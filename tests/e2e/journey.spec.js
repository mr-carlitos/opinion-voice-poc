import { test, expect } from '@playwright/test';

test('offline text-to-review-to-save journey requires versioned approval and cleans up the session', async ({ page }) => {
  const requests = [];
  const messages = [];
  const summary = { topic: 'Pilot', haltung: 'Unentschieden', offene_fragen: [], gegenpositionen: [], sources: [] };
  await page.route('**/api/readiness', route => route.fulfill({ json: {
    ready: true, message: 'Synthetic services', can_sign_in: true,
    auth: { mode: 'application', status: 'signed_in' }, voice_delivery_mode: 'strict', avatar_available: false,
  } }));
  await page.route('**/api/sessions', route => {
    requests.push({ method: route.request().method(), body: route.request().postDataJSON() });
    return route.fulfill({ json: {
      session_id: 'browser-session', sources: [], limits: 'Synthetic limits',
    } });
  });
  await page.route('**/api/sessions/browser-session/**', route => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname.split('/').pop();
    const body = request.postDataJSON();
    requests.push({ endpoint, method: request.method(), body });
    if (endpoint === 'editing') return route.fulfill({ json: { editing: true } });
    if (endpoint === 'draft') return route.fulfill({ json: {
      summary: body.summary, version: 2, frozen: false,
    } });
    if (endpoint === 'save') return route.fulfill({ json: {
      filename: 'synthetic.docx', url: 'https://demo.sharepoint.com/synthetic.docx', version: 2,
    } });
    return route.fulfill({ status: 404, json: { detail: 'Unexpected test request' } });
  });
  let voiceSocket;
  await page.routeWebSocket('**/api/sessions/browser-session/voice', ws => {
    voiceSocket = ws;
    ws.send(JSON.stringify({ type: 'connected' }));
    ws.onMessage(raw => {
      const message = JSON.parse(raw);
      messages.push(message);
      if (message.type === 'text') {
        ws.send(JSON.stringify({ type: 'user', text: message.text }));
        ws.send(JSON.stringify({ type: 'assistant', item_id: 'answer', text: 'Welche Fragen bleiben?', sources: [] }));
      }
      if (message.type === 'finish') ws.send(JSON.stringify({ type: 'draft', summary, version: 1 }));
    });
  });
  await page.goto('/');
  await page.locator('#start').click();
  await expect(page.locator('#message')).toBeEnabled();
  expect(requests[0]).toEqual({ method: 'POST', body: { avatar_enabled: false } });
  await page.locator('#message').fill('   \n  ');
  await page.locator('#send').click();
  expect(messages).toEqual([]);
  await page.locator('#message').fill('  Meine Haltung: offen.\nKosten? 🚆  ');
  await page.locator('#send').click();
  await expect(page.locator('#message')).toHaveValue('');
  await expect(page.locator('#transcript .user')).toContainText('Meine Haltung: offen.');
  expect(messages).toEqual([{ type: 'text', text: 'Meine Haltung: offen.\nKosten? 🚆' }]);
  await expect(page.locator('#turn-count')).toHaveText('1 / 30 Beitraege');
  await page.locator('#finish').click();
  await expect(page.locator('#review')).toBeVisible();
  expect(requests.filter(request => request.endpoint === 'save')).toHaveLength(0);
  await page.locator('#stance').fill('Ich bevorzuge den Pilot.');
  await expect(page.locator('#save')).toBeDisabled();
  await page.locator('#update-draft').click();
  await expect(page.locator('#summary-state')).toHaveText('Entwurf 2 zur Pruefung');
  const update = requests.find(request => request.endpoint === 'draft');
  expect(update.body.version).toBe(1);
  expect(update.body.summary.haltung).toBe('Ich bevorzuge den Pilot.');
  expect(requests.filter(request => request.endpoint === 'save')).toHaveLength(0);
  await page.locator('#save').click();
  await expect(page.locator('#download')).toHaveAttribute('href', 'https://demo.sharepoint.com/synthetic.docx');
  expect(requests.filter(request => request.endpoint === 'save')).toEqual([
    { endpoint: 'save', method: 'POST', body: { version: 2 } },
  ]);
  voiceSocket.close();
  await expect(page.locator('#message')).toBeDisabled();
  await expect(page.locator('#microphone')).toBeDisabled();
  await expect(page.locator('#delete')).toBeEnabled();
  await expect(page.locator('#download')).toBeVisible();
  let deleted = false;
  await page.route('**/api/sessions/browser-session', route => {
    expect(route.request().method()).toBe('DELETE');
    deleted = true;
    return route.fulfill({ json: { deleted: true } });
  });
  await page.locator('#delete').click();
  await expect(page.locator('#review')).toBeHidden();
  expect(deleted).toBe(true);
});

test('failed session startup is visible and can be retried without capturing a microphone', async ({ page }) => {
  await page.route('**/api/readiness', route => route.fulfill({ json: {
    ready: true, message: 'Synthetic services', can_sign_in: true,
    auth: { status: 'signed_in' }, avatar_available: false,
  } }));
  let attempts = 0;
  await page.route('**/api/sessions', route => {
    attempts++;
    return route.fulfill({ status: 502, json: { message: 'Synthetic corpus unavailable' } });
  });
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new Error('Unexpected microphone capture'); };
  });
  await page.goto('/');
  for (let attempt = 1; attempt <= 2; attempt++) {
    await page.locator('#start').click();
    await expect(page.getByRole('status')).toHaveText('Synthetic corpus unavailable');
    await expect(page.locator('#start')).toBeEnabled();
    await expect(page.locator('#message')).toBeDisabled();
    expect(attempts).toBe(attempt);
  }
});
