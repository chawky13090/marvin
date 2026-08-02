import assert from 'node:assert/strict';
import fs from 'node:fs';

const paths = [
  '../app/emails/page.jsx',
  '../components/email/EmailSetupPanel.jsx',
  '../components/email/emailStyles.js',
];
const source = paths
  .map((path) => new URL(path, import.meta.url))
  .filter((path) => fs.existsSync(path))
  .map((path) => fs.readFileSync(path, 'utf8'))
  .join('\n');

for (const contract of [
  /\/api\/email\/providers/,
  /\/api\/email\/test/,
  /\/api\/email\/accounts/,
  /\/api\/email\/oauth\/google\/start/,
  /type=\{opts\.pw \? ['"]password['"]/,
  /\/api\/email\/inbox/,
  /\/api\/email\/search/,
  /\/api\/email\/read\//,
  /\/api\/email\/mark/,
  /\/api\/email\/move/,
  /\/api\/email\/send/,
  /\/api\/email\/automation/,
  /\/api\/email\/watch/,
]) {
  assert.match(source, contract);
}

assert.match(source, /function SetupPanel|export function SetupPanel/);
assert.match(source, /<SetupPanel/);
assert.match(source, /account_hint=\$\{encodeURIComponent\(form\.username \|\| ['"]['"]\)\}/);
assert.match(source, /Vous pouvez connecter plusieurs boîtes/);
console.log('Email workspace characterization OK - multi-account setup, inbox, compose, automation and watch contracts covered.');
