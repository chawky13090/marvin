import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const pagePath = path.join(root, 'app', 'outils', 'page.jsx');
const componentPath = path.join(root, 'components', 'tools', 'ResultPanel.jsx');
const page = fs.readFileSync(pagePath, 'utf8');
const component = fs.existsSync(componentPath) ? fs.readFileSync(componentPath, 'utf8') : page;

assert.equal(
  [page, fs.existsSync(componentPath) ? component : '']
    .map((source) => (source.match(/function ResultPanel\s*\(/g) || []).length)
    .reduce((left, right) => left + right, 0),
  1,
  'ResultPanel doit avoir un propriétaire unique',
);
assert.match(page, /<ResultPanel\s+result=\{result\}/, 'la carte outil doit conserver son résultat');
assert.match(page, /error=\{error\}/, 'la carte outil doit conserver son erreur');
for (const marker of [
  'showJson', 'PrettyResult', 'open_ports', 'webResults', 'isImage', 'result.stdout',
  'result.stderr', 'result.devices', 'result.addresses', 'result.translated',
]) {
  assert.ok(component.includes(marker), `branche de rendu perdue: ${marker}`);
}
assert.match(component, /if \(error\)/, 'la branche erreur doit rester présente');
assert.match(component, /\{error\}/, 'le message d’erreur doit rester visible');
assert.match(component, /JSON/, 'le fallback JSON doit rester accessible');

console.log('Tools ResultPanel characterization OK - erreurs, fichiers, Web, image, shell et JSON couverts.');
