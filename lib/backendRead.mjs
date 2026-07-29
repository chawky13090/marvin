export class BackendReadUnavailable extends Error {
  constructor() {
    super('Backend temporairement indisponible');
    this.name = 'BackendReadUnavailable';
  }
}

export async function fetchBackendRead(
  url,
  {
    attempts = 4,
    timeoutMs = 6000,
    retryDelayMs = 2000,
    fetchImpl = fetch,
    sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms)),
  } = {},
) {
  if (!Number.isInteger(attempts) || attempts < 1 || attempts > 4) {
    throw new TypeError('Nombre de tentatives backend invalide');
  }
  let lastResponse = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetchImpl(url, {
        signal: AbortSignal.timeout(timeoutMs),
        cache: 'no-store',
      });
      lastResponse = response;
      if (response.ok || response.status < 500) return response;
    } catch {
      lastResponse = null;
    }
    if (attempt < attempts) await sleep(retryDelayMs);
  }
  if (lastResponse) return lastResponse;
  throw new BackendReadUnavailable();
}
