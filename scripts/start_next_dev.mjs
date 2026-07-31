import { closeSync, constants, existsSync, openSync, rmSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const devRoot = join(projectRoot, '.next', 'dev');
const devLock = join(devRoot, 'lock');
const lifecycleRoot = join(projectRoot, 'runtime', 'lifecycle');
const shutdownRequest = join(lifecycleRoot, 'frontend.shutdown');

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
rmSync(shutdownRequest, { force: true });
const child = spawn(process.execPath, [nextCli, 'dev', '-H', '127.0.0.1'], {
  cwd: projectRoot,
  env: process.env,
  stdio: 'inherit',
});

let stopping = false;
const stopChild = () => {
  if (stopping || child.exitCode !== null) return;
  stopping = true;
  child.kill('SIGTERM');
  setTimeout(() => {
    if (child.exitCode === null) child.kill('SIGKILL');
  }, 8000).unref();
};

const watcher = setInterval(() => {
  if (existsSync(shutdownRequest)) stopChild();
}, 250);
watcher.unref();

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, stopChild);
}

child.once('error', (error) => {
  clearInterval(watcher);
  console.error(`[ERREUR] Turbopack n'a pas démarré : ${error.message}`);
  process.exitCode = 1;
});
child.once('exit', (code, signal) => {
  clearInterval(watcher);
  rmSync(shutdownRequest, { force: true });
  // Une terminaison demandée par stop-marvin.ps1 est un succès opérationnel,
  // même si Windows représente SIGTERM comme une fin sans code numérique.
  process.exitCode = stopping ? 0 : (code ?? (signal ? 1 : 0));
});
