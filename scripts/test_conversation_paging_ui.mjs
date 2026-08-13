import fs from 'node:fs';
import assert from 'node:assert/strict';
import {
  conversationPageIsCurrent,
  mergeOlderConversationMessages,
  preservePrependScrollTop,
} from '../lib/conversationPaging.mjs';

assert.deepEqual(
  mergeOlderConversationMessages([{ id: '1' }, { id: '2' }], [{ id: '2' }, { id: '3' }]).map(item => item.id),
  ['1', '2', '3'],
);
assert.equal(conversationPageIsCurrent({ requestSequence: 2, latestSequence: 2, requestedConversationId: 'a', activeConversationId: 'a' }), true);
assert.equal(conversationPageIsCurrent({ requestSequence: 2, latestSequence: 3, requestedConversationId: 'a', activeConversationId: 'a' }), false);
assert.equal(conversationPageIsCurrent({ requestSequence: 2, latestSequence: 2, requestedConversationId: 'a', activeConversationId: 'b' }), false);
assert.equal(preservePrependScrollTop({ scrollTop: 120, scrollHeight: 800, nextScrollHeight: 1250 }), 570);

const bubble = fs.readFileSync(new URL('../components/chat/MessageBubble.jsx', import.meta.url), 'utf8');
assert.match(bubble, /Le résultat détaillé n’est plus disponible/);
assert.match(bubble, /response\.status === 404/);
assert.match(bubble, /Aucun nouvel essai n’a été lancé automatiquement/);
const container = fs.readFileSync(new URL('../components/chat/ChatContainer.jsx', import.meta.url), 'utf8');
assert.match(container, /Charger les messages précédents/);
assert.match(container, /preservePrependScrollTop/);

console.log('Conversation Paging UI OK - déduplication, course, ancre et détail 404.');
