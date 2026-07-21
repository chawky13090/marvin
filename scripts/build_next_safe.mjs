import { closeSync, constants, existsSync, openSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const devLock = join(projectRoot, '.next', 'dev', 'lock');

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
  console.error([
    '',
    '[BLOQUÉ] Le frontend Turbopack de Marvin est en cours d’exécution.',
    'Un build Next.js simultané peut corrompre le manifeste des routes dynamiques',
    'et rendre les historiques de conversations invisibles.',
    '',
    'Arrêtez d’abord Marvin, lancez le build, puis redémarrez-le.',
    '',
  ].join('\n'));
  process.exit(2);
}

const nextCli = join(projectRoot, 'node_modules', 'next', 'dist', 'bin', 'next');
const result = spawnSync(process.execPath, [nextCli, 'build'], {
  cwd: projectRoot,
  env: process.env,
  stdio: 'inherit',
});

if (result.error) throw result.error;
process.exit(result.status ?? 1);
