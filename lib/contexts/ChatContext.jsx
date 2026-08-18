'use client';
/**
 * ChatContext — Global chat state mounted at the layout level.
 *
 * WHY: Previously chat state lived in ChatContainer. When the user navigated
 * to another page (Outils, Fichiers, etc.), ChatContainer unmounted and the
 * SSE stream was aborted → the conversation in progress got cut.
 *
 * This provider lives in app/layout.js so it persists across page navigations.
 * The ChatContainer becomes a thin "view" that just reads from this context.
 *
 * Public API (via useChat()):
 *   - messages, status, error, isLoading
 *   - conversationId, setConversationId
 *   - initialMessages, setInitialMessages
 *   - activeModel, setActiveModel
 *   - sendMessage({ text, images })
 *   - addToolResult({ toolCallId, result })
 *   - stop()
 *   - setMessages(updaterOrValue)
 *
 * For navigation indicator (sidebar badge):
 *   - useChatStatus() → { isLoading, status, hasActiveStream }
 */
import { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import { useVoice } from '@/lib/hooks/useVoice';
import { BACKEND_URL } from '@/lib/backend';
import { DEFAULT_CORTEX_CONTRACT, resetOneShot } from '@/lib/cortex';
import { ChatStreamTransportError, durableChatEvents } from '@/lib/chatStream';

const ChatContext = createContext(null);

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

export function ChatProvider({ children }) {
  // Core chat state
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState('ready');           // 'ready'|'submitted'|'streaming'|'error'
  const [error, setError] = useState(null);
  const [conversationId, setConversationId] = useState(null);
  const [initialMessages, setInitialMessages] = useState([]);
  const [activeModel, setActiveModel] = useState('auto');
  const [cortexContract, setCortexContract] = useState({ ...DEFAULT_CORTEX_CONTRACT });

  // Voice state (TTS + voice mode)
  const voice = useVoice();
  // sendMessage est un useCallback([]) → il capturerait le `voice` du 1er render
  // (voiceMode=false). On lit toujours la valeur LIVE via cette ref, sinon la
  // synthèse vocale ne se déclenche jamais (réponse écrite OK mais pas parlée).
  const voiceRef = useRef(voice);
  voiceRef.current = voice;
  // Track which message IDs have already been auto-spoken (avoid speaking
  // the same message multiple times if React re-renders during streaming)
  const spokenMessagesRef = useRef(new Set());

  // For onConversationCreated callback (called when a new conv ID is allocated)
  const conversationCreatedListenersRef = useRef([]);
  const subscribeConversationCreated = useCallback((cb) => {
    conversationCreatedListenersRef.current.push(cb);
    return () => {
      conversationCreatedListenersRef.current = conversationCreatedListenersRef.current.filter(c => c !== cb);
    };
  }, []);

  // For onStreamFinish (called when the stream completes)
  const streamFinishListenersRef = useRef([]);
  const subscribeStreamFinish = useCallback((cb) => {
    streamFinishListenersRef.current.push(cb);
    return () => {
      streamFinishListenersRef.current = streamFinishListenersRef.current.filter(c => c !== cb);
    };
  }, []);

  // Refs for live values (used by sendMessage to avoid stale closures)
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;
  const activeModelRef = useRef(activeModel);
  activeModelRef.current = activeModel;
  const cortexContractRef = useRef(cortexContract);
  cortexContractRef.current = cortexContract;
  const abortRef = useRef(null);
  // Only the newest request owns the visible streaming state. This prevents an
  // aborted request from marking a newer approval continuation as completed.
  const runGenerationRef = useRef(0);
  const activeRootRequestRef = useRef(null);
  const queuedNextDirectivesRef = useRef([]);
  const provisionalConversationKeyRef = useRef(crypto.randomUUID());
  const [directives, setDirectives] = useState([]);

  // Send a message — does NOT abort on unmount because it lives in the provider
  const sendMessage = useCallback(async ({
    text,
    images,
    cortex,
    internal = false,
    continuationApprovalId = null,
  }) => {
    if (!text?.trim() && (!images || images.length === 0)) return;

    const textContent = text?.trim() || '';
    const imageList = images || [];
    const runGeneration = ++runGenerationRef.current;
    const isCurrentRun = () => runGenerationRef.current === runGeneration;

    const missionContract = { ...DEFAULT_CORTEX_CONTRACT, ...(cortex || cortexContractRef.current) };
    const userMsg = {
      id: genId(),
      role: 'user',
      content: textContent,
      parts: [{ type: 'text', text: textContent }],
      images: imageList.map(img => img.data),
      cortexRequested: missionContract,
    };
    if (!continuationApprovalId) activeRootRequestRef.current = userMsg.id;

    const assistantId = genId();
    const assistantMsg = {
      id: assistantId,
      role: 'assistant',
      content: '',
      parts: [],
      toolInvocations: [],
    };

    setMessages(prev => internal
      ? [...prev, assistantMsg]
      : [...prev, userMsg, assistantMsg]);
    setStatus('submitted');
    setError(null);

    // Mode vocal : on lit les phrases AU FIL DE LA GÉNÉRATION (pas à la fin)
    // → Marvin commence à parler dès la 1ère phrase écrite.
    const liveVoice = voiceRef.current;   // valeur LIVE (pas la capture obsolète)
    const voiceSequence = liveVoice.voiceMode && liveVoice.beginSpeechStream
      ? liveVoice.beginSpeechStream()
      : null;
    const voiceStream = { text: '', spoken: 0, active: !!liveVoice.voiceMode, sequence: voiceSequence };

    // v2.165 — un envoi précédent encore en cours (l'utilisateur retape/renvoie le
    // même message pendant qu'une recherche web ou un outil traîne) partait en
    // PARALLÈLE du nouveau sans jamais être annulé : deux flux SSE concurrents pour
    // la même conversation se marchaient dessus côté état React (des mises à jour
    // setMessages(prev => ...) capturant un `prev` obsolète), et le contenu déjà
    // généré (ex. un script) pouvait disparaître au premier re-rendu/rechargement.
    // On coupe l'ancien flux avant d'en démarrer un nouveau — sans effet sur le
    // comportement voulu "continue en fond si on quitte la page" (ça, c'est
    // l'absence d'abort au démontage du composant, inchangé).
    abortRef.current?.abort();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const allMessages = [...messagesRef.current, userMsg];
      // Une conversation existante est reconstruite depuis SQLite par le backend.
      // Le navigateur n'envoie que le delta courant : les longues sessions ne sont
      // plus limitées par la taille du payload HTTP et SQLite reste autoritaire.
      const outboundMessages = conversationIdRef.current ? [userMsg] : allMessages;

      const requestPayload = {
          messages: outboundMessages.map(m => {
            const msgText = extractText(m);
            let content;
            if (m.role === 'user' && m.images && m.images.length > 0) {
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
              ...(m.toolInvocations?.length > 0 && m.role === 'assistant' ? {
                toolInvocations: m.toolInvocations.map(inv => ({
                  toolCallId: inv.toolCallId,
                  toolName: inv.toolName,
                  args: inv.args,
                  state: inv.state,
                  result: inv.state === 'result' ? inv.result : undefined,
                }))
              } : {}),
            };
          }),
          conversationId: conversationIdRef.current || null,
          conversationKey: conversationIdRef.current || provisionalConversationKeyRef.current,
          requestId: userMsg.id,
          rootRequestId: continuationApprovalId ? activeRootRequestRef.current : userMsg.id,
          model: activeModelRef.current || null,
          cortex: missionContract,
          continuationApprovalId: continuationApprovalId || null,
        };
      if (isCurrentRun()) setStatus('streaming');
      for await (const event of durableChatEvents({
        url: `${BACKEND_URL}/api/chat`, payload: requestPayload, signal: controller.signal,
      })) {
          switch (event.type) {
            case 'conv_id':
              if (event.conversationId) {
                setConversationId(event.conversationId);
                provisionalConversationKeyRef.current = crypto.randomUUID();
                conversationCreatedListenersRef.current.forEach(cb => {
                  try { cb(event.conversationId); } catch { /* ignore */ }
                });
              }
              break;

            case 'directive_received':
            case 'directive_deferred':
            case 'directive_applied':
            case 'directive_ready':
            case 'directive_rejected':
            case 'directive_cancelled':
              if (event.directive) {
                setDirectives(prev => {
                  const rest = prev.filter(item => item.id !== event.directive.id);
                  return [...rest, event.directive].sort((a, b) => a.sequence - b.sequence);
                });
                if (event.type === 'directive_ready') {
                  queuedNextDirectivesRef.current.push(event.directive);
                }
              }
              break;

            case 'model_info':
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                return {
                  ...m,
                  modelInfo: {
                    profile: event.profile,
                    model: event.model,
                    label: event.label,
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

            case 'cortex_contract':
              setMessages(prev => prev.map(m => m.id === assistantId ? {
                ...m,
                cortex: event.contract,
                executionGraph: [
                  { id: 'contract', label: 'Contrat compilé', status: 'done', detail: event.contract?.summary || 'Auto' },
                  { id: 'reasoning', label: 'Analyse et routage', status: 'running' },
                ],
              } : m));
              break;

            // v2.125 — certains modèles (notamment cloud) renvoient leur raisonnement dans
            // un champ SÉPARÉ de la réponse finale, avant celle-ci ou avant un appel
            // d'outil. Jusqu'ici ignoré côté backend → rien ne s'affichait pendant
            // potentiellement plusieurs minutes (jusqu'à 3min10 mesurées en réel), donnant
            // l'impression que Marvin restait bloqué à "réfléchir". MessageBubble.jsx avait
            // DÉJÀ un bloc collapsible "🧠 Réflexion..." tout construit pour les parts de
            // type 'reasoning' — jamais alimenté faute d'émission côté backend. On le
            // nourrit ici plutôt que d'inventer un nouvel affichage.
            case 'thinking':
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                const reasoningParts = m.parts.filter(p => p.type === 'reasoning');
                const otherParts = m.parts.filter(p => p.type !== 'reasoning');
                const newReasoningText = (reasoningParts[0]?.text || '') + event.text;
                return { ...m, parts: [{ type: 'reasoning', text: newReasoningText }, ...otherParts] };
              }));
              break;

            case 'text':
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                const newContent = (m.content || '') + event.text;
                // v2.125 fix — ne gardait que les parts 'tool-invocation', ce qui effaçait
                // silencieusement le bloc 'reasoning' (thinking) dès l'arrivée du premier
                // token de texte final. Préserve maintenant aussi le raisonnement déjà streamé.
                const keptParts = m.parts.filter(p => p.type === 'tool-invocation' || p.type === 'reasoning');
                return {
                  ...m,
                  content: newContent,
                  parts: [
                    { type: 'text', text: newContent },
                    ...keptParts,
                  ],
                };
              }));
              // Vocal en streaming : lit chaque phrase complète dès qu'elle arrive
              if (voiceStream.active && liveVoice.enqueueSpeech) {
                voiceStream.text += event.text;
                const rest = voiceStream.text.slice(voiceStream.spoken);
                const m = rest.match(/^[\s\S]*[.!?…\n]/);   // jusqu'à la dernière fin de phrase
                if (m && m[0].replace(/[\s*#`>_-]/g, '').length > 1) {
                  liveVoice.enqueueSpeech(m[0], voiceStream.sequence);
                  voiceStream.spoken += m[0].length;
                }
              }
              break;

            case 'answer_final':
              // Certains modèles Cloud livrent toute la réponse dans answer_final sans
              // émettre de fragments `text`. Le rendu React est asynchrone : l'événement
              // `done` suivant ne peut donc pas compter sur messagesRef pour retrouver
              // immédiatement ce texte. Conserver aussi la réponse dans le tampon vocal
              // garantit sa lecture, sans doubler les fragments déjà prononcés.
              if (voiceStream.active && event.text) {
                voiceStream.text = event.text;
              }
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                const finalText = event.text || '';
                const keptParts = m.parts.filter(
                  p => p.type === 'tool-invocation' || p.type === 'reasoning'
                );
                return {
                  ...m,
                  content: finalText,
                  parts: [
                    { type: 'text', text: finalText },
                    ...keptParts,
                  ],
                };
              }));
              break;

            case 'tool_start': {
              // v2.148 — horodatage de départ, utilisé par ToolCallInline pour afficher un
              // chrono en direct sur les outils lents (recherche approfondie, panel
              // d'experts, tâche longue...) — sans ça, la carte reste sur "⟳ Exécution..."
              // plusieurs minutes sans aucun repère de temps, symptôme déjà documenté
              // (v2.125/v2.136 — impression que Marvin reste bloqué).
              const inv = {
                state: 'call',
                toolCallId: event.toolCallId,
                toolName: event.toolName,
                args: event.args || {},
                startedAt: Date.now(),
              };
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                const graph = [...(m.executionGraph || [])].map(n => n.id === 'reasoning' ? { ...n, status: 'done' } : n);
                graph.push({ id: event.toolCallId, label: event.toolName, status: 'running', kind: 'tool' });
                return {
                  ...m,
                  parts: [...m.parts, { type: 'tool-invocation', toolInvocation: inv }],
                  toolInvocations: [...(m.toolInvocations || []), inv],
                  executionGraph: graph,
                };
              }));
              break;
            }

            case 'tool_progress':
              setMessages(prev => prev.map(m => {
                if (m.id !== assistantId) return m;
                const progress = {
                  ...(event.progress || {}),
                  receivedAt: Date.now(),
                };
                const updateInvocation = inv => (
                  inv.toolCallId === event.toolCallId
                    ? {
                        ...inv,
                        progress,
                        progressEvents: [...(inv.progressEvents || []), progress].slice(-24),
                      }
                    : inv
                );
                return {
                  ...m,
                  parts: m.parts.map(part => (
                    part.type === 'tool-invocation'
                    && part.toolInvocation?.toolCallId === event.toolCallId
                      ? { ...part, toolInvocation: updateInvocation(part.toolInvocation) }
                      : part
                  )),
                  toolInvocations: (m.toolInvocations || []).map(updateInvocation),
                  executionGraph: (m.executionGraph || []).map(node => (
                    node.id === event.toolCallId
                      ? { ...node, detail: progress.label, progress }
                      : node
                  )),
                };
              }));
              break;

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
                return { ...m, parts: updatedParts, toolInvocations: updatedInvocations,
                  executionGraph: (m.executionGraph || []).map(n => n.id === event.toolCallId ? { ...n, status: 'done' } : n) };
              }));
              break;

            case 'cortex_provenance':
              setMessages(prev => prev.map(m => m.id === assistantId ? {
                ...m,
                cortexProvenance: event.provenance,
                executionGraph: [
                  ...(m.executionGraph || []).map(n => ({ ...n, status: n.status === 'running' ? 'done' : n.status })),
                  { id: 'delivered', label: 'Réponse vérifiée et livrée', status: 'done', kind: 'output' },
                ],
              } : m));
              break;

            case 'done':
              if (isCurrentRun()) setStatus('ready');
              // Mode vocal : on a déjà lu les phrases au fil de l'eau. Il ne reste
              // qu'à lire la « queue » non terminée par un point (dernier fragment).
              if (voiceStream.active && !spokenMessagesRef.current.has(assistantId)) {
                spokenMessagesRef.current.add(assistantId);
                const finalMsg = messagesRef.current.find(m => m.id === assistantId);
                const full = finalMsg?.content || voiceStream.text || '';
                const tail = full.slice(voiceStream.spoken).trim();
                if (tail && tail.replace(/[\s*#`>_-]/g, '').length > 1 && liveVoice.enqueueSpeech) {
                  liveVoice.enqueueSpeech(tail, voiceStream.sequence);
                } else if (voiceStream.spoken === 0 && full.trim() && liveVoice.speak) {
                  // fallback : rien n'a été lu (réponse sans ponctuation) → lit tout
                  liveVoice.speak(full).catch(() => {});
                }
              }
              streamFinishListenersRef.current.forEach(cb => {
                try { cb(); } catch { /* ignore */ }
              });
              if (isCurrentRun() && queuedNextDirectivesRef.current.length > 0) {
                const queued = queuedNextDirectivesRef.current.splice(0);
                queueMicrotask(async () => {
                  for (const directive of queued) {
                    await sendMessage({ text: directive.text });
                  }
                });
              }
              break;

            case 'error':
              if (isCurrentRun()) {
                setError(new Error(
                  event.message ||
                  event.detail ||
                  event.error ||
                  'Erreur backend inconnue (le modèle a peut-être renvoyé une réponse invalide)'
                ));
                setStatus('error');
              }
              if (!event.message?.includes('Ollama')) {
                setMessages(prev => prev.filter(m => m.id !== assistantId || m.content));
              }
              break;
          }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        // Une coupure réseau bornée est déjà rendue dans l'interface. En développement,
        // console.error déclenche l'overlay Turbopack et masque ce message exploitable.
        if (err instanceof ChatStreamTransportError) {
          console.warn('[ChatContext] Transport du chat indisponible après reconnexion bornée.');
        } else {
          console.error('[ChatContext] Erreur streaming:', err);
        }
        // Give a meaningful error message even when err.message is empty
        const msg = err.message
          || err.toString()
          || `Erreur réseau ou backend (${err.name || 'inconnu'})`;
        if (isCurrentRun()) {
          setError(new Error(msg));
          setStatus('error');
        }
      } else if (isCurrentRun()) {
        setStatus('ready');
      }
    }

    if (isCurrentRun()) {
      abortRef.current = null;
      setStatus(s => s === 'streaming' || s === 'submitted' ? 'ready' : s);
      setCortexContract(prev => resetOneShot(prev));
    }
  }, []);

  const addToolResult = useCallback(({ toolCallId, result }) => {
    const updatedMessages = messagesRef.current.map(m => {
      if (m.role !== 'assistant') return m;
      const updatedParts = (m.parts || []).map(p => {
        if (p.type === 'tool-invocation' && p.toolInvocation?.toolCallId === toolCallId) {
          return { ...p, toolInvocation: { ...p.toolInvocation, state: 'result', result } };
        }
        return p;
      });
      const updatedInvocations = (m.toolInvocations || []).map(inv =>
        inv.toolCallId === toolCallId ? { ...inv, state: 'result', result } : inv
      );
      return { ...m, parts: updatedParts, toolInvocations: updatedInvocations };
    });
    // La continuation peut démarrer dans le même tick que le clic d'approbation.
    // La ref doit donc recevoir le résultat avant le prochain rendu React, sinon
    // Ollama verrait un tool_call sans message tool correspondant.
    messagesRef.current = updatedMessages;
    setMessages(updatedMessages);
  }, []);

  const sendDirective = useCallback(async ({ text = '', kind = 'append' }) => {
    const rootRequestId = activeRootRequestRef.current;
    if (!rootRequestId) throw new Error('Aucun tour actif à orienter.');
    const response = await fetch(
      `${BACKEND_URL}/api/chat/turns/${encodeURIComponent(rootRequestId)}/directives`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clientDirectiveId: crypto.randomUUID(), kind, text }),
      },
    );
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Orientation refusée.');
    setDirectives(prev => [...prev.filter(item => item.id !== payload.directive.id), payload.directive]);
    return payload.directive;
  }, []);

  const stop = useCallback(() => {
    if (activeRootRequestRef.current && (status === 'submitted' || status === 'streaming')) {
      sendDirective({ kind: 'stop', text: '' })
        .then(() => setDirectives(prev => [...prev, {
          id: `local-stop-${Date.now()}`,
          sequence: Math.max(0, ...prev.map(item => item.sequence || 0)) + 1,
          kind: 'stop',
          status: 'deferred',
          waitingFor: { kind: 'current_action_completion' },
          reasonCode: 'cooperative_stop_requested',
        }]))
        .catch(err => setError(err));
      return;
    }
    runGenerationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus('ready');
  }, [sendDirective, status]);

  const isLoading = status === 'submitted' || status === 'streaming';

  const value = {
    // State
    messages, setMessages,
    status, error, isLoading, directives,
    conversationId, setConversationId,
    initialMessages, setInitialMessages,
    activeModel, setActiveModel,
    cortexContract, setCortexContract,
    // Actions
    sendMessage,
    sendDirective,
    addToolResult,
    stop,
    // Subscriptions
    subscribeConversationCreated,
    subscribeStreamFinish,
    // Voice (TTS + voice mode)
    voice,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) {
    throw new Error('useChat must be used within a ChatProvider (wrap your layout with <ChatProvider>)');
  }
  return ctx;
}

/** Variante optionnelle pour les composants également rendus dans des tests isolés. */
export function useOptionalChat() {
  return useContext(ChatContext);
}

/** Lightweight subscription for sidebar/indicator components that only need status */
export function useChatStatus() {
  const ctx = useContext(ChatContext);
  return {
    isLoading: ctx?.isLoading ?? false,
    status: ctx?.status ?? 'ready',
    conversationId: ctx?.conversationId ?? null,
    messageCount: ctx?.messages?.length ?? 0,
  };
}
