const get = (id) => document.getElementById(id);
const status = document.querySelector('[role="status"]');
let sessionId, socket, context, micStream, micNode, micSource, draft, version;
let playAt = 0, playStarted = 0, playedItem = null, sources = [], turns = 0;
let playing = [], lastAssistant = null, draftDirty = false, authTimer, voiceError = false, captureLoaded = false;
let reviewBusy = false, draftFrozen = false, editingRequest = null;
let assistantItem = null;
const interruptedItems = new Set();
let microphoneOn = false, playbackOn = true, microphoneBusy = false;
let voiceConnected = false, responsePending = false;
let avatarConnected = false;
const streamingItems = new Map();

function conversationState() {
  const state = playing.length ? 'playing' : responsePending ? 'processing'
    : microphoneOn ? 'listening' : voiceConnected ? 'ready' : 'idle';
  const labels = { playing: 'Antwort wird abgespielt', processing: 'Wird verarbeitet',
    listening: 'Mikrofon aktiv · Hoert zu', ready: 'Bereit · Mikrofon aus', idle: 'Keine Sprachverbindung' };
  get('conversation-state').dataset.state = state;
  get('conversation-state').textContent = labels[state];
  get('interrupt').disabled = !voiceConnected || (!playing.length && !responsePending && !avatarConnected);
}

function avatarControl(method, ...args) {
  try {
    Promise.resolve(window.avatarPlayer?.[method]?.(...args)).catch(() => {
      get('avatar-state').textContent = 'Avatar nicht verfuegbar. Audio-Modus bleibt aktiv.';
    });
  } catch {
    get('avatar-state').textContent = 'Avatar nicht verfuegbar. Audio-Modus bleibt aktiv.';
  }
}

function audioControls() {
  get('microphone').setAttribute('aria-pressed', String(microphoneOn));
  get('microphone').textContent = microphoneOn ? 'Mikrofon stummschalten' : 'Mikrofon einschalten';
  get('playback').setAttribute('aria-pressed', String(playbackOn));
  get('playback').textContent = playbackOn ? 'Ton ausschalten' : 'Ton einschalten';
  get('voice-hint').textContent = microphoneOn
    ? 'Mikrofon aktiv. Sprechen Sie – auch „OK, jetzt Zusammenfassung erstellen“.'
    : 'Mikrofon aus. Sie koennen weiterhin tippen.';
  conversationState();
}

function show(message, failed = false) {
  status.textContent = message;
  status.classList.toggle('error', failed);
}

async function api(path, data, method = 'POST') {
  const response = await fetch(path, {
    method, headers: { 'Content-Type': 'application/json', 'X-Local-Client': '1' },
    body: data === undefined ? undefined : JSON.stringify(data),
    signal: AbortSignal.timeout(180000),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || result.detail || `HTTP ${response.status}`);
  return result;
}

async function action(callback) {
  try { await callback(); } catch (error) { show(error.message, true); }
}

async function checkReadiness() {
  get('retry').disabled = true;
  clearTimeout(authTimer);
  try {
    const response = await fetch('/api/readiness', { cache: 'no-store', signal: AbortSignal.timeout(5000) });
    const result = await response.json();
    if (!result.auth) throw new Error('Unerwartete Antwort des lokalen Dienstes.');
    show(result.ready ? 'Bereit zum Starten' : 'Noch nicht verbunden');
    get('detail').textContent = result.message;
    get('delivery-mode').textContent = result.voice_delivery_mode === 'streaming'
      ? 'Streaming-Demo: Antworten werden ohne unabhaengige Vorabpruefung gesprochen.'
      : 'Strikter Modus: Antworten werden vor der Wiedergabe geprueft.';
    const applicationIdentity = result.auth.mode === 'application';
    get('sign-in').textContent = applicationIdentity ? 'App-Zugriff verbinden' : 'Microsoft 365 anmelden';
    get('auth-mode').textContent = applicationIdentity
      ? 'App-Identitaet: synthetische Einzelnutzer-Demo, keine benutzerbezogene SharePoint-Berechtigungspruefung.'
      : 'Delegierter Zugriff: SharePoint-Zugriff mit Ihrem angemeldeten Konto.';
    get('sign-in').disabled = !result.can_sign_in || ['starting', 'pending', 'signed_in'].includes(result.auth.status);
    get('start').disabled = !result.ready || Boolean(sessionId);
    get('avatar-enabled').disabled = Boolean(sessionId) || !result.avatar_available;
    if (!result.avatar_available) get('avatar-enabled').checked = false;
    if (!sessionId) get('avatar-state').textContent = result.avatar_available
      ? 'Optionaler Avatar · nur Streaming. Ohne Auswahl: Audio-Modus.'
      : 'Audio-Modus · Avatar nicht aktiviert.';
    get('login').hidden = result.auth.status !== 'pending';
    if (result.auth.status === 'pending') {
      const url = new URL(result.auth.verification_uri);
      if (url.protocol !== 'https:') throw new Error('Ungueltige Anmeldeadresse.');
      get('verification').href = url.href;
      get('device-code').textContent = result.auth.user_code;
    }
    if (result.auth.status === 'error') show(result.auth.message, true);
    if (['starting', 'pending'].includes(result.auth.status)) authTimer = setTimeout(checkReadiness, 2500);
  } catch (error) {
    get('start').disabled = true;
    get('sign-in').disabled = true;
    show('Verbindung fehlgeschlagen', true);
    get('detail').textContent = error.message;
  } finally { get('retry').disabled = false; }
}

function send(message) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
  else throw new Error('Keine Sprachverbindung.');
}

function stopPlayback(report = true) {
  avatarControl('interrupt');
  if (assistantItem) interruptedItems.add(assistantItem);
  if (playing.length && playedItem) {
    const milliseconds = Math.max(0, Math.floor((context.currentTime - playStarted) * 1000));
    if (report && socket?.readyState === WebSocket.OPEN) send({ type: 'interrupt', item_id: playedItem, milliseconds });
    if (lastAssistant) lastAssistant.dataset.interrupted = 'true';
  }
  for (const node of playing) { try { node.stop(); } catch {} }
  playing = [];
  playedItem = null;
  playAt = context?.currentTime || 0;
  conversationState();
}

function playAudio(message) {
  if (!playbackOn || interruptedItems.has(message.item_id)) return;
  const bytes = Uint8Array.from(atob(message.audio), (character) => character.charCodeAt(0));
  const samples = new DataView(bytes.buffer);
  const buffer = context.createBuffer(1, bytes.length / 2, 24000);
  const channel = buffer.getChannelData(0);
  for (let index = 0; index < channel.length; index++) channel[index] = samples.getInt16(index * 2, true) / 32768;
  if (playedItem !== message.item_id) {
    playedItem = message.item_id;
    playStarted = Math.max(context.currentTime + 0.05, playAt);
  }
  const node = context.createBufferSource();
  node.buffer = buffer;
  node.connect(context.destination);
  playAt = Math.max(context.currentTime + 0.05, playAt);
  node.start(playAt);
  playAt += buffer.duration;
  playing.push(node);
  responsePending = false;
  conversationState();
  node.onended = () => {
    playing = playing.filter((entry) => entry !== node);
    conversationState();
  };
}

function transcript(role, text, references = []) {
  const item = document.createElement('li');
  item.className = role;
  const label = document.createElement('strong');
  label.textContent = role === 'user' ? 'Sie' : 'Denkpartner';
  const content = document.createElement('p');
  content.textContent = text;
  item.append(label, content);
  for (const reference of references) {
    const source = sources.find((entry) => entry.document_id === reference.document_id);
    if (source) {
      const link = document.createElement('a');
      link.href = source.url;
      link.textContent = `${source.document_id}${reference.page ? `, Seite ${reference.page}` : ''}`;
      link.target = '_blank'; link.rel = 'noopener noreferrer';
      item.append(link, ' ');
    }
  }
  get('transcript').append(item);
  get('transcript-count').textContent = `(${get('transcript').children.length})`;
  if (get('transcript-panel').open) get('transcript').scrollTop = get('transcript').scrollHeight;
  if (role === 'assistant') lastAssistant = item;
  return item;
}

function streamingItem(itemId) {
  if (!streamingItems.has(itemId)) {
    const item = transcript('assistant', '');
    item.dataset.streaming = 'true';
    streamingItems.set(itemId, item);
  }
  return streamingItems.get(itemId);
}

async function microphone(enabled) {
  if (!enabled) {
    micStream?.getTracks().forEach((track) => track.stop());
    micNode?.disconnect(); micSource?.disconnect();
    micStream = micNode = micSource = null;
    microphoneOn = false;
    audioControls();
    return;
  }
  micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
  if (socket?.readyState !== WebSocket.OPEN) {
    await microphone(false);
    throw new Error('Sprachverbindung beendet. Bitte eine neue Sitzung starten.');
  }
  if (!captureLoaded) {
    await context.audioWorklet.addModule('/static/microphone.js');
    captureLoaded = true;
  }
  micNode = new AudioWorkletNode(context, 'pcm-capture');
  micNode.port.onmessage = ({ data }) => {
    if (socket?.readyState !== WebSocket.OPEN) return;
    const bytes = new Uint8Array(data);
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    send({ type: 'audio', audio: btoa(binary) });
  };
  micSource = context.createMediaStreamSource(micStream);
  micSource.connect(micNode);
  micNode.connect(context.destination);
  microphoneOn = true;
  audioControls();
}

function showDraft(message) {
  const firstDraft = get('review').hidden;
  responsePending = false;
  stopPlayback();
  draft = message.summary; version = message.version; draftDirty = false;
  draftFrozen = Boolean(message.frozen);
  get('review').hidden = false;
  get('topic').value = draft.topic; get('stance').value = draft.haltung;
  get('questions').value = draft.offene_fragen.join('\n');
  get('counterpositions').value = draft.gegenpositionen.join('\n');
  get('summary-state').textContent = `Entwurf ${version} zur Pruefung`;
  get('save').disabled = false; get('finish').disabled = true;
  reviewControls(false);
  if (draftFrozen) get('summary-state').textContent = `Freigegebene Version ${version}; Speicherung erneut versuchen`;
  if (message.result) saved(message.result);
  if (firstDraft) {
    get('summary-title').focus({ preventScroll: true });
    get('summary-title').scrollIntoView({ block: 'start', behavior: 'instant' });
  }
}

function reviewControls(busy) {
  reviewBusy = busy;
  get('review').querySelectorAll('input,textarea').forEach((field) => {
    field.disabled = busy || draftFrozen;
  });
  get('update-draft').disabled = busy || draftFrozen;
  get('save').disabled = busy || draftDirty;
}

async function recoverReview() {
  const state = await api(`/api/sessions/${sessionId}/draft`, undefined, 'GET');
  if (state.frozen || state.result) showDraft(state);
  else {
    draftFrozen = false;
    reviewControls(false);
  }
  return state;
}

function saved(result) {
  draftFrozen = true;
  get('summary-state').textContent = `Gespeichert: ${result.filename}`;
  get('download').href = result.url; get('download').hidden = false;
  get('save').disabled = true;
  get('update-draft').disabled = true;
  get('review').querySelectorAll('input,textarea').forEach((field) => { field.disabled = true; });
  show('Word-Dokument in SharePoint gespeichert.');
}

function received(message) {
  if (message.type === 'avatar_start') avatarControl('start', message.ice_servers, message => {
    if (message.type === 'avatar_ready') avatarConnected = true;
    send(message);
  });
  if (message.type === 'avatar_answer') avatarControl('answer', message.server_sdp);
  if (message.type === 'avatar_resume') avatarControl('resume');
  if (message.type === 'avatar_failed') {
    voiceError = true;
    avatarControl('stop');
    get('avatar-state').textContent = message.message;
    get('avatar-fallback').hidden = false;
    show(message.message, true);
    socket?.close();
  }
  if (message.type === 'status') {
    show(message.message);
    if (['Antwort wird vorbereitet und geprueft.', 'Antwort wird gestreamt – ohne separate Vorabpruefung.', 'Zusammenfassung wird erstellt.'].includes(message.message)) responsePending = true;
    if (message.message === 'Bereit.') responsePending = false;
    conversationState();
  }
  if (message.type === 'error') { voiceError = true; responsePending = false; conversationState(); show(message.message, true); }
  if (message.type === 'connected') {
    voiceConnected = true;
    conversationState();
    for (const id of ['microphone', 'message', 'send', 'finish', 'stop']) get(id).disabled = false;
  }
  if (message.type === 'user') {
    stopPlayback();
    transcript('user', message.text); turns++;
    responsePending = true;
    conversationState();
    get('turn-count').textContent = `${turns} / 30 Beitraege`;
  }
  if (message.type === 'assistant') {
    responsePending = false;
    conversationState();
    assistantItem = message.item_id;
    if (streamingItems.has(message.item_id)) {
      const item = streamingItems.get(message.item_id);
      item.querySelector('p').textContent = message.text;
      item.dataset.streaming = 'false';
      for (const reference of message.sources || []) {
        const source = sources.find(entry => entry.document_id === reference.document_id);
        if (!source) continue;
        const link = document.createElement('a');
        link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        link.textContent = `${source.document_id}${reference.page ? `, Seite ${reference.page}` : ''}`;
        item.append(link, ' ');
      }
      streamingItems.delete(message.item_id);
      lastAssistant = item;
    } else transcript('assistant', message.text, message.sources);
  }
  if (message.type === 'assistant_start') {
    assistantItem = message.item_id;
    streamingItem(message.item_id);
  }
  if (message.type === 'assistant_delta' && !interruptedItems.has(message.item_id)) {
    streamingItem(message.item_id).querySelector('p').textContent += message.text;
  }
  if (message.type === 'assistant_interrupted') {
    const item = streamingItems.get(message.item_id);
    if (item) {
      item.dataset.interrupted = 'true';
      item.dataset.streaming = 'false';
      streamingItems.delete(message.item_id);
    }
  }
  if (message.type === 'audio') playAudio(message);
  if (message.type === 'interrupt') { responsePending = false; stopPlayback(false); }
  if (message.type === 'speech_started') {
    if (playing.length || avatarConnected) {
      stopPlayback();
      if (avatarConnected) send({ type: 'interrupt' });
    }
    get('voice-hint').textContent = 'Sprache erkannt. Bitte den Satz zu Ende sprechen.';
  }
  if (message.type === 'draft') { avatarControl('interrupt'); showDraft(message); }
  if (message.type === 'saved') saved(message);
}

get('retry').onclick = checkReadiness;
get('sign-in').onclick = () => action(async () => { await api('/api/auth/start'); await checkReadiness(); });
get('start').onclick = () => action(async () => {
  get('start').disabled = true;
  get('avatar-enabled').disabled = true;
  context = new AudioContext({ sampleRate: 24000 });
  captureLoaded = false; voiceError = false;
  await context.resume();
  if (context.sampleRate !== 24000) throw new Error('Dieser Browser unterstuetzt die benoetigte Abtastrate nicht. Bitte Chromium verwenden.');
  show('SharePoint-Unterlagen werden geladen; Agent wird vorbereitet.');
  try {
    const result = await api('/api/sessions', { avatar_enabled: get('avatar-enabled').checked });
    sessionId = result.session_id; sources = result.sources;
    get('session-limit').textContent = result.limits;
    get('sources').replaceChildren();
    for (const source of sources) {
      const item = document.createElement('li'), link = document.createElement('a');
      link.href = source.url; link.textContent = `${source.document_id} - ${source.title}`;
      link.target = '_blank'; link.rel = 'noopener noreferrer'; item.append(link); get('sources').append(item);
    }
    socket = new WebSocket(`ws://${location.host}/api/sessions/${sessionId}/voice`);
    get('stop').disabled = false;
    socket.onmessage = (event) => { try { received(JSON.parse(event.data)); } catch (error) { show(error.message, true); } };
    socket.onerror = () => { voiceError = true; show('Sprachverbindung fehlgeschlagen.', true); };
    socket.onclose = () => {
      avatarConnected = false;
      if (get('avatar-enabled').checked && !draft) get('avatar-fallback').hidden = false;
      voiceConnected = false; responsePending = false;
      stopPlayback(false);
      avatarControl('stop');
      microphone(false);
      for (const id of ['microphone', 'message', 'send', 'finish', 'stop']) get(id).disabled = true;
      get('delete').disabled = false;
      if (!voiceError && !draft) show('Sprachverbindung beendet.');
    };
  } catch (error) { get('start').disabled = false; throw error; }
});
get('microphone').onclick = () => action(async () => {
  if (microphoneBusy) return;
  microphoneBusy = true;
  get('microphone').disabled = true;
  try { await microphone(!microphoneOn); }
  catch (error) { await microphone(false); throw error; }
  finally {
    microphoneBusy = false;
    get('microphone').disabled = socket?.readyState !== WebSocket.OPEN;
  }
});
get('playback').onclick = () => {
  playbackOn = !playbackOn; audioControls();
  avatarControl('setMuted', !playbackOn);
  if (!playbackOn) stopPlayback();
};
get('interrupt').onclick = () => action(async () => {
  const hadAudio = playing.length && playedItem;
  stopPlayback();
  if (!hadAudio) send({ type: 'interrupt' });
  responsePending = false;
  conversationState();
});
get('composer').onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const text = get('message').value.trim();
    if (!text) return;
    stopPlayback(); send({ type: 'text', text }); get('message').value = '';
    responsePending = true; conversationState();
  });
};
get('finish').onclick = () => action(async () => {
  stopPlayback(); send({ type: 'finish' }); responsePending = true; conversationState();
});
get('stop').onclick = () => action(async () => { stopPlayback(); await microphone(false); send({ type: 'stop' }); socket.close(); });
get('delete').onclick = () => action(async () => {
  await api(`/api/sessions/${sessionId}`, undefined, 'DELETE'); location.reload();
});
get('avatar-fallback').onclick = () => action(async () => {
  get('avatar-fallback').disabled = true;
  try {
    avatarControl('stop');
    await microphone(false);
    if (socket?.readyState === WebSocket.OPEN) {
      send({ type: 'stop' });
      socket.close();
    }
    if (sessionId) await api(`/api/sessions/${sessionId}`, undefined, 'DELETE');
    get('avatar-enabled').checked = false;
    location.reload();
  } finally { get('avatar-fallback').disabled = false; }
});
get('review').oninput = () => {
  if (reviewBusy || draftFrozen) return;
  get('save').disabled = true;
  get('summary-state').textContent = 'Ungespeicherte Entwurfsaenderungen';
  if (!draftDirty) {
    draftDirty = true;
    if (socket?.readyState === WebSocket.OPEN) send({ type: 'draft_editing', version });
    editingRequest = api(`/api/sessions/${sessionId}/editing`, { version });
    editingRequest.catch((error) => { show(error.message, true); });
  }
};
get('review').onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    if (reviewBusy || draftFrozen) return;
    reviewControls(true);
    const summary = { ...draft, topic: get('topic').value, haltung: get('stance').value,
      offene_fragen: get('questions').value.split('\n').map((entry) => entry.trim()).filter(Boolean),
      gegenpositionen: get('counterpositions').value.split('\n').map((entry) => entry.trim()).filter(Boolean) };
    try {
      // Wait for the editing marker so a delayed marker cannot invalidate the new version.
      if (draftDirty) await api(`/api/sessions/${sessionId}/editing`, { version });
      if (editingRequest) await editingRequest.catch(() => {});
      showDraft(await api(`/api/sessions/${sessionId}/draft`, { summary, version }));
    } catch (error) {
      draftDirty = true;
      reviewControls(false);
      try {
        const state = await recoverReview();
        if (!state.frozen && state.version !== version) {
          version = state.version;
          draft = state.summary;
        }
      } catch { show('Verbindung unterbrochen; Aenderungen sind nicht bestaetigt.', true); }
      throw error;
    } finally { editingRequest = null; }
  });
};
get('save').onclick = () => action(async () => {
  if (draftDirty) throw new Error('Bitte zuerst die Aenderungen uebernehmen.');
  if (reviewBusy) return;
  reviewControls(true); show('Word-Dokument wird hochgeladen.');
  try { saved(await api(`/api/sessions/${sessionId}/save`, { version })); }
  catch (error) {
    // A timed-out request may already have uploaded: never unlock edits speculatively.
    draftFrozen = true;
    reviewControls(false);
    try {
      const state = await recoverReview();
      if (state.result) return;
    }
    catch { get('summary-state').textContent = 'Speicherstatus unbekannt; dieselbe Version erneut versuchen.'; }
    throw error;
  } finally { reviewBusy = false; }
});
checkReadiness();