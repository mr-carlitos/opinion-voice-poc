const status = document.querySelector('[role="status"]');
const detail = document.querySelector('#detail');
const retry = document.querySelector('#retry');

async function checkReadiness() {
  retry.disabled = true;
  status.textContent = 'Verbindung wird geprueft';
  try {
    const response = await fetch('/api/readiness', {
      cache: 'no-store',
      signal: AbortSignal.timeout(5000),
    });
    const result = await response.json();
    if (response.status !== 503 || result.code !== 'integrations_not_implemented') {
      throw new Error('Unexpected readiness response');
    }
    status.textContent = 'Noch nicht verbunden';
    detail.textContent = result.message;
  } catch {
    status.textContent = 'Verbindung fehlgeschlagen';
    detail.textContent = 'Der lokale Dienst ist nicht erreichbar.';
  } finally {
    retry.disabled = false;
  }
}

retry.addEventListener('click', checkReadiness);
checkReadiness();