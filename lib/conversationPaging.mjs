export function mergeOlderConversationMessages(older, current) {
  const known = new Set((current || []).map(message => message?.id).filter(Boolean));
  return [
    ...(older || []).filter(message => !message?.id || !known.has(message.id)),
    ...(current || []),
  ];
}

export function conversationPageIsCurrent({
  requestSequence,
  latestSequence,
  requestedConversationId,
  activeConversationId,
}) {
  return requestSequence === latestSequence
    && requestedConversationId === activeConversationId;
}

export function preservePrependScrollTop({ scrollTop, scrollHeight, nextScrollHeight }) {
  return Math.max(0, Number(scrollTop || 0) + Number(nextScrollHeight || 0) - Number(scrollHeight || 0));
}
