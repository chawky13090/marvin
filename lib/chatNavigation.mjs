export function initialChatSelection(chatStatus = {}) {
  const conversationId = String(chatStatus.conversationId || '').trim() || null;
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
