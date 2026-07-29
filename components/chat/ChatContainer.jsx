'use client';
import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useChat } from '@/lib/contexts/ChatContext';
import MessageBubble from '@/components/chat/MessageBubble';
import ChatInput from '@/components/chat/ChatInput';
import TypingIndicator from '@/components/chat/TypingIndicator';
import LivingAvatar from '@/components/avatar/LivingAvatar';
import QuietWelcome from '@/components/chat/QuietWelcome';
import ConversationViewToolbar from '@/components/chat/ConversationViewToolbar';
import { BACKEND_URL } from '@/lib/backend';
import { isLiveConversation } from '@/lib/chatNavigation.mjs';
import {
  conversationAuditToMarkdown,
  createConversationAudit,
  groupConversationMessages,
} from '@/lib/chatPresentation.mjs';

// v2.169 — salutation dynamique (façon Claude/ChatGPT) au lieu d'un titre "MARVIN" figé +
// tagline marketing datée ("25 ans d'expérience"). Pas de prénom en dur : Marvin est pensé
// distribuable à d'autres utilisateurs (voir CLAUDE.md), aucun réglage "nom" n'existe encore.
function getGreeting() {
  const h = new Date().getHours();
  if (h < 5) return 'Bonne nuit';
  if (h < 12) return 'Bonjour';
  if (h < 18) return 'Bon après-midi';
  return 'Bonsoir';
}

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
  const [viewMode, setViewMode] = useState('reading');
  const [toolbarHost, setToolbarHost] = useState(null);
  const [toolbarHostResolved, setToolbarHostResolved] = useState(false);
  const scrollRef = useRef(null);
  // v2.183 — "coller au bas" façon Claude/ChatGPT : l'ancien effet forçait scrollTop=scrollHeight
  // à CHAQUE frappe de token pendant le streaming, kidnappant le scroll dès que l'utilisateur
  // remontait pour relire un passage. Ne force plus le scroll que si l'utilisateur était déjà
  // proche du bas juste avant la mise à jour (seuil 80px) — sinon sa position est respectée.
  const stickToBottomRef = useRef(true);

  // Le brouillon survit aux changements de page. Une demande préparée par Code Workspace
  // reste prioritaire et remplace le brouillon courant uniquement une fois.
  useEffect(() => {
    const draft = window.sessionStorage.getItem('marvin:code-draft');
    if (draft) {
      window.sessionStorage.removeItem('marvin:code-draft');
      setLocalInput(draft.slice(0, 20000));
      return;
    }
    const key = `marvin:chat-draft:${conversationId || 'new'}`;
    setLocalInput((window.sessionStorage.getItem(key) || '').slice(0, 20000));
  }, [conversationId]);

  useEffect(() => {
    const key = `marvin:chat-draft:${conversationId || 'new'}`;
    if (localInput) window.sessionStorage.setItem(key, localInput.slice(0, 20000));
    else window.sessionStorage.removeItem(key);
  }, [conversationId, localInput]);

  useEffect(() => {
    const saved = window.localStorage.getItem('marvin:conversation-view');
    if (['reading', 'technical', 'audit'].includes(saved)) setViewMode(saved);
  }, []);

  useEffect(() => {
    setToolbarHost(document.getElementById('marvin-conversation-toolbar-host'));
    setToolbarHostResolved(true);
  }, []);

  const {
    messages, status, isLoading, error,
    sendMessage, setMessages, addToolResult, stop,
    conversationId: liveConversationId,
    setConversationId, setActiveModel,
    subscribeConversationCreated, subscribeStreamFinish,
    voice,
  } = useChat();

  // Detect if a tool call is currently in flight (latest message has a pending invocation)
  const activeInvocation = (() => {
    const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant');
    if (!lastAssistant?.toolInvocations) return null;
    return lastAssistant.toolInvocations.find(inv => inv.state === 'call' && !inv.result) || null;
  })();
  const activeTool = activeInvocation?.toolName || null;

  // v2.244 — les appels techniques consécutifs forment une seule activité lisible.
  const displayMessages = useMemo(
    () => viewMode === 'audit' ? messages : groupConversationMessages(messages),
    [messages, viewMode],
  );
  const lastCodingMissionMessageIndex = useMemo(() => {
    let latest = -1;
    displayMessages.forEach((message, index) => {
      const fromParts = message.parts
        ?.filter((part) => part.type === 'tool-invocation')
        .map((part) => part.toolInvocation) || [];
      const invocations = message.toolInvocations?.length ? message.toolInvocations : fromParts;
      if (invocations.some((tool) => (
        ['code_workspace_start', 'code_workspace_status', 'code_workspace_control'].includes(tool.toolName)
        && tool.result !== undefined
      ))) latest = index;
    });
    return latest;
  }, [displayMessages]);

  const changeViewMode = useCallback((mode) => {
    if (!['reading', 'technical', 'audit'].includes(mode)) return;
    setViewMode(mode);
    window.localStorage.setItem('marvin:conversation-view', mode);
  }, []);

  const exportAudit = useCallback((format) => {
    const audit = createConversationAudit(messages);
    const isJson = format === 'json';
    const content = isJson ? `${JSON.stringify(audit, null, 2)}\n` : conversationAuditToMarkdown(audit);
    const blob = new Blob([content], { type: isJson ? 'application/json' : 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const safeId = String(conversationId || 'nouvelle').replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 80);
    link.href = url;
    link.download = `marvin-audit-${safeId}.${isJson ? 'json' : 'md'}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }, [conversationId, messages]);

  // ── Sync conversationId & activeModel from props to context ────────────────
  // The parent (app/page.js) owns the navigation state; we mirror it into the
  // context so the SSE stream uses the latest values.
  useEffect(() => {
    if (isLiveConversation({
      isLoading,
      liveConversationId,
      targetConversationId: conversationId,
      liveMessageCount: messages.length,
    })) return;
    setConversationId(conversationId);
  }, [conversationId, isLoading, liveConversationId, messages.length, setConversationId]);

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
      if (isLiveConversation({
        isLoading,
        liveConversationId,
        targetConversationId: conversationId,
        liveMessageCount: messages.length,
      })) return;
      if (Array.isArray(initialMessages)) {
        setMessages(initialMessages);
      } else if (!conversationId) {
        // Truly new conversation → clear the chat
        setMessages([]);
      }
    }
  }, [conversationId, initialMessages, isLoading, liveConversationId, messages.length, setMessages]);

  // ── Auto-scroll vers le bas à chaque nouveau message — SEULEMENT si l'utilisateur
  // était déjà collé au bas (voir stickToBottomRef ci-dessus). ────────────────────
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !stickToBottomRef.current) return;
    const raf = requestAnimationFrame(() => {
      if (el) el.scrollTop = el.scrollHeight;
    });
    return () => cancelAnimationFrame(raf);
  }, [messages, isLoading]);

  // Détecte un scroll manuel de l'utilisateur : à moins de 80px du bas → on reste collé
  // (comportement historique) ; plus haut → on laisse sa position tranquille, même en
  // plein streaming.
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distanceFromBottom < 80;
  }, []);

  // Un nouvel envoi recolle toujours au bas (même si l'utilisateur avait remonté lire
  // un ancien message) — comportement attendu quand on relance une conversation.
  const stickToBottomOnSend = useCallback(() => {
    stickToBottomRef.current = true;
  }, []);

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

    stickToBottomOnSend();
    if (images.length > 0) {
      sendMessage({ text, images });
    } else {
      sendMessage({ text });
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {messages.length > 0 && toolbarHost && createPortal(
        <ConversationViewToolbar
          mode={viewMode}
          onModeChange={changeViewMode}
          onExport={exportAudit}
          hasMessages
          inHeader
        />,
        toolbarHost,
      )}
      {messages.length > 0 && toolbarHostResolved && !toolbarHost && (
        <ConversationViewToolbar
          mode={viewMode}
          onModeChange={changeViewMode}
          onExport={exportAudit}
          hasMessages
        />
      )}

      {/* Messages */}
      <div
        ref={scrollRef}
        data-active-conversation-id={conversationId || ''}
        data-live-conversation-id={liveConversationId || ''}
        data-chat-status={status}
        data-message-count={messages.length}
        onScroll={handleScroll}
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
          <QuietWelcome
            greeting={getGreeting()}
            input={localInput}
            setInput={setLocalInput}
            handleSubmit={handleSend}
            isLoading={isLoading}
            onStop={stop}
            onImageAttach={handleImageAttach}
            messages={messages}
          />
        ) : (
          displayMessages.map((msg, index) => (
            <MessageBubble
              key={`${msg.id || index}-${index}`}
              message={msg}
              viewMode={viewMode}
              showMissionTracker={index === lastCodingMissionMessageIndex}
              onConfirmTool={handleConfirmTool}
              onCancelTool={handleCancelTool}
            />
          ))
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
                      <strong>Ollama n&apos;est pas accessible</strong> sur le port {process.env.NEXT_PUBLIC_OLLAMA_PORT || '11434'}.
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
                  if (text) { stickToBottomOnSend(); sendMessage({ text, cortex: lastUser.cortexRequested }); }
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

      {isLoading && (
        <TypingIndicator
          status={activeTool ? 'tool' : status === 'streaming' ? 'streaming' : 'submitted'}
          toolName={activeTool}
          progress={activeInvocation?.progress}
          progressEvents={activeInvocation?.progressEvents}
          startedAt={activeInvocation?.startedAt}
          onStop={stop}
        />
      )}

      {/* Central sur une nouvelle conversation, ancré en bas après le premier message. */}
      {messages.length > 0 && (
        <ChatInput
          input={localInput}
          setInput={setLocalInput}
          handleSubmit={handleSend}
          isLoading={isLoading}
          onStop={stop}
          onImageAttach={handleImageAttach}
          messages={messages}
        />
      )}
    </div>
  );
}
