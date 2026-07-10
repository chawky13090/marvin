'use client';
/**
 * useVoice — Hook React pour la voix de Marvin.
 *
 * Capacités :
 *   - Text-to-Speech via Edge-TTS backend (voix françaises neurales)
 *   - Lecture audio avec contrôle (play/pause/stop)
 *   - Mode vocal continu : auto-speak + auto-listen
 *
 * Public API :
 *   { speak, stopSpeaking, isSpeaking, currentVoice, setVoice, voiceList,
 *     voiceMode, toggleVoiceMode }
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { openMicStream, createRecorder, startVAD, listAudioInputDevices, getSavedDeviceId, saveDeviceId } from '@/lib/voice/voiceRecorder';

const BACKEND_URL = (typeof window!=='undefined'&&window.location?window.location.protocol+'//'+window.location.hostname+':8005':(process.env.NEXT_PUBLIC_BACKEND_URL||'http://127.0.0.1:8005'));

const VOICE_STORAGE_KEY  = 'marvin:voice';
const VOICE_MODE_KEY     = 'marvin:voice_mode';

// Découpe un texte en segments « parlables » : la 1ʳᵉ phrase courte d'abord
// (pour démarrer la voix au plus vite), puis des blocs ~220 caractères.
function splitForSpeech(text) {
  const raw = (text || '').replace(/\s+/g, ' ').trim();
  if (!raw) return [];
  const sentences = raw.match(/[^.!?…\n]+[.!?…]+|\S[^.!?…\n]*$/g) || [raw];
  const chunks = [];
  let cur = '';
  for (let s of sentences) {
    s = s.trim();
    if (!s) continue;
    // 1er morceau : on flushe dès la 1ère phrase pour parler tout de suite
    if (chunks.length === 0 && !cur) { chunks.push(s); continue; }
    if ((cur + ' ' + s).trim().length > 220) { if (cur) chunks.push(cur.trim()); cur = s; }
    else cur = (cur ? cur + ' ' : '') + s;
  }
  if (cur.trim()) chunks.push(cur.trim());
  return chunks;
}

export function useVoice() {
  const [isSpeaking, setIsSpeaking]   = useState(false);
  const [currentVoice, setCurrentVoice] = useState('henri');
  const [rate, setRate]               = useState('+0%');   // vitesse de parole
  const [voiceList, setVoiceList]     = useState([]);
  const [voiceMode, setVoiceMode]     = useState(false);  // continuous voice conversation
  const [isListening, setIsListening] = useState(false);  // micro en écoute (STT)
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [voiceError, setVoiceError]   = useState('');     // dernière erreur micro (affichable)
  const [micDevices, setMicDevices]   = useState([]);     // périphériques d'entrée audio disponibles
  const [micDeviceId, setMicDeviceIdState] = useState('');// micro choisi (vide = défaut système)
  const audioRef = useRef(null);
  const speakSeqRef = useRef(0);   // incrémenté à chaque speak → annule les précédents
  // Écoute micro (STT)
  const mrRef = useRef(null);
  const listenStreamRef = useRef(null);
  const vadRef = useRef(null);
  const listeningRef = useRef(false);

  // Charge le micro mémorisé + la liste des périphériques disponibles
  useEffect(() => {
    setMicDeviceIdState(getSavedDeviceId());
    listAudioInputDevices().then(setMicDevices);
    // La liste se complète/rafraîchit quand l'utilisateur branche/débranche un périphérique
    const onChange = () => listAudioInputDevices().then(setMicDevices);
    navigator.mediaDevices?.addEventListener?.('devicechange', onChange);
    return () => navigator.mediaDevices?.removeEventListener?.('devicechange', onChange);
  }, []);

  const setMicDevice = useCallback((deviceId) => {
    setMicDeviceIdState(deviceId);
    saveDeviceId(deviceId);
  }, []);

  // Load persisted voice preference
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const v = localStorage.getItem(VOICE_STORAGE_KEY);
      if (v) setCurrentVoice(v);
      const m = localStorage.getItem(VOICE_MODE_KEY);
      if (m === 'true') setVoiceMode(true);
      const rr = localStorage.getItem('marvin:voice_rate');
      if (rr) setRate(rr);
    } catch { /* ignore */ }
  }, []);

  // Load available voices once
  useEffect(() => {
    fetch(`${BACKEND_URL}/api/voice/voices`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.voices) setVoiceList(d.voices); })
      .catch(() => {});
  }, []);

  const setVoice = useCallback((voiceKey) => {
    setCurrentVoice(voiceKey);
    try { localStorage.setItem(VOICE_STORAGE_KEY, voiceKey); } catch { }
  }, []);

  const setSpeechRate = useCallback((r) => {
    setRate(r);
    try { localStorage.setItem('marvin:voice_rate', r); } catch { }
  }, []);

  const toggleVoiceMode = useCallback(() => {
    setVoiceMode(prev => {
      const next = !prev;
      try { localStorage.setItem(VOICE_MODE_KEY, String(next)); } catch { }
      return next;
    });
  }, []);

  /**
   * Speak the given text. Returns a promise that resolves when audio finishes
   * (or rejects on error). Auto-stops any currently-playing audio.
   */
  // Refs pour que la boucle de lecture (créée une fois) lise les valeurs à jour
  const voiceRef = useRef(currentVoice);
  const rateRef  = useRef(rate);
  useEffect(() => { voiceRef.current = currentVoice; }, [currentVoice]);
  useEffect(() => { rateRef.current = rate; }, [rate]);

  const queueRef    = useRef([]);     // segments de texte en attente
  const prefetchRef = useRef(null);   // Promise<url> du prochain segment (préchargé)
  const playingRef  = useRef(false);  // la boucle de lecture tourne-t-elle ?

  const fetchChunkAudio = useCallback(async (chunk) => {
    const res = await fetch(`${BACKEND_URL}/api/voice/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: chunk, voice: voiceRef.current, rate: rateRef.current, pitch: '+0Hz' }),
    });
    if (!res.ok) throw new Error('TTS ' + res.status);
    return URL.createObjectURL(await res.blob());
  }, []);

  // Boucle : consomme la file, lit chaque segment, précharge le suivant (pipeline)
  const runPlayer = useCallback(async () => {
    if (playingRef.current) return;
    playingRef.current = true;
    setIsSpeaking(true);
    try {
      while (playingRef.current && (queueRef.current.length || prefetchRef.current)) {
        let url = prefetchRef.current;
        prefetchRef.current = null;
        if (!url && queueRef.current.length) url = fetchChunkAudio(queueRef.current.shift()).catch(() => null);
        // précharge le suivant pendant qu'on attend/lit le courant
        if (queueRef.current.length) prefetchRef.current = fetchChunkAudio(queueRef.current.shift()).catch(() => null);
        const resolved = await url;
        if (!playingRef.current) { if (resolved) URL.revokeObjectURL(resolved); break; }
        if (!resolved) continue;
        await new Promise((resolve) => {
          const audio = new Audio(resolved);
          audioRef.current = audio;
          const done = () => { try { URL.revokeObjectURL(resolved); } catch {} resolve(); };
          audio.onended = done;
          audio.onerror = done;
          audio.play().catch(done);
        });
      }
    } finally {
      playingRef.current = false;
      audioRef.current = null;
      setIsSpeaking(false);
    }
  }, [fetchChunkAudio]);

  // Ajoute du texte à lire (sans interrompre) → utilisé pendant le streaming LLM
  const enqueueSpeech = useCallback((text) => {
    const chunks = splitForSpeech(text);
    if (!chunks.length) return;
    queueRef.current.push(...chunks);
    runPlayer();
  }, [runPlayer]);

  const stopSpeaking = useCallback(() => {
    playingRef.current = false;
    queueRef.current = [];
    if (prefetchRef.current) { prefetchRef.current.then(u => u && URL.revokeObjectURL(u)).catch(() => {}); prefetchRef.current = null; }
    if (audioRef.current) {
      try { audioRef.current.pause(); audioRef.current.src = ''; } catch { }
      audioRef.current = null;
    }
    setIsSpeaking(false);
  }, []);

  /**
   * Démarre l'écoute micro (module voiceRecorder partagé — voir son en-tête pour le détail
   * des correctifs : choix de périphérique + repli robuste, MIME adaptatif, VAD sensible).
   * Auto-stop après ~0,9 s de silence (mains libres). Appelle onText(transcription) une fois
   * la parole transcrite.
   */
  const startListening = useCallback(async (onText) => {
    if (listeningRef.current) return;
    stopSpeaking();   // évite que le micro capte la voix de Marvin
    setVoiceError('');
    try {
      const { stream, fellBack } = await openMicStream(micDeviceId, (m) => setVoiceError(m));
      if (fellBack) setVoiceError('Micro choisi indisponible — micro par défaut utilisé.');
      listenStreamRef.current = stream;
      const { mr, chunks, mime } = createRecorder(stream);
      mr.onstop = async () => {
        if (vadRef.current) { try { vadRef.current.stop(); } catch {} vadRef.current = null; }
        stream.getTracks().forEach(t => t.stop());
        listenStreamRef.current = null;
        listeningRef.current = false;
        setIsListening(false);
        const blob = new Blob(chunks, { type: mime });
        if (blob.size < 1200) return;   // trop court → on ignore
        setIsTranscribing(true);
        try {
          const fd = new FormData();
          fd.append('file', blob, 'recording.webm');
          fd.append('language', 'fr');
          const res = await fetch(`${BACKEND_URL}/api/voice/transcribe`, { method: 'POST', body: fd });
          if (res.ok) {
            const data = await res.json();
            if (data.text && data.text.trim() && onText) onText(data.text.trim());
          } else {
            setVoiceError(`Transcription échouée (HTTP ${res.status}).`);
          }
        } catch { setVoiceError('Transcription impossible (réseau).'); } finally { setIsTranscribing(false); }
      };
      mr.start();
      mrRef.current = mr;
      listeningRef.current = true;
      setIsListening(true);
      vadRef.current = startVAD(stream, { onSilence: () => { if (mrRef.current && mrRef.current.state !== 'inactive') mrRef.current.stop(); } });
    } catch (e) {
      listeningRef.current = false;
      setIsListening(false);
      setVoiceError(e?.name === 'NotAllowedError' ? 'Accès au micro refusé (autorisation navigateur).' : (e?.message || 'Erreur micro.'));
      throw e;
    }
  }, [stopSpeaking, micDeviceId]);

  const stopListening = useCallback(() => {
    if (mrRef.current && mrRef.current.state !== 'inactive') mrRef.current.stop();
  }, []);

  /**
   * Parle un texte complet (one-shot) : remplace toute lecture en cours.
   * INNOVATION : démarre dès la 1ère phrase, le reste est préchargé en pipeline.
   */
  const speak = useCallback(async (text) => {
    if (!text || !text.trim()) return;
    stopSpeaking();
    // petite latence pour laisser l'audio précédent se libérer
    queueRef.current = splitForSpeech(text);
    runPlayer();
  }, [stopSpeaking, runPlayer]);

  // Cleanup on unmount
  useEffect(() => {
    return () => { stopSpeaking(); stopListening(); };
  }, [stopSpeaking, stopListening]);

  return {
    speak,
    enqueueSpeech,   // pour lire au fil de l'eau pendant le streaming LLM
    stopSpeaking,
    isSpeaking,
    startListening,  // STT mains libres (VAD auto-stop → transcription)
    stopListening,
    isListening,
    isTranscribing,
    voiceError,      // dernière erreur micro/transcription (affichable, '' si aucune)
    micDevices,      // [{deviceId, label}] — micros disponibles
    micDeviceId,     // micro choisi (vide = défaut système)
    setMicDevice,    // (deviceId) => void — change + mémorise le micro choisi
    currentVoice,
    setVoice,
    rate,
    setSpeechRate,
    voiceList,
    voiceMode,
    toggleVoiceMode,
  };
}
