import { conversationListFromPayload } from './conversationPayload.mjs';

function failed(reason) {
  return {
    ok: false,
    reason: reason instanceof Error ? reason.name : 'Unavailable',
  };
}

async function readConversations(fetcher, timestamp) {
  try {
    const response = await fetcher(`/api/conversations?t=${timestamp}`);
    if (!response?.ok) return failed(new Error(`ConversationHTTP${response?.status || 0}`));
    const payload = await response.json();
    const valid = Array.isArray(payload) || Array.isArray(payload?.conversations);
    if (!valid) return failed(new TypeError('InvalidConversationPayload'));
    return { ok: true, value: conversationListFromPayload(payload) };
  } catch (error) {
    return failed(error);
  }
}

async function readProjects(fetcher, timestamp) {
  try {
    const response = await fetcher(`/api/projects?t=${timestamp}`);
    if (!response?.ok) return failed(new Error(`ProjectHTTP${response?.status || 0}`));
    const payload = await response.json();
    if (!Array.isArray(payload)) return failed(new TypeError('InvalidProjectPayload'));
    return { ok: true, value: payload };
  } catch (error) {
    return failed(error);
  }
}

export async function fetchWorkspaceSnapshot(fetcher, timestamp = Date.now()) {
  if (typeof fetcher !== 'function') {
    throw new TypeError('fetcher doit être une fonction');
  }
  const [conversations, projects] = await Promise.all([
    readConversations(fetcher, timestamp),
    readProjects(fetcher, timestamp),
  ]);
  return { conversations, projects };
}
