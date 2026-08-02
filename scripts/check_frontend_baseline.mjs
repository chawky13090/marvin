import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { ESLint } from 'eslint';

const root = path.resolve(import.meta.dirname, '..');
const configPath = path.join(root, 'config', 'frontend-baseline.json');
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const sourceRoots = ['app', 'components', 'lib'];
const sourceExtensions = new Set(['.js', '.jsx']);

function walk(relativeDirectory) {
  const absolute = path.join(root, relativeDirectory);
  if (!fs.existsSync(absolute)) return [];
  return fs.readdirSync(absolute, { withFileTypes: true }).flatMap((entry) => {
    const child = path.posix.join(relativeDirectory.replaceAll('\\', '/'), entry.name);
    if (entry.isDirectory()) return walk(child);
    return sourceExtensions.has(path.extname(entry.name)) ? [child] : [];
  });
}

function countLines(relativePath) {
  const content = fs.readFileSync(path.join(root, relativePath), 'utf8');
  if (content === '') return 0;
  const lines = content.split(/\r?\n/);
  return lines.at(-1) === '' ? lines.length - 1 : lines.length;
}

const files = sourceRoots.flatMap(walk).sort();
const oversized = Object.fromEntries(
  files
    .map((file) => [file, countLines(file)])
    .filter(([, lines]) => lines > config.largeFileThreshold),
);

const failures = [];
for (const [file, lines] of Object.entries(oversized)) {
  const ceiling = config.legacyLargeFiles[file];
  if (ceiling === undefined) {
    failures.push(`${file}: nouveau fichier au-dessus de ${config.largeFileThreshold} lignes (${lines})`);
  } else if (lines > ceiling) {
    failures.push(`${file}: ${lines} lignes, plafond historique ${ceiling}`);
  }
}
for (const file of Object.keys(config.legacyLargeFiles)) {
  if (!(file in oversized) && fs.existsSync(path.join(root, file))) {
    const lines = countLines(file);
    if (lines > config.largeFileThreshold) {
      failures.push(`${file}: exception incohérente (${lines} lignes)`);
    }
  }
}

const eslint = new ESLint({ cwd: root });
const results = await eslint.lintFiles(sourceRoots);
const errors = results.reduce((sum, result) => sum + result.errorCount, 0);
const warnings = results.reduce((sum, result) => sum + result.warningCount, 0);
if (errors > 0) failures.push(`ESLint: ${errors} erreur(s)`);
if (warnings > config.warningBudget) {
  failures.push(`ESLint: ${warnings} avertissements, budget ${config.warningBudget}`);
}

if (failures.length > 0) {
  console.error('Frontend baseline ECHEC');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exitCode = 1;
} else {
  console.log(
    `Frontend baseline OK - ${files.length} sources, ${warnings}/${config.warningBudget} ` +
      `avertissements, ${Object.keys(oversized).length} exceptions historiques.`,
  );
}
