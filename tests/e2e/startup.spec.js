import { test as base, expect } from '@playwright/test';

const test = base.extend({
  diagnostics: [async ({ page }, use, testInfo) => {
    const messages = [];
    const exceptions = [];
    page.on('console', message => messages.push(`console ${message.type()}: ${message.text()}`));
    page.on('pageerror', error => {
      exceptions.push(error.message);
      messages.push(`pageerror: ${error.message}`);
    });
    page.on('requestfailed', request => messages.push(
      `requestfailed: ${request.method()} ${request.url()} ${request.failure()?.errorText}`,
    ));
    page.on('response', response => {
      if (response.status() >= 400) messages.push(`http ${response.status()}: ${response.url()}`);
    });
    await use();
    await testInfo.attach('browser.log', {
      body: messages.join('\n'), contentType: 'text/plain',
    });
    expect(exceptions, 'Uncaught browser exceptions').toEqual([]);
  }, { auto: true }],
});

test('startup stays unavailable without cloud integrations', async ({ page, request }, testInfo) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Eine eigene Position.', exact: true })).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('Noch nicht verbunden');
  await expect(page.getByRole('button', { name: 'Sitzung starten' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Gepruefte Zusammenfassung speichern' })).toBeDisabled();
  const response = await page.evaluate(async () => {
    const result = await fetch('/api/sessions', {
      method: 'POST', headers: { 'X-Local-Client': '1', 'Content-Type': 'application/json' },
      body: '{}',
    });
    return { status: result.status, data: await result.json() };
  });
  expect(response.status).toBe(503);
  expect(response.data.detail).toContain('SharePoint-Verbindung erforderlich');
  expect((await request.get('/.env')).status()).toBe(404);
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits, 'No horizontal overflow').toBe(true);
  await page.screenshot({ path: testInfo.outputPath('startup.png'), fullPage: true });
});

test('readiness network failure is visible and retry recovers', async ({ page }) => {
  await page.route('**/api/readiness', route => route.abort('failed'));
  await page.goto('/');
  await expect(page.getByRole('status')).toHaveText('Verbindung fehlgeschlagen');
  await expect(page.getByRole('button', { name: 'Sitzung starten' })).toBeDisabled();
  await page.unroute('**/api/readiness');
  await page.getByRole('button', { name: 'Erneut pruefen' }).click();
  await expect(page.getByRole('status')).toHaveText('Noch nicht verbunden');
  await expect(page.getByRole('button', { name: 'Sitzung starten' })).toBeDisabled();
});