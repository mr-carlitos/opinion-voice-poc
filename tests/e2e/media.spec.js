import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

async function mockCapture(page) {
  await page.evaluate(() => {
    window.mediaTest = { captures: 0, loaded: 0, stopped: 0, disconnected: 0, sent: [] };
    socket = {
      readyState: WebSocket.OPEN,
      send: data => window.mediaTest.sent.push(JSON.parse(data)),
    };
    context = {
      destination: {},
      audioWorklet: { addModule: async () => { window.mediaTest.loaded++; } },
      createMediaStreamSource: () => ({
        connect() {},
        disconnect() { window.mediaTest.disconnected++; },
      }),
    };
    window.AudioWorkletNode = class {
      constructor() { this.port = {}; }
      connect() {}
      disconnect() { window.mediaTest.disconnected++; }
    };
    navigator.mediaDevices.getUserMedia = async () => {
      window.mediaTest.captures++;
      return { getTracks: () => [{ stop() { window.mediaTest.stopped++; } }] };
    };
    received({ type: 'connected' });
  });
}

test('actual PCM worklet clips samples, retains partial frames and never reuses sent buffers', async ({ page }) => {
  const response = await page.request.get('/static/microphone.js');
  expect(response.ok()).toBe(true);
  const source = await response.text();
  const result = await page.evaluate(source => {
    let Processor;
    const frames = [];
    const Base = class { constructor() { this.port = { postMessage: data => frames.push(data) }; } };
    new Function('AudioWorkletProcessor', 'registerProcessor', source)(
      Base, (name, implementation) => {
        if (name !== 'pcm-capture') throw new Error('Unexpected processor name');
        Processor = implementation;
      },
    );
    const capture = new Processor();
    const alive = [capture.process([]), capture.process([[]])];
    capture.process([[new Float32Array([-2, -1, -0.5, 0, 0.5, 1, 2])]]);
    const partial = { count: frames.length, offset: capture.offset };
    capture.process([[new Float32Array(2393)]]);
    const first = new Int16Array(frames[0]);
    capture.process([[new Float32Array(2400).fill(1)]]);
    return {
      alive, partial, count: frames.length, distinct: frames[0] !== frames[1],
      first: Array.from(first.slice(0, 7)), unchanged: first[2399],
      second: new Int16Array(frames[1])[0], offset: capture.offset,
    };
  }, source);
  expect(result).toEqual({
    alive: [true, true], partial: { count: 0, offset: 7 }, count: 2, distinct: true,
    first: [-32768, -32768, -16384, 0, 16383, 32767, 32767],
    unchanged: 0, second: 32767, offset: 0,
  });
});

test('capture toggles release resources, reuse the worklet module and send PCM only while connected', async ({ page }) => {
  await mockCapture(page);
  const mic = page.locator('#microphone');
  for (let cycle = 0; cycle < 2; cycle++) {
    await mic.click();
    await expect(mic).toHaveAttribute('aria-pressed', 'true');
    await page.evaluate(() => micNode.port.onmessage({ data: new Uint8Array([0, 128, 255, 127]).buffer }));
    await mic.click();
    await expect(mic).toHaveAttribute('aria-pressed', 'false');
  }
  expect(await page.evaluate(() => window.mediaTest)).toEqual({
    captures: 2, loaded: 1, stopped: 2, disconnected: 4,
    sent: [{ type: 'audio', audio: 'AID/fw==' }, { type: 'audio', audio: 'AID/fw==' }],
  });
  await mic.click();
  await page.evaluate(() => {
    socket.readyState = WebSocket.CLOSED;
    micNode.port.onmessage({ data: new ArrayBuffer(2) });
  });
  expect(await page.evaluate(() => window.mediaTest.sent.length)).toBe(2);
  await page.evaluate(() => microphone(false));
});

for (const failure of ['permission', 'worklet']) {
  test(`microphone ${failure} failure is visible and releases all acquired resources`, async ({ page }) => {
    await mockCapture(page);
    await page.evaluate(failure => {
      if (failure === 'permission') {
        navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Synthetic permission denied', 'NotAllowedError'); };
      } else {
        context.audioWorklet.addModule = async () => { throw new Error('Synthetic worklet failure'); };
      }
    }, failure);
    await page.locator('#microphone').click();
    await expect(page.getByRole('status')).toContainText(
      failure === 'permission' ? 'Synthetic permission denied' : 'Synthetic worklet failure',
    );
    await expect(page.locator('#microphone')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('#microphone')).toBeEnabled();
    expect(await page.evaluate(() => [micStream, micNode, micSource])).toEqual([null, null, null]);
    expect(await page.evaluate(() => window.mediaTest.stopped)).toBe(failure === 'worklet' ? 1 : 0);
  });
}

test('connection loss while waiting for permission stops the newly acquired stream', async ({ page }) => {
  await mockCapture(page);
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = () => new Promise(resolve => {
      window.grantCapture = () => resolve({ getTracks: () => [{ stop() { window.mediaTest.stopped++; } }] });
    });
  });
  await page.locator('#microphone').click();
  await expect(page.locator('#microphone')).toBeDisabled();
  await page.evaluate(() => { socket.readyState = WebSocket.CLOSED; window.grantCapture(); });
  await expect(page.getByRole('status')).toContainText('Sprachverbindung beendet');
  expect(await page.evaluate(() => window.mediaTest.stopped)).toBe(1);
  expect(await page.evaluate(() => microphoneOn)).toBe(false);
});

test('PCM playback decodes signed little-endian samples and queues chunks without overlap', async ({ page }) => {
  const result = await page.evaluate(() => {
    window.audioNodes = [];
    context = {
      currentTime: 0, destination: {},
      createBuffer: (channels, length, rate) => {
        const samples = new Float32Array(length);
        return { getChannelData: () => samples, duration: length / rate, samples, rate, channels };
      },
      createBufferSource: () => {
        const node = {
          connect() {}, start(time) { this.started = time; }, stop() { this.stopped = true; },
        };
        window.audioNodes.push(node);
        return node;
      },
    };
    received({ type: 'connected' });
    received({ type: 'audio', item_id: 'answer', audio: 'AID/fwAA' });
    received({ type: 'audio', item_id: 'answer', audio: 'AID/fwAA' });
    return window.audioNodes.map(node => ({
      samples: Array.from(node.buffer.samples), started: node.started,
      duration: node.buffer.duration, rate: node.buffer.rate, channels: node.buffer.channels,
    }));
  });
  expect(result[0].samples).toEqual([-1, 32767 / 32768, 0]);
  expect(result[0].rate).toBe(24000);
  expect(result[0].channels).toBe(1);
  expect(result[1].started).toBeCloseTo(result[0].started + result[0].duration, 10);
  await expect(page.locator('#conversation-state')).toHaveAttribute('data-state', 'playing');
  await page.evaluate(() => window.audioNodes[0].onended());
  expect(await page.evaluate(() => playing.length)).toBe(1);
  await page.evaluate(() => window.audioNodes[1].onended());
  await expect(page.locator('#conversation-state')).toHaveAttribute('data-state', 'ready');
  await page.locator('#playback').click();
  await page.evaluate(() => received({ type: 'audio', item_id: 'muted', audio: 'AID/fwAA' }));
  expect(await page.evaluate(() => window.audioNodes.length)).toBe(2);
});

test('transcripts escape HTML and source updates ignore unknown IDs without duplicating links', async ({ page }) => {
  await page.evaluate(() => {
    sources = [{ document_id: 'D01', url: 'https://demo.sharepoint.com/source.pdf' }];
    received({ type: 'assistant', item_id: 'answer', text: '<img src=x onerror="window.injected=true">', sources: [] });
    received({ type: 'assistant_sources', item_id: 'unknown', source_status: 'checked', sources: [] });
    for (let repeat = 0; repeat < 2; repeat++) received({
      type: 'assistant_sources', item_id: 'answer', source_status: 'checked',
      sources: [{ document_id: 'D01', page: 2 }, { document_id: 'invented' }],
    });
  });
  await expect(page.locator('#transcript img')).toHaveCount(0);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
  const links = page.locator('#transcript a');
  await expect(links).toHaveCount(1);
  await expect(links).toHaveText('D01, Seite 2');
  await expect(links).toHaveAttribute('target', '_blank');
  await expect(links).toHaveAttribute('rel', 'noopener noreferrer');
});
