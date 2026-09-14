import { test, expect } from '@playwright/test';

for (const viewport of [{ width: 1365, height: 950 }, { width: 390, height: 844 }]) {
  test(`compact conversation stays together at ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await expect(page.locator('#transcript')).toBeVisible();
    const measure = () => page.evaluate(() => {
      const box = selector => {
        const { top, bottom, left, right } = document.querySelector(selector).getBoundingClientRect();
        return { top, bottom, left, right };
      };
      return {
        connection: box('.connection-panel'), avatar: box('.avatar-column'),
        chat: box('.chat-column'), transcript: box('#transcript'), composer: box('#composer'),
        stage: box('.conversation-stage'), overflow: document.documentElement.scrollWidth > innerWidth,
        scrollY,
      };
    });
    const before = await measure();
    expect(before.overflow).toBe(false);
    expect(before.connection.bottom).toBeLessThanOrEqual(before.avatar.top);
    expect(before.composer.top - before.transcript.bottom).toBeLessThanOrEqual(2);
    if (viewport.width > 600) {
      expect(Math.abs(before.avatar.top - before.chat.top)).toBeLessThanOrEqual(1);
      expect(before.chat.left - before.avatar.right).toBeLessThanOrEqual(2);
      expect(before.composer.bottom).toBeLessThan(viewport.height);
    } else {
      expect(before.chat.top - before.avatar.bottom).toBeLessThanOrEqual(2);
      expect(before.composer.bottom).toBeLessThanOrEqual(viewport.height);
    }
    await page.evaluate(() => {
      for (let i = 0; i < 35; i++) transcript('user', `Beitrag ${i}: ${'Gedanken abwaegen. '.repeat(8)}`);
      received({ type: 'assistant_start', item_id: 'long-answer' });
      received({ type: 'assistant_delta', item_id: 'long-answer', text: 'Antwort. '.repeat(150) });
    });
    const after = await measure();
    expect(after.stage).toEqual(before.stage);
    expect(after.composer).toEqual(before.composer);
    expect(after.scrollY).toBe(before.scrollY);
    expect(after.overflow).toBe(false);
    expect(await page.locator('#transcript').evaluate(list =>
      list.scrollHeight > list.clientHeight && list.scrollHeight - list.scrollTop - list.clientHeight < 2,
    )).toBe(true);
    await page.locator('#transcript').evaluate(list => { list.scrollTop = 0; });
    await page.evaluate(() => received({ type: 'assistant_delta', item_id: 'long-answer', text: 'Weiter. '.repeat(30) }));
    expect(await page.locator('#transcript').evaluate(list => list.scrollTop)).toBe(0);
    await page.screenshot({ path: testInfo.outputPath(`conversation-${viewport.width}.png`), fullPage: true });
  });
}

test('microphone icon has explicit state and keyboard mute without automatic capture', async ({ page }) => {
  await page.addInitScript(() => {
    window.captureCalls = 0;
    navigator.mediaDevices.getUserMedia = async () => { window.captureCalls++; throw new Error('No capture in test'); };
  });
  await page.goto('/');
  const mic = page.locator('#microphone');
  await expect(mic).toHaveAttribute('aria-label', 'Mikrofon einschalten');
  await expect(mic).toHaveAttribute('title', 'Mikrofon einschalten');
  await page.evaluate(() => {
    socket = { readyState: WebSocket.OPEN, send() {} };
    received({ type: 'connected' });
  });
  expect(await page.evaluate(() => window.captureCalls)).toBe(0);
  await expect(mic).toHaveAttribute('aria-pressed', 'false');
  await page.evaluate(() => { microphoneOn = true; audioControls(); });
  await expect(mic).toHaveAttribute('aria-label', 'Mikrofon stummschalten');
  await expect(mic).toHaveAttribute('title', 'Mikrofon stummschalten');
  await expect(mic.locator('.mic-slash')).toBeHidden();
  await mic.focus();
  await page.keyboard.press('Space');
  await expect(mic).toHaveAttribute('aria-pressed', 'false');
  await expect(mic.locator('.mic-slash')).toBeVisible();
  await expect(mic).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('status')).toHaveText('No capture in test');
  expect(await page.evaluate(() => window.captureCalls)).toBe(1);
  await expect(mic.locator('svg')).toHaveCount(1);
});
