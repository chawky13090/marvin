import { MutationOutcomeUnknownError } from './backendFallback.mjs';

const AMBIGUOUS_STATUSES = new Set([502, 503, 504]);

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
    if (error?.code === 'MUTATION_OUTCOME_UNKNOWN') throw error;
    if (error instanceof TypeError || error?.name === 'AbortError' || error?.name === 'TimeoutError') {
      throw new MutationOutcomeUnknownError('/api/settings', 'POST', error);
    }
    throw error;
  }
}
