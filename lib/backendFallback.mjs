const READ_FALLBACK_STATUSES = new Set([404, 500, 502, 503, 504]);
const MUTATION_FALLBACK_STATUSES = new Set([404, 502, 503, 504]);

function normalizedMethod(options) {
  return String(options?.method || 'GET').toUpperCase();
}

export function shouldFallbackToBackend(status, options) {
  const method = normalizedMethod(options);
  const safeRead = method === 'GET' || method === 'HEAD';
  return (safeRead ? READ_FALLBACK_STATUSES : MUTATION_FALLBACK_STATUSES).has(status);
}

export async function fetchWithBackendFallback(
  path,
  options,
  {
    backendUrl,
    fetchImpl = fetch,
    localTimeoutMs = 8000,
    backendTimeoutMs = 12000,
  } = {},
) {
  if (!backendUrl) throw new TypeError('URL backend requise');
  const withTimeout = (timeout) => ({
    ...(options || {}),
    signal: options?.signal || AbortSignal.timeout(timeout),
  });
  try {
    const localResponse = await fetchImpl(path, withTimeout(localTimeoutMs));
    if (localResponse.ok || !shouldFallbackToBackend(localResponse.status, options)) {
      return localResponse;
    }
  } catch {
    // Le repli direct reste borne. Les mutations conservent leur cle d'idempotence
    // lorsqu'elle est fournie par l'appelant ou par le pont fetch du navigateur.
  }
  return fetchImpl(`${backendUrl}${path}`, withTimeout(backendTimeoutMs));
}
