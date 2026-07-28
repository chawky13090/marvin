import assert from 'node:assert/strict';
import {
  canSwitchConversation,
  initialChatSelection,
  isLiveConversation,
  normalizeConversationId,
  persistLastConversationId,
  readLastConversationId,
} from '../lib/chatNavigation.mjs';

assert.deepEqual(initialChatSelection({ conversationId: 'conv-live' }), {
  conversationId: 'conv-live', chatKey: 'conv-live',
});
assert.deepEqual(initialChatSelection({}), { conversationId: null, chatKey: 'new' });

assert.equal(normalizeConversationId(' conv_123-test '), 'conv_123-test');
assert.equal(normalizeConversationId('../conversation'), null);
assert.equal(normalizeConversationId('x'.repeat(129)), null);

const storage = new Map();
const storageAdapter = {
  getItem: (key) => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, value),
  removeItem: (key) => storage.delete(key),
};
assert.equal(persistLastConversationId(storageAdapter, 'conv-42'), 'conv-42');
assert.equal(readLastConversationId(storageAdapter), 'conv-42');
assert.equal(persistLastConversationId(storageAdapter, null), null);
assert.equal(readLastConversationId(storageAdapter), null);
assert.equal(readLastConversationId({ getItem: () => { throw new Error('storage blocked'); } }), null);
assert.equal(isLiveConversation({ isLoading: true, liveConversationId: 'conv-live', targetConversationId: 'conv-live', liveMessageCount: 4 }), true);
assert.equal(isLiveConversation({ isLoading: true, liveConversationId: null, targetConversationId: null, liveMessageCount: 2 }), true);
assert.equal(isLiveConversation({ isLoading: false, liveConversationId: 'conv-live', targetConversationId: 'conv-live', liveMessageCount: 4 }), false);
assert.equal(canSwitchConversation({ isLoading: true, liveConversationId: 'conv-live', targetConversationId: 'conv-other' }), false);
assert.equal(canSwitchConversation({ isLoading: true, liveConversationId: 'conv-live', targetConversationId: 'conv-live' }), true);
assert.equal(canSwitchConversation({ isLoading: false, targetConversationId: 'conv-other' }), true);

console.log('Chat navigation: 8 assertions réussies.');
