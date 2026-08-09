'use client';
/**
 * useSecretary — Hook React personnalisé remplaçant @ai-sdk/react.
 * Appelle le backend Python FastAPI (localhost:8005) via SSE.
 *
 * Interface compatible avec l'usage existant dans ChatContainer :
 *   { messages, status, isLoading, error, sendMessage, setMessages, addToolResult, stop }
 *
 * Format des messages (compatible MessageBubble.jsx) :
 *   { id, role, content, parts: [{type:'text', text}, {type:'tool-invocation', toolInvocation:{...}}], toolInvocations:[...] }
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { BACKEND_URL } from '@/lib/backend';
import { durableChatEvents } from '@/lib/chatStream';

function genId() {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

function extractText(msg) {
  if (typeof msg.content === 'string') return msg.content;
  if (Array.isArray(msg.parts)) {
    return msg.parts.filter(p => p.type === 'text').map(p => p.text).join('');
  }
  return '';
}

export function useSecretary({ conversationId, onConversationCreated, onStreamFinish, activeModel }) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState('ready');   // 'ready'|'submitted'|'streaming'|'error'
  const [error, setError] = useState(null);

  const abortRef = useRef(null);
  const onConversationCreatedRef = useRef(onConversationCreated);
  onConversationCreatedRef.current = onConversationCreated;
  const onStreamFinishRef = useRef(onStreamFinish);
  onStreamFinishRef.current = onStreamFinish;

  // Track conversationId and messages via refs so sendMessage's closure always
  // sees the LATEST values without forcing a callback recreation per render.
  // This eliminates the stale-closure bug AND the perf cost of recreating on
  // every message append.
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;
  const activeModelRef = useRef(activeModel);
  activeModelRef.current = activeModel;
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  // ── Envoi d'un message ────────────────────────────────────────────────────
  const sendMessage = useCallback(async ({ text, images }) => {
    if (!text?.trim() && (!images || images.length === 0)) return;

    const textContent = text?.trim() || '';
    const imageList = images || [];

    // 1. Ajouter le message utilisateur à l'état local
    const userMsg = {
      id: genId(),
      role: 'user',
      content: textContent,
      parts: [{ type: 'text', text: textContent }],
      images: imageList.map(img => img.data),  // base64 data URLs for display
    };

    // 2. Préparer le message assistant placeholder
    const assistantId = genId();
    const assistantMsg = {
      id: assistantId,
      role: 'assistant',
      content: '',
      parts: [],
      toolInvocations: [],
    };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setStatus('submitted');
    setError(null);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // 3. Construire la liste de messages à envoyer (historique + nouveau message user)
      // Use the LATEST messages from the ref (not the closure-captured value) to
      // avoid sending a stale snapshot if the state updated between deps capture.
      const allMessages = [...messagesRef.current, userMsg];

      const requestPayload = {
          messages: allMessages.map(m => {
            const msgText = extractText(m);
            // Construire le contenu multimodal si le message a des images
            let content;
            if (m.role === 'user' && m.images && m.images.length > 0) {
              // Format multimodal pour Ollama vision
              content = [
                { type: 'text', text: msgText },
                ...m.images.map(dataUrl => ({ type: 'image_url', image_url: { url: dataUrl } })),
              ];
            } else {
              content = msgText;
            }
            return {
              role: m.role,
              content,
              // Réinjecter les tool_calls pour les messages assistant déjà traités
              ...(m.toolInvocations?.length > 0 && m.role === 'assistant' ? {
                tool_calls: m.toolInvocations.map(inv => ({
                  toolName: inv.toolName,
                  args: inv.args,
                }))
              } : {}),
            };
          }),
          // Read conversationId from ref so it picks up updates from `conv_id` SSE event
          conversationId: conversationIdRef.current || null,
          requestId: userMsg.id,
          model: activeModelRef.current || null,
        };
      setStatus('streaming');
      for await (const event of durableChatEvents({
        url: `${BACKEND_URL}/api/chat`, payload: requestPayload, signal: controller.signal,
      })) {
          switch (event.type) {
            // ── Nouvelle conversation créée ─────────────────────────────────
            case 'conv_id':
              if (event.conversationId) {
                onConversationCreatedRef.current?.(event.conversationId);
              }
              break;

            // ── Modèle sélectionné (auto-routing) ──────────────────────────
            case 'model_info':
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                return {
                  ...m,
                  modelInfo: {
                    profile: event.profile,
                    model:   event.model,
                    label:   event.label,
                    provider: event.provider,
                    privacyMode: event.privacyMode,
                    privacyPreset: event.privacyPreset,
                    cloudPreferred: Boolean(event.cloudPreferred),
                    cloudOnly: Boolean(event.cloudOnly),
                    degraded: Boolean(event.degraded),
                    continuityState: event.continuityState,
                    switchReason: event.switchReason,
                    sensitive: Boolean(event.sensitive),
                  },
                };
              }));
              break;

            // ── Texte streamé ───────────────────────────────────────────────
            case 'text':
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                const newContent = (m.content || '') + event.text;
                const textParts = m.parts.filter(p => p.type !== 'text');
                const toolParts = m.parts.filter(p => p.type === 'tool-invocation');
                return {
                  ...m,
                  content: newContent,
                  parts: [
                    { type: 'text', text: newContent },
                    ...toolParts,
                  ],
                };
              }));
              break;

            // ── Début d'appel d'outil ───────────────────────────────────────
            case 'tool_start': {
              const inv = {
                state: 'call',
                toolCallId: event.toolCallId,
                toolName: event.toolName,
                args: event.args || {},
              };
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                return {
                  ...m,
                  parts: [
                    ...m.parts,
                    { type: 'tool-invocation', toolInvocation: inv },
                  ],
                  toolInvocations: [...(m.toolInvocations || []), inv],
                };
              }));
              break;
            }

            // ── Fin d'appel d'outil ─────────────────────────────────────────
            case 'tool_end':
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                const updatedParts = m.parts.map(p => {
                  if (p.type === 'tool-invocation' && p.toolInvocation?.toolCallId === event.toolCallId) {
                    return {
                      ...p,
                      toolInvocation: {
                        ...p.toolInvocation,
                        state: 'result',
                        result: event.result,
                        evidence: event.evidence,
                      },
                    };
                  }
                  return p;
                });
                const updatedInvocations = (m.toolInvocations || []).map(inv =>
                  inv.toolCallId === event.toolCallId
                    ? { ...inv, state: 'result', result: event.result, evidence: event.evidence }
                    : inv
                );
                return { ...m, parts: updatedParts, toolInvocations: updatedInvocations };
              }));
              break;

            // ── Fin du stream ───────────────────────────────────────────────
            case 'done':
              setStatus('ready');
              onStreamFinishRef.current?.();
              break;

            // ── Erreur ──────────────────────────────────────────────────────
            case 'error':
              setError(new Error(event.message || 'Erreur inconnue'));
              setStatus('error');
              // Supprimer le message assistant vide en cas d'erreur grave
              if (!event.message?.includes('Ollama')) {
                setMessages(prev => prev.filter(m => m.id !== assistantId || m.content));
              }
              break;
          }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('[useSecretary] Erreur streaming:', err);
        setError(err);
        setStatus('error');
      } else {
        setStatus('ready');
      }
    }

    setStatus(s => s === 'streaming' || s === 'submitted' ? 'ready' : s);
  }, []);  // No deps — uses refs for all dynamic values to avoid stale closures

  // ── Résultat d'outil confirmé (depuis handleConfirmTool) ──────────────────
  const addToolResult = useCallback(({ toolCallId, result }) => {
    setMessages(prev => prev.map(m => {
      if (m.role !== 'assistant') return m;
      const updatedParts = (m.parts || []).map(p => {
        if (p.type === 'tool-invocation' && p.toolInvocation?.toolCallId === toolCallId) {
          return {
            ...p,
            toolInvocation: { ...p.toolInvocation, state: 'result', result },
          };
        }
        return p;
      });
      const updatedInvocations = (m.toolInvocations || []).map(inv =>
        inv.toolCallId === toolCallId ? { ...inv, state: 'result', result } : inv
      );
      return { ...m, parts: updatedParts, toolInvocations: updatedInvocations };
    }));
  }, []);

  // ── Arrêt du stream ───────────────────────────────────────────────────────
  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStatus('ready');
  }, []);

  // ── Cleanup: abort any ongoing stream when the hook unmounts ──────────────
  // Prevents memory leaks and orphan SSE connections when user navigates away
  // mid-stream.
  useEffect(() => {
    return () => {
      try { abortRef.current?.abort(); } catch { /* ignore */ }
    };
  }, []);

  const isLoading = status === 'submitted' || status === 'streaming';

  return { messages, status, isLoading, error, sendMessage, setMessages, addToolResult, stop };
}
