import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    window.avatarEvents = [];
    window.avatarTracks = [];
    window.RTCRtpReceiver = class {
      static getCapabilities() { return { codecs: [{ mimeType: 'video/H264' }] }; }
    };
    window.MediaStream = class {
      constructor() { this.tracks = []; }
      addTrack(track) { this.tracks.push(track); }
      getAudioTracks() { return this.tracks.filter(t => t.kind === 'audio'); }
      getVideoTracks() { return this.tracks.filter(t => t.kind === 'video'); }
    };
    const video = document.getElementById('avatar-video');
    Object.defineProperty(video, 'srcObject', { writable: true, value: null });
    video.play = async () => {};
    video.pause = () => {};
    window.RTCPeerConnection = class {
      constructor() { window.avatarPeer = this; this.connectionState = 'new'; }
      addTransceiver() {}
      async createOffer() { return { type: 'offer', sdp: 'v=0\r\nm=audio 9\r\nm=video 9\r\n' }; }
      async setLocalDescription(description) {
        this.localDescription = description;
        this.signalingState = 'have-local-offer';
        this.onicecandidate({ candidate: null });
      }
      async setRemoteDescription() {
        this.signalingState = 'stable';
        for (const kind of ['audio', 'video']) {
          const track = { kind, stopped: false, stop() { this.stopped = true; } };
          window.avatarTracks.push(track);
          this.ontrack({ track });
        }
        this.connectionState = 'connected';
        this.onconnectionstatechange();
      }
      getReceivers() { return window.avatarTracks.map(track => ({ track })); }
      close() { this.connectionState = 'closed'; }
    };
  });
});

test('missing H264 fails before sending an incompatible SDP offer', async ({ page }) => {
  await page.evaluate(async () => {
    window.RTCRtpReceiver.getCapabilities = () => ({ codecs: [{ mimeType: 'video/VP8' }] });
    await window.avatarPlayer.start([], e => window.avatarEvents.push(e));
  });
  await expect(page.locator('#avatar-state')).toContainText('kein H.264');
  const events = await page.evaluate(() => window.avatarEvents);
  expect(events).toHaveLength(1);
  expect(events[0]).toMatchObject({
    type: 'avatar_failed', reason: 'h264_unsupported',
    diagnostics: { stage: 'codec_check', h264_supported: false, offer_sent: false },
  });
  expect(await page.evaluate(() => window.avatarPeer)).toBeUndefined();
});

test('native player negotiates once, waits for media, mutes and releases tracks', async ({ page }) => {
  await page.evaluate(async () => {
    await window.avatarPlayer.start([{ urls: ['turn:synthetic.example'] }], e => window.avatarEvents.push(e));
  });
  expect(await page.evaluate(() => window.avatarEvents.map(e => e.type))).toEqual(['avatar_offer']);
  await expect(page.locator('#avatar-video')).toBeHidden();
  await page.evaluate(() => window.avatarPlayer.answer(btoa(JSON.stringify({
    type: 'answer', sdp: 'v=0\r\nm=audio 9\r\nm=video 9\r\n',
  }))));
  await expect(page.locator('#avatar-video')).toBeVisible();
  expect(await page.evaluate(() => window.avatarEvents.map(e => e.type))).toEqual(['avatar_offer', 'avatar_ready']);
  expect(await page.locator('#avatar-video').evaluate(v => v.muted)).toBe(false);
  await page.evaluate(() => window.avatarPlayer.interrupt());
  expect(await page.locator('#avatar-video').evaluate(v => v.muted)).toBe(true);
  await page.evaluate(() => { window.avatarPlayer.setMuted(true); window.avatarPlayer.resume(); });
  expect(await page.locator('#avatar-video').evaluate(v => v.muted)).toBe(true);
  await page.evaluate(() => window.avatarPlayer.stop());
  await expect(page.locator('#avatar-video')).toBeHidden();
  expect(await page.evaluate(() => window.avatarTracks.every(t => t.stopped))).toBe(true);
  expect(await page.locator('#avatar-video').evaluate(v => v.srcObject)).toBe(null);
  expect(await page.evaluate(() => window.avatarPeer.connectionState)).toBe('closed');
});

test('invalid answer closes peer and explicitly requires audio-only restart', async ({ page }) => {
  await page.evaluate(async () => {
    await window.avatarPlayer.start([{ urls: ['turn:synthetic.example'] }], e => window.avatarEvents.push(e));
    await window.avatarPlayer.answer('invalid');
  });
  await expect(page.locator('#avatar-state')).toContainText('Avatar abwaehlen');
  await expect(page.locator('#avatar-placeholder')).toBeVisible();
  expect(await page.evaluate(() => window.avatarEvents.at(-1).type)).toBe('avatar_failed');
  expect(await page.evaluate(() => window.avatarPeer.connectionState)).toBe('closed');
  expect(await page.evaluate(() => window.avatarEvents.at(-1))).toMatchObject({
    reason: 'remote_description_failed',
    diagnostics: { stage: 'decode_answer', answer_received: true },
  });
});

test('connection failure includes ICE errors and pre-cleanup states but not credentials', async ({ page }) => {
  await page.evaluate(async () => {
    await window.avatarPlayer.start([{ urls: ['turn:relay.example'], credential: 'SUPERSECRET' }],
      e => window.avatarEvents.push(e));
    const pc = window.avatarPeer;
    pc.iceConnectionState = 'failed';
    pc.iceGatheringState = 'complete';
    pc.onicecandidateerror({
      errorCode: 701, errorText: 'Failed 192.168.0.1 turn:relay.example:3478',
      url: 'turn:relay.example:3478',
    });
    pc.connectionState = 'failed';
    pc.onconnectionstatechange();
  });
  const failure = await page.evaluate(() => window.avatarEvents.at(-1));
  expect(failure.reason).toBe('peer_failed');
  expect(failure.diagnostics.connection_state).toBe('failed');
  expect(failure.diagnostics.ice_connection_state).toBe('failed');
  expect(failure.diagnostics.offer_sent).toBe(true);
  expect(failure.diagnostics.ice_errors[0].code).toBe(701);
  for (const privateValue of ['SUPERSECRET', '192.168.0.1', 'relay.example', 'v=0']) {
    expect(JSON.stringify(failure)).not.toContain(privateValue);
  }
});

test('remote-description exception keeps useful error without dumping SDP', async ({ page }) => {
  await page.evaluate(async () => {
    await window.avatarPlayer.start([], e => window.avatarEvents.push(e));
    window.avatarPeer.setRemoteDescription = async () => {
      throw new DOMException('Video codec parameters rejected', 'OperationError');
    };
    await window.avatarPlayer.answer(btoa(JSON.stringify({ type: 'answer', sdp: 'v=0\r\nm=video 9' })));
  });
  const failure = await page.evaluate(() => window.avatarEvents.at(-1));
  expect(failure.diagnostics.error_name).toBe('OperationError');
  expect(failure.diagnostics.error_message).toBe('Video codec parameters rejected');
  expect(failure.diagnostics.stage).toBe('set_remote_description');
});

test('negotiation timeout has explicit failure and no hanging peer', async ({ page }) => {
  await page.clock.install();
  await page.evaluate(() => window.avatarPlayer.start(
    [{ urls: ['turn:synthetic.example'] }], e => window.avatarEvents.push(e),
  ));
  await page.clock.fastForward(31000);
  await expect(page.locator('#avatar-state')).toContainText('fehlgeschlagen');
  expect(await page.evaluate(() => window.avatarPeer.connectionState)).toBe('closed');
});

test('offer is sent after bounded gathering wait even without end-of-candidates', async ({ page }) => {
  await page.clock.install();
  await page.evaluate(async () => {
    RTCPeerConnection.prototype.setLocalDescription = async function(description) {
      this.localDescription = description;
      this.signalingState = 'have-local-offer';
      this.iceGatheringState = 'gathering';
    };
    await avatarPlayer.start([], event => avatarEvents.push(event));
  });
  expect(await page.evaluate(() => avatarEvents)).toEqual([]);
  await page.clock.fastForward(3001);
  expect(await page.evaluate(() => avatarEvents.map(e => e.type))).toEqual(['avatar_offer']);
  await page.evaluate(() => avatarPeer.onicecandidate({ candidate: null }));
  await page.clock.fastForward(4000);
  expect(await page.evaluate(() => avatarEvents.map(e => e.type))).toEqual(['avatar_offer']);
  await page.evaluate(() => avatarPlayer.answer(btoa(JSON.stringify({
    type: 'answer', sdp: 'v=0\r\nm=audio 9\r\nm=video 9\r\n',
  }))));
  await expect(page.locator('#avatar-video')).toBeVisible();
});

test('stop cancels gathering fallback and cannot signal from an obsolete peer', async ({ page }) => {
  await page.clock.install();
  await page.evaluate(async () => {
    RTCPeerConnection.prototype.setLocalDescription = async function(description) {
      this.localDescription = description;
      this.signalingState = 'have-local-offer';
      this.iceGatheringState = 'gathering';
    };
    await avatarPlayer.start([], event => avatarEvents.push(event));
    avatarPlayer.stop();
  });
  await page.clock.fastForward(31000);
  expect(await page.evaluate(() => avatarEvents)).toEqual([]);
});

test('failed avatar offers an explicit fresh audio-only startup', async ({ page }) => {
  await page.evaluate(() => {
    document.getElementById('avatar-enabled').checked = true;
    received({ type: 'avatar_failed', message: 'Avatar fehlgeschlagen. Audio-only neu starten.' });
  });
  await expect(page.locator('#avatar-fallback')).toBeVisible();
  await page.locator('#avatar-fallback').click();
  await expect(page.locator('#avatar-enabled')).not.toBeChecked();
  await expect(page.locator('#avatar-video')).toBeHidden();
});
