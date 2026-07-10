'use client';
/**
 * SpeakButton — Petit bouton 🔊 sur chaque message assistant pour le faire lire à haute voix.
 * Utilise le contexte ChatContext.voice (edge-tts backend).
 */
import { useState } from 'react';
import { useChat } from '@/lib/contexts/ChatContext';

export default function SpeakButton({ text, compact = false }) {
  const { voice } = useChat();
  const [speakingThisOne, setSpeakingThisOne] = useState(false);
  const [error, setError] = useState(null);

  if (!text || !text.trim()) return null;

  const handleClick = async (e) => {
    e.stopPropagation();
    if (voice.isSpeaking && speakingThisOne) {
      voice.stopSpeaking();
      setSpeakingThisOne(false);
      return;
    }
    // Stop any other audio first
    voice.stopSpeaking();
    setSpeakingThisOne(true);
    setError(null);
    try {
      await voice.speak(text);
    } catch (err) {
      setError(err.message);
    } finally {
      setSpeakingThisOne(false);
    }
  };

  const active = speakingThisOne && voice.isSpeaking;
  const size = compact ? '22px' : '26px';
  const font = compact ? '11px' : '13px';

  return (
    <button
      onClick={handleClick}
      title={active ? 'Arrêter la lecture' : 'Écouter la réponse'}
      style={{
        width: size, height: size, padding: 0,
        border: '1px solid rgba(79, 140, 255,0.25)',
        background: active ? 'rgba(79, 140, 255,0.18)' : 'transparent',
        borderRadius: '50%',
        cursor: 'pointer',
        fontSize: font,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        color: active ? '#4f8cff' : 'var(--text-muted)',
        transition: 'all 0.15s',
        opacity: error ? 0.6 : 0.85,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.opacity = 1; e.currentTarget.style.background = 'rgba(79, 140, 255,0.12)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.opacity = 0.85; e.currentTarget.style.background = active ? 'rgba(79, 140, 255,0.18)' : 'transparent'; }}
    >
      {error ? '⚠' : active ? '⏸' : '🔊'}
    </button>
  );
}
