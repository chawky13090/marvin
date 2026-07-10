'use client';
/**
 * voiceRecorder — capture micro CENTRALISÉE pour Marvin (STT).
 *
 * Avant ce module, ChatInput.jsx et useVoice.js avaient CHACUN leur propre copie de la
 * logique d'enregistrement (getUserMedia + VAD + MediaRecorder), avec les MÊMES défauts
 * dupliqués deux fois :
 *   1. `getUserMedia({ audio: true })` sans `deviceId` → IMPOSSIBLE de choisir un micro
 *      (casque Bluetooth, micro externe…), toujours le périphérique par défaut du système.
 *   2. `mimeType: 'audio/webm'` figé, sans repli si le navigateur ne le supporte pas.
 *   3. VAD (détection de silence) peu sensible (seuil 0.025, 1100 ms) → rate les phrases
 *      courtes / démarrages doux, l'utilisateur a l'impression que le micro « ne capte rien ».
 *
 * Ce module corrige les 3 à un seul endroit, avec un repli robuste : un micro Bluetooth
 * mémorisé qui a disparu (éteint, batterie à plat, changé) ne bloque plus l'enregistrement —
 * on retente en "ideal", puis on retombe sur le micro par défaut et on efface le choix cassé.
 */

const DEVICE_STORAGE_KEY = 'marvin:mic_device_id';

/** Liste les micros disponibles. Les labels ne sont lisibles qu'après une 1ʳᵉ autorisation
 * micro accordée par l'utilisateur (limitation navigateur, pas un bug). */
export async function listAudioInputDevices() {
  try {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices
      .filter((d) => d.kind === 'audioinput')
      .map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Microphone ${i + 1}`, groupId: d.groupId }));
  } catch {
    return [];
  }
}

export function getSavedDeviceId() {
  try { return localStorage.getItem(DEVICE_STORAGE_KEY) || ''; } catch { return ''; }
}

export function saveDeviceId(deviceId) {
  try {
    if (deviceId) localStorage.setItem(DEVICE_STORAGE_KEY, deviceId);
    else localStorage.removeItem(DEVICE_STORAGE_KEY);
  } catch { /* stockage indisponible (navigation privée…) */ }
}

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/ogg', 'audio/wav',
];

/** Premier type MIME que CE navigateur sait réellement enregistrer (évite le crash
 * "mimeType not supported" sur les navigateurs qui ne gèrent pas webm, ex. certains iOS). */
export function pickSupportedMime() {
  if (typeof MediaRecorder === 'undefined') return '';
  for (const m of MIME_CANDIDATES) {
    try { if (MediaRecorder.isTypeSupported(m)) return m; } catch { /* ignore */ }
  }
  return '';
}

/**
 * Ouvre le flux micro avec repli robuste :
 *   deviceId exact demandé → deviceId "ideal" (le navigateur choisit le plus proche
 *   disponible sans échouer) → micro par défaut (et efface le choix mémorisé cassé).
 * `onLog` (optionnel) reçoit un message à chaque étape de repli, pour affichage debug.
 */
export async function openMicStream(preferredDeviceId, onLog) {
  const log = (m) => { try { onLog && onLog(m); } catch { /* ignore */ } };
  const base = { channelCount: 1, echoCancellation: true, noiseSuppression: true, sampleRate: { ideal: 16000 } };

  if (preferredDeviceId) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { ...base, deviceId: { exact: preferredDeviceId } } });
      return { stream, deviceId: preferredDeviceId, fellBack: false };
    } catch (e) {
      log(`Micro mémorisé indisponible (${e?.name || e?.message || 'erreur'}) — nouvelle tentative…`);
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { ...base, deviceId: { ideal: preferredDeviceId } } });
      return { stream, deviceId: preferredDeviceId, fellBack: false };
    } catch (e) {
      log('Micro toujours indisponible — repli sur le micro par défaut du système.');
      saveDeviceId('');   // le choix mémorisé est cassé (débranché/éteint) → on l'efface
    }
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: base });
  return { stream, deviceId: '', fellBack: !!preferredDeviceId };
}

/** Crée un MediaRecorder avec le meilleur type MIME supporté par ce navigateur. */
export function createRecorder(stream) {
  const mime = pickSupportedMime();
  const mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const chunks = [];
  mr.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  return { mr, chunks, mime: mime || mr.mimeType || 'audio/webm' };
}

/**
 * VAD (détection d'activité vocale) réglé pour réagir vite sur des phrases courtes en
 * français ("salut", "oui"…) — valeurs mesurées : un seuil de 0.025 ratait des débuts de
 * phrase doux ; 0.006 les capte de façon fiable sans se déclencher sur le bruit de fond
 * normal d'une pièce. `minSpeechMs` évite qu'un simple clic/souffle déclenche un faux positif.
 */
export function startVAD(stream, {
  onSilence, speechThreshold = 0.006, minSpeechMs = 120, silenceMs = 900, maxMs = 15000,
} = {}) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    src.connect(analyser);
    const buf = new Uint8Array(analyser.frequencyBinCount);
    let spoke = false, speechStart = 0, silenceStart = 0, raf = 0, stopped = false;
    const started = performance.now();
    const tick = () => {
      if (stopped) return;
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
      const rms = Math.sqrt(sum / buf.length);
      const now = performance.now();
      if (rms > speechThreshold) {
        if (!spoke) speechStart = now;
        if (!spoke && now - speechStart >= minSpeechMs) spoke = true;
        silenceStart = 0;
      } else if (spoke) {
        if (!silenceStart) silenceStart = now;
        else if (now - silenceStart > silenceMs) { stopped = true; onSilence(); return; }
      }
      if (now - started > maxMs) { stopped = true; onSilence(); return; }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return { stop: () => { stopped = true; cancelAnimationFrame(raf); try { ctx.close(); } catch { /* ignore */ } } };
  } catch {
    return null;   // VAD indisponible (navigateur ancien) → l'appelant garde le stop manuel
  }
}
