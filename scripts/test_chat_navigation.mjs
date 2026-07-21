import assert from 'node:assert/strict';
import {
  canSwitchConversation,
  initialChatSelection,
  isLiveConversation,
} from '../lib/chatNavigation.mjs';

assert.deepEqual(initialChatSelection({ conversationId: 'conv-live' }), {
  conversationId: 'conv-live', chatKey: 'conv-live',
});
assert.deepEqual(initialChatSelection({}), { conversationId: null, chatKey: 'new' });
assert.equal(isLiveConversation({ isLoading: true, liveConversationId: 'conv-live', targetConversationId: 'conv-live', liveMessageCount: 4 }), true);
assert.equal(isLiveConversation({ isLoading: true, liveConversationId: null, targetConversationId: null, liveMessageCount: 2 }), true);
assert.equal(isLiveConversation({ isLoading: false, liveConversationId: 'conv-live', targetConversationId: 'conv-live', liveMessageCount: 4 }), false);
assert.equal(canSwitchConversation({ isLoading: true, liveConversationId: 'conv-live', targetConversationId: 'conv-other' }), false);
assert.equal(canSwitchConversation({ isLoading: true, liveConversationId: 'conv-live', targetConversationId: 'conv-live' }), true);
assert.equal(canSwitchConversation({ isLoading: false, targetConversationId: 'conv-other' }), true);

console.log('Chat navigation: 8 assertions réussies.');
