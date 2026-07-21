import { closeSync, constants, existsSync, openSync, rmSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const devRoot = join(projectRoot, '.next', 'dev');
const devLock = join(devRoot, 'lock');

function activeDevLock(lockPath) {
  if (!existsSync(lockPath)) return false;
  try {
    const descriptor = openSync(lockPath, constants.O_RDWR);
    closeSync(descriptor);
    return false;
  } catch (error) {
    if (['EBUSY', 'EACCES', 'EPERM'].includes(error?.code)) return true;
    throw error;
  }
}

if (activeDevLock(devLock)) {
  console.error('[BLOQUÉ] Un frontend Turbopack Marvin est déjà actif.');
  process.exit(2);
}

// Le cache de compilation reste conservé, mais le graphe de routes est reconstruit.
// Cela répare un arrêt pendant `next build` sans toucher au code ni aux données.
for (const relativePath of [
  'server',
  'build-manifest.json',
  'fallback-build-manifest.json',
  'prerender-manifest.json',
  'routes-manifest.json',
]) {
  rmSync(join(devRoot, relativePath), { recursive: true, force: true });
}

const nextCli = join(projectRoot, 'node_modules', 'next', 'dist', 'bin', 'next');
const result = spawnSync(process.execPath, [nextCli, 'dev', '-H', '0.0.0.0'], {
  cwd: projectRoot,
  env: process.env,
  stdio: 'inherit',
});

if (result.error) throw result.error;
process.exit(result.status ?? 1);
