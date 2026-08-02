import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..');
const catalogPath = path.join(root, 'lib', 'tools', 'catalog.js');

async function loadCatalog() {
  if (fs.existsSync(catalogPath)) {
    return import(`${pathToFileURL(catalogPath).href}?t=${Date.now()}`);
  }
  const page = fs.readFileSync(path.join(root, 'app', 'outils', 'page.jsx'), 'utf8');
  const start = page.indexOf('// Catalogue des outils');
  const end = page.indexOf('function buildArgs');
  assert.ok(start >= 0 && end > start, 'catalogue historique introuvable');
  const source = `${page.slice(start, end)}\nexport { CATEGORIES, schemaToParams, prettifyToolId, pickCategoryId, pickAutoIcon, applyOverride, SYNTHETIC_CATEGORIES, GROUPS, groupOf };`;
  return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
}

const catalog = await loadCatalog();
const categoryIds = catalog.CATEGORIES.map((category) => category.id);
const toolIds = catalog.CATEGORIES.flatMap((category) => category.tools.map((tool) => tool.id));

assert.equal(catalog.CATEGORIES.length, 17);
assert.equal(toolIds.length, 141);
assert.equal(new Set(categoryIds).size, categoryIds.length, 'catégories dupliquées');
assert.equal(new Set(toolIds).size, toolIds.length, 'outils curés dupliqués');
assert.deepEqual(categoryIds, [
  'infographie', 'documents', 'fichiers', 'web', 'pc', 'calendar', 'cloud', 'taches',
  'memoire', 'reseau', 'ocr', 'email', 'ssh', 'archives', 'voix', 'utilitaires', 'donnees',
]);
assert.equal(catalog.GROUPS.length, 4);
assert.equal(catalog.groupOf('ssh'), 'systeme');
assert.equal(catalog.groupOf('email'), 'organisation');
assert.equal(catalog.pickCategoryId('billing_invoice_create'), 'facturation');
assert.equal(catalog.pickCategoryId('unknown_action'), 'utilitaires');
assert.equal(catalog.prettifyToolId('file_create_pdf'), 'File create pdf');
assert.deepEqual(
  catalog.schemaToParams({
    type: 'object',
    required: ['count'],
    properties: {
      count: { type: 'integer', description: 'Nombre' },
      mode: { type: 'string', enum: ['safe', 'fast'] },
      tags: { type: 'array', items: { type: 'string' } },
    },
  }),
  [
    { name: 'count', label: 'Count', type: 'number', required: true, placeholder: 'Nombre' },
    {
      name: 'mode', label: 'Mode', type: 'select', required: false, placeholder: '',
      options: [{ value: 'safe', label: 'safe' }, { value: 'fast', label: 'fast' }],
    },
    { name: 'tags', label: 'Tags', type: 'tags', required: false, placeholder: '' },
  ],
);

console.log('Tools catalog characterization OK - 17 catégories, 141 outils curés, 4 groupes.');
