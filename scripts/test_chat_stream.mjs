import assert from 'node:assert/strict';
import { ChatStreamTransportError, durableChatEvents } from '../lib/chatStream.js';

const encoder = new TextEncoder();
const bodies = [];
const headers = [];
let calls = 0;
globalThis.fetch = async (_url, options) => {
  calls += 1;
  bodies.push(JSON.parse(options.body));
  headers.push(options.headers);
  if (calls === 1) {
    return new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"text","text":"A","turnSeq":1}\n\n'));
        setTimeout(() => controller.error(new Error('coupure simulée')), 0);
      },
    }), { status: 200 });
  }
  return new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('data: {"type":"text","text":"B","turnSeq":2}\n\n'));
      controller.enqueue(encoder.encode('data: {"type":"done","turnSeq":3}\n\n'));
      controller.close();
    },
  }), { status: 200 });
};

const events = [];
for await (const event of durableChatEvents({
  url: 'http://marvin.invalid/api/chat',
  payload: { requestId: 'request-1', messages: [] },
  reconnectDelayMs: 0,
})) events.push(event);

assert.equal(calls, 2);
assert.equal(bodies[0].afterEvent, 0);
assert.equal(bodies[1].afterEvent, 1);
assert.equal(headers[0]['X-Request-ID'], 'request-1');
assert.equal(headers[1]['X-Request-ID'], 'request-1');
assert.deepEqual(events.map(event => event.type), ['text', 'text', 'done']);
assert.equal(events.map(event => event.text || '').join(''), 'AB');

// Un redémarrage court du backend doit être absorbé sans rejouer logiquement la demande :
// le requestId reste identique et le curseur reprend après le dernier événement reçu.
calls = 0;
const restartBodies = [];
globalThis.fetch = async (_url, options) => {
  calls += 1;
  restartBodies.push(JSON.parse(options.body));
  if (calls <= 3) throw new TypeError('Failed to fetch');
  return new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('data: {"type":"done","turnSeq":1}\n\n'));
      controller.close();
    },
  }), { status: 200 });
};
const restarted = [];
for await (const event of durableChatEvents({
  url: 'http://marvin.invalid/api/chat',
  payload: { requestId: 'request-restart', messages: [] },
  reconnectDelayMs: 0,
})) restarted.push(event);
assert.equal(calls, 4);
assert.deepEqual(restartBodies.map(body => body.requestId), Array(4).fill('request-restart'));
assert.deepEqual(restarted.map(event => event.type), ['done']);

// Les erreurs client ne sont pas rejouées et une indisponibilité prolongée devient une
// erreur métier explicite après un nombre strictement borné de tentatives.
calls = 0;
globalThis.fetch = async () => {
  calls += 1;
  return new Response('', { status: 422 });
};
await assert.rejects(
  async () => {
    for await (const _event of durableChatEvents({
      url: 'http://marvin.invalid/api/chat', payload: { requestId: 'bad', messages: [] },
      reconnectDelayMs: 0,
    })) { /* aucun événement attendu */ }
  },
  error => error?.status === 422,
);
assert.equal(calls, 1);

calls = 0;
globalThis.fetch = async () => {
  calls += 1;
  throw new TypeError('Failed to fetch');
};
await assert.rejects(
  async () => {
    for await (const _event of durableChatEvents({
      url: 'http://marvin.invalid/api/chat', payload: { requestId: 'offline', messages: [] },
      maxReconnects: 2, reconnectDelayMs: 0,
    })) { /* aucun événement attendu */ }
  },
  error => error instanceof ChatStreamTransportError && error.attempts === 3,
);
assert.equal(calls, 3);

console.log('Chat Stream OK - reprise bornée, curseur stable et erreurs 4xx non rejouées.');
