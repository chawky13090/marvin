'use client';
import { useRef, useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useChat } from '@/lib/contexts/ChatContext';
import MessageBubble from '@/components/chat/MessageBubble';
import ChatInput from '@/components/chat/ChatInput';
import TypingIndicator from '@/components/chat/TypingIndicator';
import LivingAvatar from '@/components/avatar/LivingAvatar';

const BACKEND_URL = (typeof window!=='undefined'&&window.location?window.location.protocol+'//'+window.location.hostname+':8005':(process.env.NEXT_PUBLIC_BACKEND_URL||'http://127.0.0.1:8005'));

/**
 * ChatContainer — View-only component.
 *
 * All chat state lives in ChatContext (mounted at the layout level).
 * This means navigating to other pages does NOT cancel the running stream.
 *
 * Props:
 *   - conversationId  : sync the active conversation in context
 *   - initialMessages : messages loaded from the server for an existing conversation
 *   - activeModel     : sync the active model in context
 *   - onConversationCreated : called when a new conversation ID is allocated
 *   - onStreamFinish  : called when the stream completes
 */
export default function ChatContainer({
  conversationId,
  initialMessages = [],
  onConversationCreated,
  onStreamFinish,
  activeModel,
}) {
  const [localInput, setLocalInput] = useState('');
  const scrollRef = useRef(null);
  const router = useRouter();

  const {
    messages, status, isLoading, error,
    sendMessage, setMessages, addToolResult, stop,
    setConversationId, setActiveModel,
    subscribeConversationCreated, subscribeStreamFinish,
    voice,
  } = useChat();

  // Detect if a tool call is currently in flight (latest message has a pending invocation)
  const activeTool = (() => {
    const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant');
    if (!lastAssistant?.toolInvocations) return null;
    const pending = lastAssistant.toolInvocations.find(inv => inv.state === 'call' && !inv.result);
    return pending?.toolName || null;
  })();

  // ── Sync conversationId & activeModel from props to context ────────────────
  // The parent (app/page.js) owns the navigation state; we mirror it into the
  // context so the SSE stream uses the latest values.
  useEffect(() => {
    setConversationId(conversationId);
  }, [conversationId, setConversationId]);

  useEffect(() => {
    if (activeModel) setActiveModel(activeModel);
  }, [activeModel, setActiveModel]);

  // ── Subscribe to provider events and forward to parent callbacks ───────────
  useEffect(() => {
    if (!onConversationCreated) return;
    return subscribeConversationCreated(onConversationCreated);
  }, [onConversationCreated, subscribeConversationCreated]);

  useEffect(() => {
    if (!onStreamFinish) return;
    return subscribeStreamFinish(onStreamFinish);
  }, [onStreamFinish, subscribeStreamFinish]);

  // ── Sync initial messages when user clicks a different conversation ────────
  // Use a ref to track the last applied reference. Only re-apply when the
  // reference truly changes (user clicked another conversation in sidebar).
  const lastInitialMsgsRef = useRef(null);
  useEffect(() => {
    if (initialMessages !== lastInitialMsgsRef.current) {
      lastInitialMsgsRef.current = initialMessages;
      if (initialMessages && initialMessages.length > 0) {
        setMessages(initialMessages);
      } else if (!conversationId) {
        // Truly new conversation → clear the chat
        setMessages([]);
      }
    }
  }, [conversationId, initialMessages, setMessages]);

  // ── Auto-scroll vers le bas à chaque nouveau message ──────────────────────
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const raf = requestAnimationFrame(() => {
      if (el) el.scrollTop = el.scrollHeight;
    });
    return () => cancelAnimationFrame(raf);
  }, [messages, isLoading]);

  // ── Confirmation d'outils critiques (appel direct au backend Python) ───────
  const handleConfirmTool = useCallback(async (toolCallId, toolName, args) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName, args }),
      });
      const data = await res.json();
      addToolResult({
        toolCallId,
        result: data.result || data.error || 'Aucun résultat',
      });
    } catch (err) {
      addToolResult({
        toolCallId,
        result: { error: 'Erreur : ' + err.message },
      });
    }
  }, [addToolResult]);

  const handleCancelTool = useCallback((toolCallId) => {
    addToolResult({
      toolCallId,
      result: { error: "Action annulée par l'utilisateur." },
    });
  }, [addToolResult]);

  // Images en attente pour le prochain message
  const [pendingImages, setPendingImages] = useState([]);

  function handleImageAttach(images) {
    setPendingImages(images);
  }

  function handleSend(e) {
    if (e?.preventDefault) e.preventDefault();
    // Voice mode passes the transcribed text via e.voiceText (bypasses local input)
    const voiceText = e?.voiceText;
    const text = (voiceText ?? localInput).trim();

    if ((!text && pendingImages.length === 0) || isLoading) return;

    const images = pendingImages;
    setPendingImages([]);
    if (!voiceText) setLocalInput('');   // don't clear if voice already cleared it

    if (images.length > 0) {
      sendMessage({ text, images });
    } else {
      sendMessage({ text });
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Voice mode banner */}
      {voice?.voiceMode && (
        <div style={{
          padding: '8px 24px',
          background: 'linear-gradient(90deg, rgba(79, 140, 255,0.12), rgba(79, 140, 255,0.04))',
          borderBottom: '1px solid rgba(79, 140, 255,0.25)',
          display: 'flex', alignItems: 'center', gap: '10px',
          fontSize: '12px', color: '#4f8cff',
          flexShrink: 0,
        }}>
          <span style={{
            display: 'inline-block', width: '8px', height: '8px',
            background: '#4f8cff', borderRadius: '50%',
            boxShadow: '0 0 8px #4f8cff',
            animation: voice.isSpeaking ? 'pulse 0.8s ease-in-out infinite' : 'pulse 2s ease-in-out infinite',
          }} />
          <span><strong>Mode vocal actif</strong> — mains libres · {voice.isSpeaking ? '🔊 parle…' : '🎙️ en attente'}</span>

          {/* Voix */}
          {voice.voiceList?.length > 0 && (
            <select value={voice.currentVoice} onChange={e => voice.setVoice(e.target.value)}
              title="Voix de Marvin"
              style={{ background: 'rgba(0,0,0,0.25)', color: '#4f8cff', border: '1px solid rgba(79, 140, 255,0.3)',
                       borderRadius: '6px', fontSize: '11px', padding: '2px 6px', cursor: 'pointer', maxWidth: 160 }}>
              {voice.voiceList.map(v => <option key={v.key} value={v.key} style={{ color: '#000' }}>{v.label?.split('(')[0]?.trim() || v.key}</option>)}
            </select>
          )}

          {/* Vitesse */}
          <select value={voice.rate} onChange={e => voice.setSpeechRate(e.target.value)}
            title="Vitesse de la voix"
            style={{ background: 'rgba(0,0,0,0.25)', color: '#4f8cff', border: '1px solid rgba(79, 140, 255,0.3)',
                     borderRadius: '6px', fontSize: '11px', padding: '2px 6px', cursor: 'pointer' }}>
            <option value="-15%" style={{ color: '#000' }}>🐢 Lent</option>
            <option value="+0%"  style={{ color: '#000' }}>Normal</option>
            <option value="+20%" style={{ color: '#000' }}>⚡ Rapide</option>
            <option value="+40%" style={{ color: '#000' }}>🚀 Très rapide</option>
          </select>

          {/* Interruption (barge-in) */}
          {voice.isSpeaking && (
            <button onClick={voice.stopSpeaking} title="Couper la voix"
              style={{ padding: '3px 10px', background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.4)',
                       borderRadius: '6px', color: '#f87171', fontSize: '11px', cursor: 'pointer' }}>
              ⏹ Stop
            </button>
          )}

          <button
            onClick={voice.toggleVoiceMode}
            style={{
              marginLeft: voice.isSpeaking ? '0' : 'auto', padding: '3px 10px',
              background: 'transparent', border: '1px solid rgba(79, 140, 255,0.3)',
              borderRadius: '6px', color: '#4f8cff', fontSize: '11px',
              cursor: 'pointer',
            }}
          >
            Désactiver
          </button>
        </div>
      )}

      {/* Messages */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '24px',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
        }}
      >
        {messages.length === 0 ? (
          <div className="empty-state">
            <div style={{ marginBottom: 6 }}>
              <LivingAvatar size={148} thinking={isLoading} />
            </div>
            <div className="empty-state-title holo-text" style={{ letterSpacing: '0.18em' }}>MARVIN</div>
            <div className="empty-state-text">
              Je suis <strong style={{ color: '#4f8cff' }}>Marvin</strong>, votre assistant informatique.<br />
              <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', letterSpacing: '0.08em' }}>
                PLUS DE 25 ANS D&apos;EXPÉRIENCE
              </span><br /><br />
              Je peux vous aider à :
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: '12px',
              marginTop: '24px',
              maxWidth: '700px',
              width: '100%',
            }}>
              {[
                // v2.168 — navigue vers la page dédiée plutôt que de lancer une requête
                // chat : signalé par l'utilisateur (les prompts v2.167 déclenchaient des
                // outils lourds — file_large_finder ~150s, email_digest ~54s — beaucoup
                // trop long pour un premier clic). Chaque page a déjà une UI pensée pour
                // ça (listes, filtres, actions rapides), instantané côté client.
                { icon: '📧', label: 'Gérer vos emails', desc: 'Lire, répondre, classer', href: '/emails' },
                { icon: '📅', label: 'Organiser votre agenda', desc: 'RDV, disponibilités', href: '/calendar' },
                { icon: '📁', label: 'Classer vos fichiers', desc: 'Parcourir, rechercher, organiser', href: '/fichiers' },
                { icon: '🖥️', label: 'Contrôler votre PC', desc: 'Santé, logiciels, nettoyage', href: '/systeme' },
              ].map((item) => (
                <button
                  key={item.label}
                  className="card suggestion-card"
                  onClick={() => router.push(item.href)}
                  style={{
                    textAlign: 'center', padding: '20px', cursor: 'pointer',
                    animation: 'slideUp 0.5s ease forwards',
                    font: 'inherit', color: 'inherit', width: '100%',
                  }}
                >
                  <div style={{ fontSize: '2rem', marginBottom: '8px' }}>{item.icon}</div>
                  <div style={{ fontWeight: 600, fontSize: 'var(--font-sm)', marginBottom: '4px' }}>{item.label}</div>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>{item.desc}</div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, index) => (
            <MessageBubble
              key={`${msg.id || index}-${index}`}
              message={msg}
              onConfirmTool={handleConfirmTool}
              onCancelTool={handleCancelTool}
            />
          ))
        )}
        {isLoading && (
          <TypingIndicator
            status={activeTool ? 'tool' : status === 'streaming' ? 'streaming' : 'submitted'}
            toolName={activeTool}
          />
        )}
        {error && (
          <div style={{
            padding: '12px 18px',
            background: 'var(--danger-bg)',
            border: '1px solid var(--danger)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--danger)',
            fontSize: 'var(--font-sm)',
            animation: 'slideUp 0.3s ease',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
          }}>
            <div>
              ⚠️ {(() => {
                const msg = error.message || 'Une erreur est survenue.';
                // Only show "Ollama not running" if the error truly indicates Ollama unreachable
                if (/Impossible de contacter Ollama|getaddrinfo|ECONNREFUSED|ConnectError/i.test(msg)) {
                  return (
                    <>
                      <strong>Ollama n&apos;est pas accessible</strong> sur le port 11434.
                      <div style={{ fontSize: '12px', marginTop: '4px', opacity: 0.85 }}>
                        Démarrez-le avec : <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: '3px' }}>ollama serve</code>
                      </div>
                    </>
                  );
                }
                if (/RemoteProtocolError|modèle a probablement planté/i.test(msg)) {
                  return (
                    <>
                      <strong>Le modèle s&apos;est arrêté pendant la réponse.</strong>
                      <div style={{ fontSize: '12px', marginTop: '4px', opacity: 0.85 }}>
                        Cause probable : manque de RAM/VRAM. Essayez un modèle plus léger (qwen2.5:3b) ou redémarrez Ollama.
                      </div>
                    </>
                  );
                }
                if (/timeout|Délai d.attente/i.test(msg)) {
                  return (
                    <>
                      <strong>Délai dépassé.</strong> Le modèle prend trop de temps à répondre.
                      <div style={{ fontSize: '12px', marginTop: '4px', opacity: 0.85 }}>
                        Causes possibles : modèle pas encore chargé en mémoire (1er appel ~30s), serveur surchargé, ou trop de contexte.
                      </div>
                    </>
                  );
                }
                return `Erreur : ${msg}`;
              })()}
            </div>
            {/* Retry button */}
            <button
              onClick={() => {
                const lastUser = [...messages].reverse().find(m => m.role === 'user');
                if (lastUser) {
                  const text = lastUser.content || lastUser.parts?.find(p => p.type === 'text')?.text || '';
                  if (text) sendMessage({ text });
                }
              }}
              style={{
                alignSelf: 'flex-start',
                marginTop: '4px',
                padding: '4px 12px',
                background: 'transparent',
                border: '1px solid var(--danger)',
                borderRadius: '6px',
                color: 'var(--danger)',
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              🔄 Réessayer
            </button>
          </div>
        )}
      </div>

      {/* Input */}
      <ChatInput
        input={localInput}
        setInput={setLocalInput}
        handleSubmit={handleSend}
        isLoading={isLoading}
        onStop={stop}
        onImageAttach={handleImageAttach}
        messages={messages}
      />
    </div>
  );
}
