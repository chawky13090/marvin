import assert from 'node:assert/strict';
import { durableChatEvents } from '../lib/chatStream.js';

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

console.log('Chat Stream OK - reconnexion au curseur sans fragment dupliqué.');
