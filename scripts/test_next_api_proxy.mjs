import assert from 'node:assert/strict';
import fs from 'node:fs';
import { decideLanProxy } from '../lib/lanProxyPolicy.mjs';

const proxySource = fs.readFileSync(new URL('../proxy.js', import.meta.url), 'utf8');

assert.equal(decideLanProxy({ authenticated: true, authorized: true }), 'allow');
assert.equal(decideLanProxy({ authenticated: true, authorized: false }), 'forbid');
assert.equal(decideLanProxy({ authenticated: false, authorized: false }), 'authenticate');
assert.equal(decideLanProxy(null), 'authenticate');
assert.match(proxySource, /detail:\s*['"]lan_introspection_unavailable['"]/);
assert.match(proxySource, /status:\s*503/);
assert.match(proxySource, /['"]Retry-After['"]:\s*['"]1['"]/);
assert.match(proxySource, /if \(!response\.ok\)/);
assert.match(proxySource, /detail:\s*['"]lan_authentication_required['"]/);
assert.match(proxySource, /status:\s*401/);
assert.match(proxySource, /detail:\s*['"]capability_required['"]/);
assert.match(proxySource, /status:\s*403/);

console.log('Next API proxy OK - 401, 403 and backend 503 are distinguished fail-closed.');
