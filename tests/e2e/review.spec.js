import { test, expect } from '@playwright/test';

const summary = {
  topic: 'Pilot', haltung: 'Unentschieden', offene_fragen: ['Kosten?'],
  gegenpositionen: [], sources: [],
};

test('post-response sources attach to the original answer without changing speech text', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    sources = [{ document_id: 'D01', url: 'https://demo.sharepoint.com/source.pdf' }];
    received({ type: 'assistant_start', item_id: 'first' });
    received({ type: 'assistant', item_id: 'first', text: 'Der Pilot umfasst 30 Fahrzeuge.',
      sources: [], source_status: 'pending' });
    received({ type: 'assistant_start', item_id: 'second' });
    received({ type: 'assistant', item_id: 'second', text: 'Ihre Meinung?', sources: [] });
    received({ type: 'assistant_sources', item_id: 'first', source_status: 'checked',
      sources: [{ document_id: 'D01', page: 1 }] });
  });
  await expect(page.locator('#transcript .assistant').first().locator('p')).toHaveText('Der Pilot umfasst 30 Fahrzeuge.');
  await expect(page.locator('#transcript .assistant').first().locator('a')).toHaveText('D01, Seite 1');
  await expect(page.locator('#transcript .assistant').last().locator('a')).toHaveCount(0);
  await page.evaluate(() => received({
    type: 'assistant_sources', item_id: 'second', source_status: 'failed', sources: [],
  }));
  await expect(page.locator('#transcript .assistant').last()).toContainText('nicht abgeschlossen');
});

test('streaming transcript updates one item and preserves interruption state', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    received({ type: 'assistant_start', item_id: 'stream-1' });
    received({ type: 'assistant_delta', item_id: 'stream-1', text: 'Guten ' });
    received({ type: 'assistant_delta', item_id: 'stream-1', text: 'Tag.' });
  });
  await expect(page.locator('#transcript .assistant')).toHaveCount(1);
  await expect(page.locator('#transcript .assistant p')).toHaveText('Guten Tag.');
  await page.evaluate(() => received({
    type: 'assistant', item_id: 'stream-1', text: 'Guten Tag.', sources: [],
    evidence_status: 'not_independently_verified',
  }));
  await expect(page.locator('#transcript .assistant')).toHaveCount(1);
  await page.evaluate(() => {
    received({ type: 'assistant_start', item_id: 'stream-2' });
    received({ type: 'assistant_delta', item_id: 'stream-2', text: 'Unvollstaendig' });
    received({ type: 'assistant_interrupted', item_id: 'stream-2' });
  });
  await expect(page.locator('#transcript .assistant').last()).toHaveAttribute('data-interrupted', 'true');
});

test('voice controls are accessible buttons with explicit audio state', async ({ page }) => {
  await page.route('**/api/readiness', async route => {
    const response = await route.fetch();
    const readiness = await response.json();
    await route.fulfill({ json: { ...readiness, avatar_available: false } });
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Mikrofon einschalten' })).toBeDisabled();
  await expect(page.locator('#microphone')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('#playback')).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Ton ausschalten' }).click();
  await expect(page.locator('#playback')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('button', { name: 'Ton einschalten' })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Avatar verwenden' })).toBeDisabled();
  await expect(page.getByRole('checkbox', { name: 'Avatar verwenden' })).not.toBeChecked();
});

test('stage offers honest audio fallback and secondary accessible details', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#avatar-video')).toBeHidden();
  await expect(page.locator('#avatar-placeholder')).toBeVisible();
  await expect(page.locator('#avatar-state')).toContainText('Audio-Modus');
  await expect(page.getByText('OK, jetzt Zusammenfassung erstellen', { exact: false })).toBeVisible();
  await expect(page.locator('#transcript')).toBeVisible();
  await page.locator('#transcript').focus();
  await expect(page.locator('#transcript')).toBeFocused();
  await page.locator('#sources-panel summary').click();
  await expect(page.locator('#sources')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('state distinguishes listening, processing and actual playback without capturing a microphone', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    received({ type: 'connected' });
    microphoneOn = true;
    audioControls();
  });
  await expect(page.locator('#conversation-state')).toHaveAttribute('data-state', 'listening');
  await page.evaluate(() => received({ type: 'status', message: 'Antwort wird vorbereitet und geprueft.' }));
  await expect(page.locator('#conversation-state')).toHaveAttribute('data-state', 'processing');
  await page.evaluate(() => {
    context = {
      currentTime: 0, destination: {},
      createBuffer: () => ({ getChannelData: () => new Float32Array(1), duration: 1 }),
      createBufferSource: () => ({ connect() {}, start() {}, stop() {} }),
    };
    received({ type: 'audio', item_id: 'answer', audio: 'AAA=' });
  });
  await expect(page.locator('#conversation-state')).toHaveAttribute('data-state', 'playing');
  await page.evaluate(() => playing[0].onended());
  await expect(page.locator('#conversation-state')).toHaveAttribute('data-state', 'listening');
});

test('interrupt and mute use optional avatar hooks while PCM remains the baseline', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    window.avatarCalls = [];
    window.avatarPlayer = {
      interrupt: () => window.avatarCalls.push('interrupt'),
      setMuted: muted => window.avatarCalls.push(['muted', muted]),
    };
    socket = { readyState: WebSocket.OPEN, send: () => {} };
    received({ type: 'connected' });
    received({ type: 'status', message: 'Antwort wird vorbereitet und geprueft.' });
  });
  await page.locator('#interrupt').click();
  await expect(page.locator('#conversation-state')).toHaveAttribute('data-state', 'ready');
  await page.locator('#playback').click();
  expect(await page.evaluate(() => window.avatarCalls)).toEqual(['interrupt', ['muted', true], 'interrupt']);
});

test('first draft reveals and focuses review but subsequent drafts preserve keyboard focus', async ({ page }) => {
  await openReview(page);
  await expect(page.locator('#summary-title')).toBeFocused();
  await page.locator('#stance').focus();
  await page.evaluate(summary => received({ type: 'draft', summary, version: 2 }), summary);
  await expect(page.locator('#stance')).toBeFocused();
  await expect(page.locator('#summary-state')).toHaveText('Entwurf 2 zur Pruefung');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

async function openReview(page) {
  await page.goto('/');
  await page.evaluate((summary) => {
    sessionId = 'local-test';
    received({ type: 'draft', summary, version: 1 });
  }, summary);
}

test('late audio for an interrupted answer is not played', async ({ page }) => {
  await page.goto('/');
  const blocked = await page.evaluate(() => {
    received({ type: 'assistant', item_id: 'old-answer', text: 'Antwort', sources: [] });
    received({ type: 'interrupt' });
    // No AudioContext exists: reaching playback would throw rather than return.
    received({ type: 'audio', item_id: 'old-answer', audio: 'AAA=' });
    return interruptedItems.has('old-answer');
  });
  expect(blocked).toBe(true);
});

test('speech onset stops playback immediately without waiting for transcription', async ({ page }) => {
  await page.goto('/');
  const result = await page.evaluate(() => {
    const sent = [];
    let stopped = 0;
    context = { currentTime: 4 };
    socket = { readyState: WebSocket.OPEN, send: value => sent.push(JSON.parse(value)) };
    assistantItem = playedItem = 'playing-answer';
    playStarted = 3;
    playing = [{ stop: () => { stopped++; } }, { stop: () => { stopped++; } }];
    received({ type: 'speech_started' });
    received({ type: 'speech_started' });
    received({ type: 'audio', item_id: 'playing-answer', audio: 'AAA=' });
    return { stopped, sent, queued: playing.length, blocked: interruptedItems.has('playing-answer') };
  });
  expect(result.stopped).toBe(2);
  expect(result.queued).toBe(0);
  expect(result.blocked).toBe(true);
  expect(result.sent).toEqual([{ type: 'interrupt', item_id: 'playing-answer', milliseconds: 1000 }]);
});

test('speech onset alone does not cancel a response still being generated', async ({ page }) => {
  await page.goto('/');
  const sent = await page.evaluate(() => {
    const messages = [];
    socket = { readyState: WebSocket.OPEN, send: value => messages.push(JSON.parse(value)) };
    playing = [];
    received({ type: 'speech_started' });
    return messages;
  });
  expect(sent).toEqual([]);
});

test('apply waits for editing acknowledgement and blocks concurrent edits and saves', async ({ page }) => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  await page.route('**/api/sessions/local-test/editing', async route => {
    await pending;
    await route.fulfill({ json: { editing: true } });
  });
  let applied = false;
  await page.route('**/api/sessions/local-test/draft', async route => {
    const body = route.request().postDataJSON();
    expect(body.version).toBe(1);
    applied = true;
    await route.fulfill({ json: { summary: body.summary, version: 2, frozen: false } });
  });
  await openReview(page);
  await page.locator('#stance').fill('Pilot bevorzugt');
  await expect(page.locator('#save')).toBeDisabled();
  await page.locator('#update-draft').click();
  await expect(page.locator('#stance')).toBeDisabled();
  expect(applied).toBe(false);
  release();
  await expect(page.locator('#summary-state')).toHaveText('Entwurf 2 zur Pruefung');
  await expect(page.locator('#save')).toBeEnabled();
  await expect(page.locator('#stance')).toHaveValue('Pilot bevorzugt');
});

test('failed upload keeps frozen fields and retry uses the reviewed version', async ({ page }) => {
  let attempts = 0;
  await page.route('**/api/sessions/local-test/save', async route => {
    expect(route.request().postDataJSON()).toEqual({ version: 1 });
    attempts++;
    await route.fulfill(attempts === 1
      ? { status: 503, json: { detail: 'Upload fehlgeschlagen' } }
      : { json: { filename: 'meinung.docx', version: 1, url: 'https://demo.sharepoint.com/meinung.docx' } });
  });
  await page.route('**/api/sessions/local-test/draft', route => route.fulfill({
    json: { summary, version: 1, frozen: true, phase: 'review', result: null },
  }));
  await openReview(page);
  await page.locator('#save').click();
  await expect(page.getByRole('status')).toHaveText('Upload fehlgeschlagen');
  await expect(page.locator('#stance')).toBeDisabled();
  await expect(page.locator('#update-draft')).toBeDisabled();
  await expect(page.locator('#save')).toBeEnabled();
  await expect(page.locator('#download')).toBeHidden();
  await page.locator('#save').click();
  await expect(page.getByRole('status')).toHaveText('Word-Dokument in SharePoint gespeichert.');
  await expect(page.locator('#save')).toBeDisabled();
  await expect(page.locator('#download')).toBeVisible();
  expect(attempts).toBe(2);
});
