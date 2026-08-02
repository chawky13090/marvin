import assert from 'node:assert/strict';
import fs from 'node:fs';

const paths = [
  '../app/devis/page.jsx',
  '../components/devis/DevisOperationsViews.jsx',
  '../components/devis/devisShared.js',
];
const source = paths
  .map((path) => new URL(path, import.meta.url))
  .filter((path) => fs.existsSync(path))
  .map((path) => fs.readFileSync(path, 'utf8'))
  .join('\n');

for (const contract of [
  /\/api\/billing\/clients/,
  /\/api\/billing\/quotes/,
  /\/api\/billing\/catalog/,
  /toolName:\s*name/,
  /billing_market_research/,
  /billing_find_products/,
  /it_kb_list/,
  /it_kb_search/,
  /it_kb_recommend/,
  /billing_invoice_list/,
  /billing_revenue_dashboard/,
  /billing_invoice_create/,
  /billing_invoice_mark_paid/,
  /view === ['"]invoices['"]/,
  /view === ['"]kb['"]/,
]) {
  assert.match(source, contract);
}

assert.match(source, /function KbView|export function KbView/);
assert.match(source, /function InvoicesView|export function InvoicesView/);
assert.match(source, /acceptedQuotes\s*=\s*quotes\.filter\(q => q\.status === ['"]accepted['"]\)/);
assert.match(source, /i\.status !== ['"]paid['"] && i\.status !== ['"]cancelled['"]/);
console.log('Devis characterization OK - data loading, market research, knowledge base and invoice workflows covered.');
