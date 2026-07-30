export function conversationListFromPayload(payload) {
  if (Array.isArray(payload)) return payload;
  if (payload && Array.isArray(payload.conversations)) {
    return payload.conversations;
  }
  return [];
}
