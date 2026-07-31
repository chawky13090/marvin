import assert from 'node:assert/strict';
import { fetchWorkspaceSnapshot } from '../lib/workspaceRefresh.mjs';

function response(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return payload; },
  };
}

const independent = await fetchWorkspaceSnapshot(async path => {
  if (path.startsWith('/api/conversations')) {
    return response(200, { conversations: [{ id: 'conv-1' }] });
  }
  throw new TypeError('Failed to fetch projects');
}, 123);
assert.equal(independent.conversations.ok, true);
assert.deepEqual(independent.conversations.value, [{ id: 'conv-1' }]);
assert.equal(independent.projects.ok, false);

const malformed = await fetchWorkspaceSnapshot(async path => (
  path.startsWith('/api/conversations')
    ? response(200, { error: 'temporary' })
    : response(200, [])
), 456);
assert.equal(malformed.conversations.ok, false);
assert.equal(malformed.projects.ok, true);

const empty = await fetchWorkspaceSnapshot(async path => (
  path.startsWith('/api/conversations')
    ? response(200, { conversations: [] })
    : response(200, [])
), 789);
assert.equal(empty.conversations.ok, true);
assert.deepEqual(empty.conversations.value, []);

console.log('Workspace refresh: 8 assertions réussies.');
