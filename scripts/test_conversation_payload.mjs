import assert from 'node:assert/strict';
import { conversationListFromPayload } from '../lib/conversationPayload.mjs';

const conversations = [{ id: 'conv-1', title: 'CrystalDiskInfo' }];
assert.deepEqual(conversationListFromPayload(conversations), conversations);
assert.deepEqual(
  conversationListFromPayload({ conversations }),
  conversations,
);
assert.deepEqual(conversationListFromPayload({ error: 'unavailable' }), []);
assert.deepEqual(conversationListFromPayload(null), []);

console.log('Conversation Payload OK - proxy et repli FastAPI compatibles.');
