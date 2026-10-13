import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, copyFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';

const root = mkdtempSync(join(tmpdir(), 'marvin-next-production-'));
let child;
try {
  for (const path of ['scripts', '.next/dev/server', 'runtime/lifecycle', 'node_modules/next/dist/bin']) {
    mkdirSync(join(root, path), { recursive: true });
  }
  copyFileSync(resolve('scripts/start_next_dev.mjs'), join(root, 'scripts/start_next_dev.mjs'));
  writeFileSync(join(root, '.next/BUILD_ID'), 'test-build');
  writeFileSync(join(root, '.next/dev/server/preserve'), 'unchanged');
  writeFileSync(join(root, 'node_modules/next/dist/bin/next'), `
const fs = require('node:fs');
if (process.argv[2] !== 'start') process.exit(7);
fs.writeFileSync('child-ready', 'ready');
setInterval(() => {}, 1000);
process.on('SIGTERM', () => process.exit(0));
`);
  let output = '';
  child = spawn(process.execPath, [join(root, 'scripts/start_next_dev.mjs'), '--production'], {
    cwd: root, stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { output += chunk; });
  const exited = new Promise(resolveExit => child.once('exit', code => resolveExit(code)));
  const deadline = Date.now() + 10000;
  while (!existsSync(join(root, 'child-ready')) && child.exitCode === null && Date.now() < deadline) {
    await delay(50);
  }
  assert(existsSync(join(root, 'child-ready')), output);
  assert(existsSync(join(root, '.next/dev/server/preserve')), 'Production removed development cache');
  writeFileSync(join(root, 'runtime/lifecycle/frontend.shutdown'), 'stop');
  const code = await Promise.race([exited, delay(12000).then(() => { throw new Error('Shutdown timed out'); })]);
  assert.equal(code, 0, output);
  console.log('Next production lifecycle OK - start, cache preservation and bounded stop.');
} finally {
  if (child && child.exitCode === null) child.kill('SIGKILL');
  rmSync(root, { recursive: true, force: true });
}
