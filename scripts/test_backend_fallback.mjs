import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  fetchWithBackendFallback,
  isMutationOutcomeUnknown,
  shouldFallbackToBackend,
} from '../lib/backendFallback.mjs';
import { postChatSetting } from '../lib/chatSettingsMutations.mjs';

assert.equal(shouldFallbackToBackend(500), true, 'un GET doit contourner un 500 Next transitoire');
assert.equal(shouldFallbackToBackend(500, { method: 'HEAD' }), true);
assert.equal(shouldFallbackToBackend(500, { method: 'PUT' }), false, 'une mutation ne doit pas etre rejouee sur HTTP 500');
assert.equal(shouldFallbackToBackend(504, { method: 'POST' }), false, 'une mutation ne doit pas etre rejouee sur HTTP 504');
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

const ambiguousStatuses = [502, 503, 504];
for (const status of ambiguousStatuses) {
  const urls = [];
  await assert.rejects(
    fetchWithBackendFallback(
      '/api/conversations/id/exports',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"format":"pdf"}' },
      {
        backendUrl: 'http://127.0.0.1:8005',
        fetchImpl: async (url) => {
          urls.push(String(url));
          return new Response('{"error":"gateway"}', { status });
        },
      },
    ),
    (error) => isMutationOutcomeUnknown(error) && error.method === 'POST',
  );
  assert.deepEqual(urls, ['http://127.0.0.1:8005/api/conversations/id/exports']);
}

const timeoutCalls = [];
await assert.rejects(
  fetchWithBackendFallback(
    '/api/projects/id',
    { method: 'PUT', body: '{}' },
    {
      backendUrl: 'http://127.0.0.1:8005',
      fetchImpl: async (url) => {
        timeoutCalls.push(String(url));
        throw new DOMException('delai depasse', 'TimeoutError');
      },
    },
  ),
  (error) => isMutationOutcomeUnknown(error) && error.path === '/api/projects/id',
);
assert.deepEqual(timeoutCalls, ['http://127.0.0.1:8005/api/projects/id']);

for (const status of [409, 422]) {
  let receiptCalls = 0;
  const receiptResponse = await fetchWithBackendFallback(
    '/api/events',
    {
      method: 'POST',
      headers: { 'Idempotency-Key': '00000000-0000-4000-8000-000000000001' },
      body: '{}',
    },
    {
      backendUrl: 'http://127.0.0.1:8005',
      fetchImpl: async (_url, init) => {
        receiptCalls += 1;
        assert.equal(new Headers(init.headers).get('Idempotency-Key'), '00000000-0000-4000-8000-000000000001');
        return new Response('{"detail":"receipt"}', { status });
      },
    },
  );
  assert.equal(receiptResponse.status, status);
  assert.equal(receiptCalls, 1, `HTTP ${status} doit rester un resultat serveur sans rejeu`);
}

const readCalls = [];
const readAfterNetworkFailure = await fetchWithBackendFallback(
  '/api/conversations/read-id',
  undefined,
  {
    backendUrl: 'http://127.0.0.1:8005',
    fetchImpl: async (url) => {
      readCalls.push(String(url));
      if (readCalls.length === 1) throw new TypeError('Failed to fetch');
      return new Response('{"messages":[]}', { status: 200 });
    },
  },
);
assert.equal(readAfterNetworkFailure.status, 200);
assert.deepEqual(readCalls, [
  '/api/conversations/read-id',
  'http://127.0.0.1:8005/api/conversations/read-id',
]);

const settingCalls = [];
const settingResponse = await postChatSetting('set_model', 'qwen3:4b', {
  fetchImpl: async (url, init) => {
    settingCalls.push({ url: String(url), init });
    return new Response('{"success":true}', { status: 200 });
  },
});
assert.equal(settingResponse.status, 200);
assert.equal(settingCalls.length, 1);
assert.equal(settingCalls[0].url, '/api/settings');
assert.deepEqual(JSON.parse(settingCalls[0].init.body), { action: 'set_model', modelName: 'qwen3:4b' });

const verifiedSettingCalls = [];
const verifiedSetting = await postChatSetting('set_model', 'glm-5.2:cloud', {
  fetchImpl: async (url, init) => {
    verifiedSettingCalls.push({ url: String(url), method: init?.method });
    if (verifiedSettingCalls.length === 1) {
      return new Response('{"error":"temporarily unavailable"}', { status: 503 });
    }
    return new Response('{"ollama":{"selectedModel":"glm-5.2:cloud"}}', { status: 200 });
  },
});
assert.equal(verifiedSetting.status, 200);
assert.deepEqual(verifiedSettingCalls, [
  { url: '/api/settings', method: 'POST' },
  { url: '/api/status', method: 'GET' },
]);

let unverifiedSettingCalls = 0;
await assert.rejects(
  postChatSetting('set_model', 'glm-5.2:cloud', {
    fetchImpl: async () => {
      unverifiedSettingCalls += 1;
      if (unverifiedSettingCalls === 1) {
        return new Response('{"error":"temporarily unavailable"}', { status: 503 });
      }
      return new Response('{"ollama":{"selectedModel":"qwen3:4b"}}', { status: 200 });
    },
  }),
  isMutationOutcomeUnknown,
);
assert.equal(unverifiedSettingCalls, 2, 'une ambiguïté ne permet qu’une lecture de vérification, jamais un second POST');

for (const status of [502, 503, 504]) {
  let callsForStatus = 0;
  await assert.rejects(
    postChatSetting('pull_model', 'qwen3:4b', {
      fetchImpl: async () => {
        callsForStatus += 1;
        return new Response('{"error":"unknown"}', { status });
      },
    }),
    isMutationOutcomeUnknown,
  );
  assert.equal(callsForStatus, 1, `le réglage HTTP ${status} ne doit pas être rejoué`);
}

let failedSettingCalls = 0;
await assert.rejects(
  postChatSetting('set_model', 'invalid', {
    fetchImpl: async () => {
      failedSettingCalls += 1;
      return new Response('{"error":"invalid"}', { status: 400 });
    },
  }),
  (error) => !isMutationOutcomeUnknown(error) && /HTTP 400/.test(error.message),
);
assert.equal(failedSettingCalls, 1);

let disconnectedSettingCalls = 0;
await assert.rejects(
  postChatSetting('pull_model', 'qwen3:4b', {
    fetchImpl: async () => {
      disconnectedSettingCalls += 1;
      throw new TypeError('Failed to fetch');
    },
  }),
  isMutationOutcomeUnknown,
);
assert.equal(disconnectedSettingCalls, 1);

const chatPageSource = readFileSync(new URL('../app/page.js', import.meta.url), 'utf8');
const toastSource = readFileSync(new URL('../components/ui/Toast.jsx', import.meta.url), 'utf8');
const mutationUiSource = readFileSync(new URL('../lib/mutationOutcomeUi.mjs', import.meta.url), 'utf8');
assert.match(chatPageSource, /reportMutationFailure/);
assert.doesNotMatch(chatPageSource, /fetch\('\/api\/projects'/);
assert.doesNotMatch(chatPageSource, /fetch\('\/api\/settings'/);
assert.match(chatPageSource, /postChatSetting\('set_model'/);
assert.match(chatPageSource, /postChatSetting\('pull_model'/);
assert.ok(
  chatPageSource.indexOf("postChatSetting('set_model'") < chatPageSource.indexOf('setActiveModel(modelName)', chatPageSource.indexOf("postChatSetting('set_model'")),
  'le modele visible ne doit changer qu apres confirmation du serveur',
);
assert.match(chatPageSource, /window\.location\.assign\('\/documents'\)/);
assert.match(mutationUiSource, /Résultat non confirmé/);
assert.match(mutationUiSource, /Marvin ne l’a pas relancée automatiquement/);
assert.match(mutationUiSource, /actionLabel: onVerify/);
assert.match(toastSource, /toast\.actionLabel && toast\.onAction/);
assert.match(toastSource, /toast\.onAction\?\.\(\)/);

console.log('Backend fallback OK - lectures recuperables, mutations a transport unique.');
