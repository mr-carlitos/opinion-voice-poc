const get = (id) => document.getElementById(id);
const status = document.querySelector('[role="status"]');
let sessionId, socket, context, micStream, micNode, micSource, draft, version;
let playAt = 0, playStarted = 0, playedItem = null, sources = [], turns = 0;
let playing = [], lastAssistant = null, draftDirty = false, authTimer, voiceError = false, captureLoaded = false;

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
    get('sign-in').disabled = !result.can_sign_in || ['starting', 'pending', 'signed_in'].includes(result.auth.status);
    get('start').disabled = !result.ready || Boolean(sessionId);
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
    show('Verbindung fehlgeschlagen', true);
    get('detail').textContent = error.message;
  } finally { get('retry').disabled = false; }
}

function send(message) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
  else throw new Error('Keine Sprachverbindung.');
}

function stopPlayback(report = true) {
  if (playing.length && playedItem) {
    const milliseconds = Math.max(0, Math.floor((context.currentTime - playStarted) * 1000));
    if (report && socket?.readyState === WebSocket.OPEN) send({ type: 'interrupt', item_id: playedItem, milliseconds });
    if (lastAssistant) lastAssistant.dataset.interrupted = 'true';
  }
  for (const node of playing) { try { node.stop(); } catch {} }
  playing = [];
  playedItem = null;
  playAt = context?.currentTime || 0;
}

function playAudio(message) {
  if (!get('playback').checked) return;
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
  node.onended = () => { playing = playing.filter((entry) => entry !== node); };
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
  item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  if (role === 'assistant') lastAssistant = item;
}

async function microphone(enabled) {
  if (!enabled) {
    micStream?.getTracks().forEach((track) => track.stop());
    micNode?.disconnect(); micSource?.disconnect();
    micStream = micNode = micSource = null;
    return;
  }
  micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
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
}

function showDraft(message) {
  stopPlayback();
  draft = message.summary; version = message.version; draftDirty = false;
  get('review').hidden = false;
  get('topic').value = draft.topic; get('stance').value = draft.haltung;
  get('questions').value = draft.offene_fragen.join('\n');
  get('counterpositions').value = draft.gegenpositionen.join('\n');
  get('summary-state').textContent = `Entwurf ${version} zur Pruefung`;
  get('save').disabled = false; get('finish').disabled = true;
}

function saved(result) {
  get('summary-state').textContent = `Gespeichert: ${result.filename}`;
  get('download').href = result.url; get('download').hidden = false;
  get('save').disabled = true;
  get('update-draft').disabled = true;
  get('review').querySelectorAll('input,textarea').forEach((field) => { field.disabled = true; });
  show('Word-Dokument in SharePoint gespeichert.');
}

function received(message) {
  if (message.type === 'status') show(message.message);
  if (message.type === 'error') { voiceError = true; show(message.message, true); }
  if (message.type === 'connected') {
    for (const id of ['microphone', 'message', 'send', 'finish', 'stop']) get(id).disabled = false;
  }
  if (message.type === 'user') {
    transcript('user', message.text); turns++;
    get('turn-count').textContent = `${turns} / 30 Beitraege`;
  }
  if (message.type === 'assistant') transcript('assistant', message.text, message.sources);
  if (message.type === 'audio') playAudio(message);
  if (message.type === 'interrupt') stopPlayback(false);
  if (message.type === 'speech_started') stopPlayback();
  if (message.type === 'draft') showDraft(message);
  if (message.type === 'saved') saved(message);
}

get('retry').onclick = checkReadiness;
get('sign-in').onclick = () => action(async () => { await api('/api/auth/start'); await checkReadiness(); });
get('start').onclick = () => action(async () => {
  get('start').disabled = true;
  context = new AudioContext({ sampleRate: 24000 });
  captureLoaded = false; voiceError = false;
  await context.resume();
  if (context.sampleRate !== 24000) throw new Error('Dieser Browser unterstuetzt die benoetigte Abtastrate nicht. Bitte Chromium verwenden.');
  show('SharePoint-Unterlagen werden geladen; Agent wird vorbereitet.');
  try {
    const result = await api('/api/sessions');
    sessionId = result.session_id; sources = result.sources;
    get('session-limit').textContent = result.limits;
    get('sources').replaceChildren();
    for (const source of sources) {
      const item = document.createElement('li'), link = document.createElement('a');
      link.href = source.url; link.textContent = `${source.document_id} - ${source.title}`;
      link.target = '_blank'; link.rel = 'noopener noreferrer'; item.append(link); get('sources').append(item);
    }
    socket = new WebSocket(`ws://${location.host}/api/sessions/${sessionId}/voice`);
    socket.onmessage = (event) => { try { received(JSON.parse(event.data)); } catch (error) { show(error.message, true); } };
    socket.onerror = () => { voiceError = true; show('Sprachverbindung fehlgeschlagen.', true); };
    socket.onclose = () => {
      microphone(false); get('microphone').checked = false;
      for (const id of ['microphone', 'message', 'send', 'finish', 'stop']) get(id).disabled = true;
      get('delete').disabled = false;
      if (!voiceError) show('Sprachverbindung beendet.');
    };
  } catch (error) { get('start').disabled = false; throw error; }
});
get('microphone').onchange = () => action(async () => {
  try { await microphone(get('microphone').checked); }
  catch (error) { get('microphone').checked = false; await microphone(false); throw error; }
});
get('playback').onchange = () => { if (!get('playback').checked) stopPlayback(); };
get('composer').onsubmit = (event) => {
  event.preventDefault();
  action(async () => { stopPlayback(); send({ type: 'text', text: get('message').value }); get('message').value = ''; });
};
get('finish').onclick = () => action(async () => { stopPlayback(); send({ type: 'finish' }); });
get('stop').onclick = () => action(async () => { stopPlayback(); await microphone(false); send({ type: 'stop' }); socket.close(); });
get('delete').onclick = () => action(async () => {
  await api(`/api/sessions/${sessionId}`, undefined, 'DELETE'); location.reload();
});
get('review').oninput = () => {
  get('save').disabled = true;
  get('summary-state').textContent = 'Ungespeicherte Entwurfsaenderungen';
  if (!draftDirty) {
    draftDirty = true;
    if (socket?.readyState === WebSocket.OPEN) send({ type: 'draft_editing' });
    action(async () => { await api(`/api/sessions/${sessionId}/editing`); });
  }
};
get('review').onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const summary = { ...draft, topic: get('topic').value, haltung: get('stance').value,
      offene_fragen: get('questions').value.split('\n').map((entry) => entry.trim()).filter(Boolean),
      gegenpositionen: get('counterpositions').value.split('\n').map((entry) => entry.trim()).filter(Boolean) };
    showDraft(await api(`/api/sessions/${sessionId}/draft`, { summary }));
  });
};
get('save').onclick = () => action(async () => {
  if (draftDirty) throw new Error('Bitte zuerst die Aenderungen uebernehmen.');
  get('save').disabled = true; show('Word-Dokument wird hochgeladen.');
  try { saved(await api(`/api/sessions/${sessionId}/save`, { version })); }
  catch (error) { get('save').disabled = false; throw error; }
});
checkReadiness();