/* Native Voice Live media. ICE/SDP stay in memory and are never recorded. */
(() => {
  let peer, timer, gatheringTimer, send, muted = false, interrupted = false, ready = false;
  let startedAt = 0, phase = 'idle', offerSent = false, answerReceived = false;
  let iceErrors = [], videoCodecs = [], reportingFailure = false;
  const video = document.getElementById('avatar-video');
  const placeholder = document.getElementById('avatar-placeholder');
  const state = document.getElementById('avatar-state');
  function silence() { video.muted = muted || interrupted || !ready; }
  function stop() {
    clearTimeout(timer);
    clearTimeout(gatheringTimer);
    const old = peer;
    peer = null; ready = false;
    if (old) {
      old.ontrack = old.onconnectionstatechange = old.onicecandidate = old.onicecandidateerror = null;
      old.getReceivers().forEach(receiver => receiver.track?.stop());
      old.close();
    }
    video.pause(); video.srcObject = null; video.hidden = true;
    placeholder.hidden = false;
    silence();
  }
  function clean(value) {
    let text = typeof value === 'string' ? value.slice(0, 12000) : '';
    if (/v=0[\r\n]|a=(ice-pwd|ice-ufrag|fingerprint|candidate):/.test(text)) return '[SDP omitted]';
    return text
      .replace(/(?:https?|wss?|turns?|stun):[^\s<>"']+/gi, '[URL omitted]')
      .replace(/\bBearer\s+\S+/gi, 'Bearer [redacted]')
      .replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, '[IP omitted]')
      .replace(/\b(?:[0-9a-f]{0,4}:){2,}[0-9a-f:.]+\b/gi, '[IP omitted]')
      .replace(/\b(authorization|token|secret|password|credential|api[-_]?key)\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi, '$1=[redacted]')
      .replace(/\b[A-Za-z0-9+/_=-]{100,}\b/g, '[encoded payload omitted]')
      .replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, 1600);
  }
  function diagnostics(pc, error) {
    return {
      stage: phase,
      elapsed_ms: Math.round(performance.now() - startedAt),
      connection_state: pc?.connectionState || 'unavailable',
      ice_connection_state: pc?.iceConnectionState || 'unavailable',
      ice_gathering_state: pc?.iceGatheringState || 'unavailable',
      signaling_state: pc?.signalingState || 'unavailable',
      offer_sent: offerSent, answer_received: answerReceived,
      h264_supported: videoCodecs.includes('video/h264'), video_codecs: videoCodecs,
      audio_tracks: pc?.getReceivers().filter(r => r.track?.kind === 'audio').length || 0,
      video_tracks: pc?.getReceivers().filter(r => r.track?.kind === 'video').length || 0,
      error_name: clean(error?.name), error_message: clean(error?.message),
      ice_errors: iceErrors.slice(-8),
    };
  }
  function fail(expectedPeer, reason = 'browser_connection_failed', error) {
    if ((expectedPeer && expectedPeer !== peer) || reportingFailure) return;
    reportingFailure = true;
    const details = diagnostics(peer, error);
    console.warn('[Avatar diagnostic]', { reason, ...details });
    stop();
    state.textContent = reason === 'h264_unsupported'
      ? 'Dieser Browser unterstuetzt kein H.264 fuer den Avatar. Ohne Avatar neu starten.'
      : `Avatar fehlgeschlagen (${reason}). Stoppen, Avatar abwaehlen und erneut starten.`;
    send?.({ type: 'avatar_failed', reason, diagnostics: details });
  }
  async function start(ice, sender) {
    stop(); send = sender; interrupted = false;
    startedAt = performance.now(); phase = 'codec_check';
    offerSent = answerReceived = reportingFailure = false;
    iceErrors = []; videoCodecs = [];
    state.textContent = 'Avatar wird verbunden …';
    try {
      const codecs = RTCRtpReceiver.getCapabilities('video')?.codecs || [];
      videoCodecs = codecs.map(codec => codec.mimeType.toLowerCase()).filter(
        codec => /^video\/[a-z0-9.-]{1,30}$/.test(codec),
      ).slice(0, 20);
      if (!codecs.some(codec => codec.mimeType.toLowerCase() === 'video/h264')) {
        fail(null, 'h264_unsupported');
        return;
      }
      phase = 'create_peer';
      const pc = new RTCPeerConnection({ iceServers: ice, bundlePolicy: 'max-bundle' });
      peer = pc;
      const stream = new MediaStream();
      video.srcObject = stream;
      let offered = false;
      let startingPlayback = false;
      const connected = async () => {
        if (peer !== pc || ready || startingPlayback || pc.connectionState !== 'connected'
            || !stream.getAudioTracks().length || !stream.getVideoTracks().length) return;
        startingPlayback = true;
        phase = 'start_playback';
        try {
          await video.play();
          if (peer !== pc) return;
          ready = true; silence(); clearTimeout(timer);
          video.hidden = false; placeholder.hidden = true;
          state.textContent = 'Avatar verbunden · Streaming ohne Vorabpruefung';
          send({ type: 'avatar_ready' });
          phase = 'ready';
        } catch (error) { fail(pc, 'playback_failed', error); }
      };
      pc.ontrack = event => { stream.addTrack(event.track); connected(); };
      pc.onconnectionstatechange = () => {
        if (['failed', 'disconnected', 'closed'].includes(pc.connectionState)) {
          fail(pc, `peer_${pc.connectionState}`);
        }
        else connected();
      };
      pc.onicecandidateerror = event => {
        if (peer !== pc) return;
        const protocol = /^(stun|turn|turns):/.exec(event.url || '')?.[1];
        iceErrors.push({ code: event.errorCode, text: clean(event.errorText), protocol });
        if (iceErrors.length > 8) iceErrors.shift();
        // A single TURN endpoint failure is not necessarily fatal; others may connect.
      };
      const sendOffer = () => {
        if (peer !== pc || offered || !pc.localDescription) return;
        try {
          const client_sdp = btoa(JSON.stringify({ type: 'offer', sdp: pc.localDescription.sdp }));
          if (client_sdp.length > 131072) return fail(pc, 'offer_too_large');
          offered = true;
          clearTimeout(gatheringTimer);
          offerSent = true; phase = 'waiting_for_answer';
          send({ type: 'avatar_offer', client_sdp });
        } catch (error) { fail(pc, 'offer_send_failed', error); }
      };
      pc.onicecandidate = event => {
        if (!event.candidate) sendOffer();
      };
      timer = setTimeout(() => fail(pc, 'browser_handshake_timeout'), 30000);
      pc.addTransceiver('video', { direction: 'recvonly' });
      pc.addTransceiver('audio', { direction: 'recvonly' });
      phase = 'create_offer';
      const offer = await pc.createOffer();
      if (peer === pc) {
        phase = 'set_local_description';
        await pc.setLocalDescription(offer);
        if (peer === pc && !offered) {
          phase = 'gathering_candidates';
          if (pc.iceGatheringState === 'complete') sendOffer();
          else gatheringTimer = setTimeout(sendOffer, 3000);
        }
      }
    } catch (error) { fail(null, 'browser_setup_failed', error); }
  }
  async function answer(encoded) {
    const pc = peer;
    try {
      if (!peer || peer.signalingState !== 'have-local-offer'
          || typeof encoded !== 'string' || encoded.length > 131072) {
        throw new Error('Unexpected avatar answer or invalid answer size.');
      }
      phase = 'decode_answer'; answerReceived = true;
      const description = JSON.parse(atob(encoded));
      if (description.type !== 'answer' || typeof description.sdp !== 'string'
          || !description.sdp.startsWith('v=0')) throw new Error('Invalid avatar answer shape.');
      phase = 'set_remote_description';
      await pc.setRemoteDescription(description);
      if (peer === pc && !ready) phase = 'waiting_for_media';
    } catch (error) { fail(pc, 'remote_description_failed', error); }
  }
  window.avatarPlayer = {
    start, answer, stop,
    interrupt() { interrupted = true; silence(); },
    resume() { interrupted = false; silence(); },
    setMuted(value) { muted = value; silence(); },
  };
  window.addEventListener('pagehide', stop);
})();
