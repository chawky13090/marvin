'use strict';

const startButton = document.getElementById('start');
const statusText = document.getElementById('status');

startButton.addEventListener('click', async () => {
  startButton.disabled = true;
  statusText.textContent = 'Démarrage et vérification en cours…';
  try {
    const result = await window.marvinDesktop.start();
    if (result?.success) return;
    statusText.textContent = result?.error || 'Marvin ne répond pas encore. Consulte les journaux de démarrage.';
    startButton.disabled = false;
  } catch (error) {
    statusText.textContent = `Démarrage impossible : ${error?.message || error}`;
    startButton.disabled = false;
  }
});
document.getElementById('quit').addEventListener('click', () => window.marvinDesktop.quit());

const stopResize = () => window.marvinDesktop.stopResize();
document.querySelectorAll('[data-edge]').forEach((handle) => {
  handle.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    window.marvinDesktop.startResize(handle.dataset.edge);
  });
});
window.addEventListener('pointerup', stopResize);
window.addEventListener('pointercancel', stopResize);
window.addEventListener('blur', stopResize);
