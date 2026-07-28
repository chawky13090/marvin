export const LAST_CONVERSATION_STORAGE_KEY = 'marvin:last-conversation-id';

export function normalizeConversationId(value) {
  const conversationId = String(value || '').trim();
  if (!conversationId || conversationId.length > 128) return null;
  return /^[a-zA-Z0-9_-]+$/.test(conversationId) ? conversationId : null;
}

export function readLastConversationId(storage) {
  try {
    return normalizeConversationId(storage?.getItem(LAST_CONVERSATION_STORAGE_KEY));
  } catch {
    return null;
  }
}

export function persistLastConversationId(storage, conversationId) {
  try {
    const normalized = normalizeConversationId(conversationId);
    if (normalized) storage?.setItem(LAST_CONVERSATION_STORAGE_KEY, normalized);
    else storage?.removeItem(LAST_CONVERSATION_STORAGE_KEY);
    return normalized;
  } catch {
    return null;
  }
}

export function initialChatSelection(chatStatus = {}) {
  const conversationId = normalizeConversationId(chatStatus.conversationId);
  return {
    conversationId,
    chatKey: conversationId || 'new',
  };
}

export function isLiveConversation({
  isLoading = false,
  liveConversationId = null,
  targetConversationId = null,
  liveMessageCount = 0,
} = {}) {
  if (!isLoading || Number(liveMessageCount) <= 0) return false;
  const liveId = String(liveConversationId || '').trim();
  const targetId = String(targetConversationId || '').trim();
  return !targetId || !liveId || targetId === liveId;
}

export function canSwitchConversation({
  isLoading = false,
  liveConversationId = null,
  targetConversationId = null,
} = {}) {
  if (!isLoading) return true;
  const liveId = String(liveConversationId || '').trim();
  const targetId = String(targetConversationId || '').trim();
  return Boolean(targetId && liveId && targetId === liveId);
}
