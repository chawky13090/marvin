import { MutationOutcomeUnknownError } from './backendFallback.mjs';

const AMBIGUOUS_STATUSES = new Set([502, 503, 504]);

async function selectedModelMatches(modelName, fetchImpl) {
  try {
    const verification = await fetchImpl('/api/status', {
      method: 'GET',
      cache: 'no-store',
    });
    if (!verification.ok) return false;
    const payload = await verification.json();
    return payload?.ollama?.selectedModel === modelName;
  } catch {
    return false;
  }
}

export async function postChatSetting(action, modelName, { fetchImpl = fetch } = {}) {
  try {
    const response = await fetchImpl('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, modelName }),
    });
    if (AMBIGUOUS_STATUSES.has(response.status)) {
      throw new MutationOutcomeUnknownError('/api/settings', 'POST', response);
    }
    if (!response.ok) throw new Error(`Réglage HTTP ${response.status}`);
    return response;
  } catch (error) {
    const ambiguous = error?.code === 'MUTATION_OUTCOME_UNKNOWN'
      ? error
      : (error instanceof TypeError || error?.name === 'AbortError' || error?.name === 'TimeoutError')
        ? new MutationOutcomeUnknownError('/api/settings', 'POST', error)
        : null;
    if (ambiguous && action === 'set_model' && await selectedModelMatches(modelName, fetchImpl)) {
      return new Response(JSON.stringify({ success: true, verifiedAfterAmbiguousResponse: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (ambiguous) throw ambiguous;
    throw error;
  }
}
