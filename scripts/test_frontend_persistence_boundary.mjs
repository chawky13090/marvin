/** Contrat : Next.js ne possède plus le schéma ni la connexion SQLite de Marvin. */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';


const root = path.resolve(import.meta.dirname, '..');
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8');

for (const relative of ['lib/database/init.js', 'lib/database/queries.js']) {
  assert.equal(fs.existsSync(path.join(root, relative)), false, `${relative} doit être absent`);
}

const packageJson = JSON.parse(read('package.json'));
assert.equal(packageJson.dependencies?.['better-sqlite3'], undefined);
assert.equal(packageJson.overrides?.sharp, '0.35.3');
assert.equal(packageJson.dependencies?.next, '16.2.12');

for (const relative of [
  'next.config.mjs',
  'scripts/check_runtime.mjs',
  'start.bat',
  'INSTALLER-NOUVEAU-PC.bat',
]) {
  assert.ok(!read(relative).includes('better-sqlite3'), `${relative} référence encore SQLite Node`);
}

const settingsRoute = read('app/api/settings/route.js');
const statusRoute = read('app/api/status/route.js');
const ollama = read('lib/ollama.js');
const boundary = read('lib/backendSettings.js');

assert.ok(settingsRoute.includes("setBackendSetting('active_model', modelName)"));
assert.ok(settingsRoute.includes("getBackendSetting('active_model', null)"));
assert.ok(settingsRoute.includes("component: 'next.settings'"));
assert.ok(settingsRoute.includes('error_type:'));
assert.ok(!settingsRoute.includes('error.message'));
assert.ok(statusRoute.includes("getBackendSetting('active_model', null)"));
assert.ok(ollama.includes('getActiveModel(selectedModel = null)'));
assert.ok(!ollama.includes('database/queries'));
assert.ok(boundary.includes('/api/settings/'));
assert.ok(boundary.includes('AbortSignal.timeout(5000)'));
assert.ok(boundary.includes('SETTING_KEY'));

console.log('Frontend Persistence Boundary OK - FastAPI propriétaire unique, dépendance native retirée.');
