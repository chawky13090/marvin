import assert from 'node:assert/strict';
import { BackendReadUnavailable, fetchBackendRead } from '../lib/backendRead.mjs';

let calls = 0;
const recovered = await fetchBackendRead('http://backend.test/health', {
  fetchImpl: async () => {
    calls += 1;
    if (calls < 3) throw new Error('socket perdue');
    return new Response('{}', { status: 200 });
  },
  sleep: async () => {},
});
assert.equal(recovered.status, 200);
assert.equal(calls, 3);

calls = 0;
const domainError = await fetchBackendRead('http://backend.test/missing', {
  fetchImpl: async () => {
    calls += 1;
    return new Response('{}', { status: 404 });
  },
  sleep: async () => {},
});
assert.equal(domainError.status, 404);
assert.equal(calls, 1, 'une erreur métier 4xx ne doit jamais être rejouée');

await assert.rejects(
  fetchBackendRead('http://backend.test/down', {
    attempts: 2,
    fetchImpl: async () => { throw new Error('secret interne'); },
    sleep: async () => {},
  }),
  error => error instanceof BackendReadUnavailable && !error.message.includes('secret'),
);

console.log('Backend Read OK - retries bornés, 4xx non rejoués et erreur expurgée.');
