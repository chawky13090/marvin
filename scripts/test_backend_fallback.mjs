import assert from 'node:assert/strict';
import {
  fetchWithBackendFallback,
  shouldFallbackToBackend,
} from '../lib/backendFallback.mjs';

assert.equal(shouldFallbackToBackend(500), true, 'un GET doit contourner un 500 Next transitoire');
assert.equal(shouldFallbackToBackend(500, { method: 'HEAD' }), true);
assert.equal(shouldFallbackToBackend(500, { method: 'PUT' }), false, 'une mutation ne doit pas etre rejouee sur HTTP 500');
assert.equal(shouldFallbackToBackend(401), false, 'une erreur d autorisation ne doit pas etre contournee');

const calls = [];
const recovered = await fetchWithBackendFallback(
  '/api/conversations/large-id?t=1',
  undefined,
  {
    backendUrl: 'http://127.0.0.1:8005',
    fetchImpl: async (url) => {
      calls.push(String(url));
      return calls.length === 1
        ? new Response('{"error":"proxy"}', { status: 500 })
        : new Response('{"messages":[{"content":"large"}]}', { status: 200 });
    },
  },
);
assert.equal(recovered.status, 200);
assert.deepEqual(calls, [
  '/api/conversations/large-id?t=1',
  'http://127.0.0.1:8005/api/conversations/large-id?t=1',
]);

let mutationCalls = 0;
const mutation = await fetchWithBackendFallback(
  '/api/conversations/id',
  { method: 'PUT', body: '{}' },
  {
    backendUrl: 'http://127.0.0.1:8005',
    fetchImpl: async () => {
      mutationCalls += 1;
      return new Response('{"error":"unknown outcome"}', { status: 500 });
    },
  },
);
assert.equal(mutation.status, 500);
assert.equal(mutationCalls, 1, 'une mutation en resultat inconnu ne doit jamais etre rejouee');

console.log('Backend fallback OK - lecture 500 recuperee et mutation non rejouee.');
