'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import LivingAvatar from '@/components/avatar/LivingAvatar';
import { useChat } from '@/lib/contexts/ChatContext';
import { BACKEND_URL } from '@/lib/backend';
import { canSwitchConversation } from '@/lib/chatNavigation.mjs';

export default function DesktopAvatarPage() {
  const { messages, isLoading, sendMessage, stop, voice, setMessages, setConversationId, conversationId } = useChat();
  const [draft, setDraft] = useState('');
  const [desktopStatus, setDesktopStatus] = useState('ready');
  const [windowMode, setWindowMode] = useState('expanded');
  const [activeJob, setActiveJob] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [notice, setNotice] = useState(null);
  const conversationRef = useRef(null);
  const historyRef = useRef(null);
  const noticeTimerRef = useRef(null);
  // v2.254 — plus de plafond à 10 messages : depuis l'ajout de l'historique (v2.253), charger
  // une ancienne conversation coupait ses messages les plus anciens sans moyen de les revoir
  // (slice retire les éléments du tableau, pas juste hors champ visuel). Le panneau défile déjà.
  const visibleMessages = useMemo(() => messages
    .filter((item) => ['user', 'assistant'].includes(item.role) && item.content?.trim()), [messages]);

  useEffect(() => {
    const pane = conversationRef.current;
    if (pane) pane.scrollTop = pane.scrollHeight;
  }, [visibleMessages, isLoading]);

  useEffect(() => {
    const release = () => window.marvinDesktop?.stopResize?.();
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
    window.addEventListener('blur', release);
    return () => {
      release();
      window.removeEventListener('pointerup', release);
      window.removeEventListener('pointercancel', release);
      window.removeEventListener('blur', release);
    };
  }, []);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/coding/jobs?limit=8`, { signal: AbortSignal.timeout(5000) });
        if (!response.ok) return;
        const data = await response.json();
        const job = (data.jobs || []).find((item) => ['queued', 'running', 'interrupted', 'blocked'].includes(item.status));
        if (active) setActiveJob(job || null);
      } catch { /* Le chat reste utilisable si le backend redémarre. */ }
    };
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  useEffect(() => {
    if (!showHistory) return;
    const closeOnOutsideClick = (event) => {
      if (historyRef.current && !historyRef.current.contains(event.target)) setShowHistory(false);
    };
    document.addEventListener('pointerdown', closeOnOutsideClick);
    return () => document.removeEventListener('pointerdown', closeOnOutsideClick);
  }, [showHistory]);

  useEffect(() => () => { if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current); }, []);

  const showNotice = (text) => {
    setNotice(text);
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = setTimeout(() => setNotice(null), 3500);
  };

  const startNewConversation = () => {
    if (!canSwitchConversation({ isLoading, liveConversationId: conversationId, targetConversationId: null })) {
      showNotice('Réponse en cours — attends la fin avant de repartir à zéro.');
      return;
    }
    setMessages([]);
    setConversationId(null);
    setShowHistory(false);
  };

  const toggleHistory = async () => {
    const opening = !showHistory;
    setShowHistory(opening);
    if (!opening) return;
    setHistoryLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/conversations?limit=50`, { signal: AbortSignal.timeout(6000) });
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      setConversations(Array.isArray(data) ? data : (data.conversations || []));
    } catch {
      showNotice('Historique indisponible pour le moment.');
    } finally {
      setHistoryLoading(false);
    }
  };

  const loadConversation = async (id) => {
    if (id === conversationId) { setShowHistory(false); return; }
    if (!canSwitchConversation({ isLoading, liveConversationId: conversationId, targetConversationId: id })) {
      showNotice('Réponse en cours — attends la fin avant de changer de conversation.');
      return;
    }
    try {
      const response = await fetch(`${BACKEND_URL}/api/conversations/${id}`, { signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      setMessages(data.messages || []);
      setConversationId(id);
      setShowHistory(false);
    } catch {
      showNotice('Conversation inaccessible.');
    }
  };

  const submit = async (text = draft) => {
    const value = String(text || '').trim();
    if (!value || isLoading) return;
    setDraft('');
    await sendMessage({ text: value });
  };

  const talk = async () => {
    if (voice.isListening) {
      voice.stopListening();
      return;
    }
    await voice.startListening((text) => submit(text));
  };

  const stopMarvin = async () => {
    if (!window.marvinDesktop?.stop) return;
    setDesktopStatus('stopping');
    await window.marvinDesktop.stop();
  };

  const openMarvin = async () => {
    if (!window.marvinDesktop?.openMain) {
      window.location.assign('/');
      return;
    }
    setDesktopStatus('opening');
    const result = await window.marvinDesktop.openMain();
    if (!result?.success) setDesktopStatus(result?.error || 'open-error');
    else setDesktopStatus('ready');
  };

  const toggleWindowMode = async () => {
    const requested = windowMode === 'expanded' ? 'compact' : 'expanded';
    const result = await window.marvinDesktop?.setWindowMode?.(requested);
    setWindowMode(result?.mode || requested);
  };

  const startResize = (edge) => (event) => {
    if (event.button !== 0) return;
    window.marvinDesktop?.startResize?.(edge);
  };

  return (
    <div style={{ height: '100vh', padding: 16, boxSizing: 'border-box', background: 'radial-gradient(circle at 50% 20%, rgba(79,140,255,.18), transparent 42%), #09090b', color: 'var(--text-primary)', overflow: 'hidden', userSelect: 'none', display: 'flex', flexDirection: 'column' }}>
      {RESIZE_EDGES.map(({ edge, style }) => (
        <div key={edge} onPointerDown={startResize(edge)} style={{ WebkitAppRegion: 'no-drag', position: 'fixed', zIndex: 20, ...style }} />
      ))}

      <div style={{ WebkitAppRegion: 'drag', display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, position: 'relative' }}>
        <span style={{ fontSize: 12, fontWeight: 750, letterSpacing: '.08em' }}>MARVIN</span>
        <div style={{ WebkitAppRegion: 'no-drag', display: 'flex', gap: 5 }}>
          <button type="button" onClick={startNewConversation} title="Nouvelle conversation" style={smallButton}>+</button>
          <button type="button" onClick={toggleHistory} title="Historique des conversations" style={{ ...smallButton, ...(showHistory ? activeSmallButton : null) }}>🕘</button>
          <button type="button" onClick={toggleWindowMode} title={windowMode === 'expanded' ? 'Passer en mode compact' : 'Agrandir la conversation'} style={smallButton}>{windowMode === 'expanded' ? '⤡' : '⤢'}</button>
          <button type="button" onClick={openMarvin} title="Ouvrir Marvin dans le navigateur" style={smallButton}>↗</button>
          <button type="button" onClick={() => window.marvinDesktop?.minimize?.()} title="Réduire dans la barre des tâches" style={smallButton}>─</button>
          <button type="button" onClick={() => window.marvinDesktop?.quit?.()} title="Fermer l’avatar" style={smallButton}>×</button>
        </div>

        {showHistory && (
          <div ref={historyRef} style={{ WebkitAppRegion: 'no-drag', position: 'absolute', top: 30, right: 0, width: 260, maxHeight: 280, overflow: 'auto', background: '#111116', border: '1px solid var(--border)', borderRadius: 10, boxShadow: '0 12px 28px rgba(0,0,0,.45)', zIndex: 30, padding: 6 }}>
            {historyLoading && <div style={{ padding: 8, fontSize: 11, color: 'var(--text-secondary)' }}>Chargement…</div>}
            {!historyLoading && conversations.length === 0 && <div style={{ padding: 8, fontSize: 11, color: 'var(--text-secondary)' }}>Aucune conversation.</div>}
            {!historyLoading && conversations.map((conv) => (
              <button
                key={conv.id}
                type="button"
                onClick={() => loadConversation(conv.id)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', border: 0, borderRadius: 7,
                  padding: '7px 8px', marginBottom: 2, cursor: 'pointer', fontFamily: 'inherit',
                  background: conv.id === conversationId ? 'rgba(79,140,255,.16)' : 'transparent',
                  color: 'var(--text-primary)',
                }}
              >
                <div style={{ fontSize: 11.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{conv.title || 'Sans titre'}</div>
                <div style={{ fontSize: 9.5, color: 'var(--text-secondary)', marginTop: 1 }}>{formatConvDate(conv.updated_at || conv.created_at)}</div>
              </button>
            ))}
          </div>
        )}
      </div>

      {notice && (
        <div role="status" style={{ marginBottom: 8, padding: '6px 9px', borderRadius: 8, border: '1px solid rgba(251,113,133,.35)', background: 'rgba(251,113,133,.08)', color: '#fca5a5', fontSize: 10.5 }}>
          {notice}
        </div>
      )}

      <div style={{ WebkitAppRegion: 'no-drag', display: 'grid', justifyItems: 'center', gap: 5 }}>
        <button type="button" onClick={talk} disabled={voice.isTranscribing} aria-label={voice.isListening ? 'Arrêter l’écoute' : 'Parler à Marvin'} style={{ border: 0, background: 'transparent', cursor: 'pointer', padding: 0 }}>
          <LivingAvatar size={windowMode === 'compact' ? 76 : 104} thinking={isLoading || voice.isTranscribing} activeBeat={0.65} />
        </button>
        <div style={{ fontSize: 12, color: voice.voiceError ? '#fb7185' : 'var(--text-secondary)', textAlign: 'center', minHeight: 18 }}>
          {voice.voiceError || (voice.isListening ? 'Je t’écoute…' : voice.isTranscribing ? 'Transcription…' : isLoading ? 'Je travaille…' : 'Clique sur l’avatar pour parler')}
        </div>
      </div>

      {activeJob && (
        <div role="status" style={{ marginTop: 6, padding: '6px 9px', borderRadius: 8, border: '1px solid rgba(79,140,255,.28)', background: 'rgba(79,140,255,.08)', color: '#9ac2ff', fontSize: 10, display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <span>Mission Code · {activeJob.progress?.stage || activeJob.status}</span>
          <strong>{Number(activeJob.progress?.percent || 0)}%</strong>
        </div>
      )}

      <div ref={conversationRef} aria-label="Conversation avec Marvin" style={{ userSelect: 'text', cursor: 'text', marginTop: 8, flex: 1, minHeight: windowMode === 'compact' ? 110 : 210, overflow: 'auto', padding: 10, border: '1px solid var(--border)', borderRadius: 10, background: 'rgba(255,255,255,.025)', fontSize: 12, lineHeight: 1.45 }}>
        {visibleMessages.length === 0 && <div style={{ color: 'var(--text-secondary)' }}>Prêt. Parle-moi ou écris ta demande.</div>}
        {visibleMessages.map((message, index) => (
          <div key={`${message.id || index}-${message.role}`} style={{ marginBottom: 9, padding: '8px 9px', borderRadius: 9, whiteSpace: 'pre-wrap', background: message.role === 'user' ? 'rgba(79,140,255,.14)' : 'rgba(255,255,255,.035)', borderLeft: `2px solid ${message.role === 'user' ? '#4f8cff' : '#8fe3ff'}` }}>
            <div style={{ marginBottom: 3, color: message.role === 'user' ? '#79a8ff' : '#8fe3ff', fontSize: 9, fontWeight: 800, letterSpacing: '.08em' }}>{message.role === 'user' ? 'VOUS' : 'MARVIN'}</div>
            {message.content}
          </div>
        ))}
        {isLoading && <div style={{ color: '#8fe3ff', fontSize: 11 }}>Marvin travaille…</div>}
      </div>

      <form onSubmit={(event) => { event.preventDefault(); submit(); }} style={{ display: 'flex', gap: 7, marginTop: 9 }}>
        <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); } }} placeholder="Écris une demande… (Maj+Entrée : nouvelle ligne)" rows={2} style={{ flex: 1, minWidth: 0, resize: 'none', padding: '9px 10px', borderRadius: 9, border: '1px solid var(--border)', background: '#111116', color: 'var(--text-primary)', fontFamily: 'inherit' }} />
        <button type="submit" disabled={isLoading || !draft.trim()} style={primaryButton}>Envoyer</button>
      </form>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 }}>
        <button type="button" onClick={openMarvin} style={{ ...secondaryButton, color: '#8fe3ff' }}>{desktopStatus === 'opening' ? 'Ouverture…' : 'Ouvrir Marvin'}</button>
        <button type="button" onClick={talk} style={secondaryButton}>{voice.isListening ? 'Stop micro' : 'Parler'}</button>
        <button type="button" onClick={() => isLoading ? stop() : voice.toggleVoiceMode()} style={secondaryButton}>{isLoading ? 'Stop tâche' : voice.voiceMode ? 'Voix active' : 'Voix inactive'}</button>
        <button type="button" onClick={stopMarvin} disabled={desktopStatus === 'stopping'} style={{ ...secondaryButton, color: '#fb7185' }}>{desktopStatus === 'stopping' ? 'Arrêt…' : 'Arrêter Marvin'}</button>
      </div>
    </div>
  );
}

function formatConvDate(value) {
  if (!value) return '';
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

const smallButton = { WebkitAppRegion: 'no-drag', width: 25, height: 25, padding: 0, borderRadius: 7, borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--border)', background: 'rgba(255,255,255,.04)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: 13 };
const activeSmallButton = { background: 'rgba(79,140,255,.22)', borderColor: 'rgba(79,140,255,.45)' };
const primaryButton = { border: 0, borderRadius: 9, padding: '0 11px', background: 'var(--accent-primary)', color: '#fff', fontWeight: 700, cursor: 'pointer' };
const secondaryButton = { border: '1px solid var(--border)', borderRadius: 8, padding: '7px 5px', background: 'rgba(255,255,255,.035)', color: 'var(--text-secondary)', fontSize: 10.5, cursor: 'pointer' };

const RESIZE_EDGES = [
  { edge: 'n', style: { top: 0, left: 10, right: 10, height: 6, cursor: 'ns-resize' } },
  { edge: 's', style: { bottom: 0, left: 10, right: 10, height: 6, cursor: 'ns-resize' } },
  { edge: 'w', style: { left: 0, top: 10, bottom: 10, width: 6, cursor: 'ew-resize' } },
  { edge: 'e', style: { right: 0, top: 10, bottom: 10, width: 6, cursor: 'ew-resize' } },
  { edge: 'nw', style: { top: 0, left: 0, width: 12, height: 12, cursor: 'nwse-resize' } },
  { edge: 'se', style: { bottom: 0, right: 0, width: 12, height: 12, cursor: 'nwse-resize' } },
  { edge: 'ne', style: { top: 0, right: 0, width: 12, height: 12, cursor: 'nesw-resize' } },
  { edge: 'sw', style: { bottom: 0, left: 0, width: 12, height: 12, cursor: 'nesw-resize' } },
];
