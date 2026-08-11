const READ_FALLBACK_STATUSES = new Set([404, 500, 502, 503, 504]);
const AMBIGUOUS_MUTATION_STATUSES = new Set([502, 503, 504]);

function normalizedMethod(options) {
  return String(options?.method || 'GET').toUpperCase();
}

function isSafeRead(options) {
  const method = normalizedMethod(options);
  return method === 'GET' || method === 'HEAD';
}

export class MutationOutcomeUnknownError extends Error {
  constructor(path, method, cause) {
    super(`Resultat non confirme pour ${method} ${path}`, { cause });
    this.name = 'MutationOutcomeUnknownError';
    this.code = 'MUTATION_OUTCOME_UNKNOWN';
    this.path = path;
    this.method = method;
  }
}

export function isMutationOutcomeUnknown(error) {
  return error instanceof MutationOutcomeUnknownError
    || error?.code === 'MUTATION_OUTCOME_UNKNOWN';
}

export function shouldFallbackToBackend(status, options) {
  return isSafeRead(options) && READ_FALLBACK_STATUSES.has(status);
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

  if (!isSafeRead(options)) {
    const method = normalizedMethod(options);
    try {
      const response = await fetchImpl(`${backendUrl}${path}`, withTimeout(backendTimeoutMs));
      if (AMBIGUOUS_MUTATION_STATUSES.has(response.status)) {
        throw new MutationOutcomeUnknownError(path, method, response);
      }
      return response;
    } catch (error) {
      if (isMutationOutcomeUnknown(error)) throw error;
      throw new MutationOutcomeUnknownError(path, method, error);
    }
  }

  try {
    const localResponse = await fetchImpl(path, withTimeout(localTimeoutMs));
    if (localResponse.ok || !shouldFallbackToBackend(localResponse.status, options)) {
      return localResponse;
    }
  } catch {
    // Une lecture peut etre repetee sans modifier l'etat metier.
  }
  return fetchImpl(`${backendUrl}${path}`, withTimeout(backendTimeoutMs));
}
