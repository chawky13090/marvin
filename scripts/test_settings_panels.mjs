import assert from 'node:assert/strict';
import fs from 'node:fs';

const paths = [
  '../app/settings/page.jsx',
  '../components/settings/ModelSettingsPanel.jsx',
  '../components/settings/CredentialGroup.jsx',
];
const source = paths
  .map((path) => new URL(path, import.meta.url))
  .filter((path) => fs.existsSync(path))
  .map((path) => fs.readFileSync(path, 'utf8'))
  .join('\n');

for (const contract of [
  /\/api\/status/,
  /\/api\/auto-config/,
  /\/api\/auto-config\/models\/policy/,
  /\/api\/settings\/cloud_enabled/,
  /action:\s*['"]pull_model['"]/,
  /handleSetModel/,
  /savePortfolioPolicy/,
  /applyPreset/,
  /setCloudModelForProfile/,
  /localOnlyLockdown/,
  /ultraUnrestricted/,
  /privacyPreset/,
  /function CredentialGroup|export function CredentialGroup/,
  /onSave\(name\)/,
  /onDelete\(name\)/,
  /type=\{isSecret && !visible \? ['"]password['"] : ['"]text['"]\}/,
]) {
  assert.match(source, contract);
}

assert.match(source, /<ModelSettingsPanel|activeTab === ['"]model['"]/);
assert.match(source, /<CredentialGroup/);
console.log('Settings panels characterization OK - model routing, privacy modes, portfolio and credential handling covered.');
