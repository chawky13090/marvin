'use client';
import { useState, useMemo, useEffect, useRef } from 'react';
import styles from './MessageBubble.module.css';
import SpeakButton from './SpeakButton';
import CortexTrace from './CortexTrace';
import CodingMissionTracker from './CodingMissionTracker';
import SourceGallery, { collectWebSources } from './SourceGallery';
import { BACKEND_URL } from '@/lib/backend';
import { renderToolResult } from './ToolResultContent';
import { renderSafeMarkdown } from '@/lib/chat/markdown';

export default function MessageBubble({ message, conversationId, viewMode = 'reading', showMissionTracker = true, onConfirmTool, onCancelTool, onRetryTool }) {
  const isUser = message.role === 'user';
  const isToolResult = message.role === 'tool';
  const [showReasoning, setShowReasoning] = useState(false);
  const [stepsCollapsed, setStepsCollapsed] = useState(viewMode === 'reading');
  useEffect(() => setStepsCollapsed(viewMode === 'reading'), [viewMode]);

  // Extraire le texte depuis parts (v6) ou content (fallback)
  const textParts = message.parts?.filter(p => p.type === 'text') || [];
  const textContent = textParts.length > 0
    ? textParts.map(p => p.text).join('')
    : (typeof message.content === 'string' ? message.content : '');

  // Images jointes au message utilisateur
  const imageParts = message.images || [];
  // Détecter les images encodées dans le contenu (format data: URL)
  const inlineImages = Array.isArray(message.content)
    ? message.content.filter(c => c.type === 'image_url').map(c => c.image_url?.url || c.url)
    : [];

  // Raisonnement (modèles avec thinking)
  const reasoningContent = message.parts
    ? message.parts.filter(p => p.type === 'reasoning').map(p => p.text || p.reasoning).join('')
    : '';

  // Tool invocations : SDK v6 les expose via parts (type 'tool-invocation')
  // ET via message.toolInvocations pour compatibilité
  const toolInvocationsFromParts = message.parts
    ?.filter(p => p.type === 'tool-invocation')
    .map(p => p.toolInvocation) || [];
  const toolInvocations = (message.toolInvocations && message.toolInvocations.length > 0)
    ? message.toolInvocations
    : toolInvocationsFromParts;
  const webSources = useMemo(() => collectWebSources(toolInvocations), [toolInvocations]);

  const htmlContent = useMemo(() => renderSafeMarkdown(textContent), [textContent]);

  // Bloc de raisonnement (collapsible, fermé par défaut)
  const reasoningBlock = reasoningContent ? (
    <div style={{
      alignSelf: 'flex-start',
      width: 'fit-content',
      maxWidth: '85%',
      marginLeft: '40px',
      background: 'rgba(139, 92, 246, 0.05)',
      backdropFilter: 'blur(20px)',
      border: '1px dashed rgba(139, 92, 246, 0.25)',
      borderLeft: '3px solid var(--accent-primary)',
      borderRadius: '8px',
      fontSize: 'var(--font-xs)',
      color: 'var(--text-secondary)',
      overflow: 'hidden',
      animation: 'slideUp 0.3s ease',
      marginBottom: '4px'
    }}>
      <div
        onClick={() => setShowReasoning(!showReasoning)}
        style={{
          display: 'flex', alignItems: 'center', gap: '24px',
          padding: '8px 12px', cursor: 'pointer', userSelect: 'none',
          background: 'rgba(255, 255, 255, 0.02)', fontWeight: 600,
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>🧠</span>
          <span>Réflexion...</span>
        </span>
        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
          {showReasoning ? '▲ Masquer' : '▼ Afficher'}
        </span>
      </div>
      {showReasoning && (
        <div style={{
          padding: '10px 12px',
          borderTop: '1px solid rgba(139, 92, 246, 0.1)',
          whiteSpace: 'pre-wrap', fontStyle: 'italic', lineHeight: 1.5,
          maxHeight: '200px', overflowY: 'auto', color: 'var(--text-secondary)'
        }}>
          {reasoningContent}
        </div>
      )}
    </div>
  ) : null;

  const provenanceLabel = message.modelInfo?.privacyMode === 'ultra_local_continuity'
    ? 'Ultra · continuité locale'
    : message.modelInfo?.privacyMode === 'ultra_cloud'
    ? 'Cloud prioritaire'
    : message.modelInfo?.privacyMode === 'hyper_local'
      ? 'Local protégé'
      : message.modelInfo?.privacyMode === 'sensitive_local'
        ? 'Local · contenu sensible'
        : message.modelInfo?.provider === 'ollama_cloud'
          ? 'Ollama Cloud'
          : message.modelInfo?.provider === 'ollama_local'
            ? 'Ollama local'
            : null;

  // Badge modèle et provenance (affiché sous les réponses de l'assistant)
  const modelBadge = !isUser && message.modelInfo ? (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: '5px',
      marginLeft: '44px', marginTop: '2px',
      fontSize: '10px', color: 'var(--text-muted)', opacity: 0.65,
      letterSpacing: '0.04em',
    }}>
      <span>{message.modelInfo.label}</span>
      <span style={{ opacity: 0.5 }}>·</span>
      <span style={{ fontFamily: 'monospace', fontSize: '9px' }}>{message.modelInfo.model}</span>
      {provenanceLabel && (
        <>
          <span style={{ opacity: 0.5 }}>·</span>
          <span>{provenanceLabel}</span>
        </>
      )}
    </div>
  ) : null;

  // Messages avec tool invocations
  if (toolInvocations.length > 0) {
    const turnMode = detectTurnMode(toolInvocations, message.modelInfo);
    const finishedCount = toolInvocations.filter((tool) => {
      const state = tool.state || (tool.result !== undefined ? 'result' : 'pending');
      return state === 'result' || state === 'error';
    }).length;
    const errorTools = toolInvocations.filter(t => toolHasFailed(t));
    const codingMissionTool = [...toolInvocations].reverse().find((tool) => (
      ['code_workspace_start', 'code_workspace_status', 'code_workspace_control'].includes(tool.toolName)
      && tool.result !== undefined
    ));
    // v2.244 — toute activité terminée se replie en résumé, même avec un seul outil.
    // Une confirmation critique reste toujours ouverte afin de ne masquer aucune décision.
    const anyNeedsAttention = toolInvocations.some(toolNeedsAttention);
    const shouldCollapse = !anyNeedsAttention && finishedCount === toolInvocations.length;
    const showToolDetails = anyNeedsAttention || (
      viewMode !== 'reading' && (!shouldCollapse || !stepsCollapsed)
    );
    return (
      <div className={`${styles.wrapper} ${styles.wrapperAssistant}`} style={{ flexDirection: 'column', gap: '8px', opacity: 1, maxWidth: '100%' }}>
        <TurnModeBadge mode={turnMode} />
        {reasoningBlock}
        {textContent && (
          <BubbleWrapper isUser={false}>
            <ReadableContent html={htmlContent} text={textContent} viewMode={viewMode} />
          </BubbleWrapper>
        )}
        <SourceGallery sources={webSources} />
        <div className={styles.responseMetaRow}>
          {shouldCollapse && viewMode === 'reading' && (
            <div className={`${styles.activityToggle} ${styles.activityStatic}`}>
              <span aria-hidden="true">{errorTools.length > 0 ? '!' : '✓'}</span>
              <span>
                {toolInvocations.length} action{toolInvocations.length > 1 ? 's' : ''}
                {errorTools.length > 0
                  ? ` · ${errorTools.length} en erreur`
                  : ` · terminée${toolInvocations.length > 1 ? 's' : ''}`}
              </span>
              <span className={styles.activityToggleAction}>Détails en mode Technique</span>
            </div>
          )}
          {shouldCollapse && viewMode !== 'reading' && (
            <button
              type="button"
              className={styles.activityToggle}
              onClick={() => setStepsCollapsed(!stepsCollapsed)}
              aria-expanded={!stepsCollapsed}
            >
              <span aria-hidden="true">{errorTools.length > 0 ? '!' : '✓'}</span>
              <span>
                {toolInvocations.length} action{toolInvocations.length > 1 ? 's' : ''}
                {errorTools.length > 0
                  ? ` · ${errorTools.length} en erreur`
                  : ` · terminée${toolInvocations.length > 1 ? 's' : ''}`}
              </span>
              {errorTools.length > 0 && stepsCollapsed && (
                <span className={styles.activityError}>{summarizeToolResult(errorTools[0].toolName, errorTools[0].result)}</span>
              )}
              <span className={styles.activityToggleAction}>{stepsCollapsed ? 'Détails' : 'Masquer'}</span>
            </button>
          )}
          <CortexTrace message={message} compact />
        </div>
        {viewMode === 'reading' && toolInvocations.some((tool) => tool.detailRef) && (
          <div style={{ marginLeft: 40, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {toolInvocations.filter((tool) => tool.detailRef).map((tool) => (
              <ToolDetailControl key={tool.toolCallId} tool={tool} conversationId={conversationId} compact />
            ))}
          </div>
        )}
        {codingMissionTool && showMissionTracker && (
          <div style={{ marginLeft: '40px', width: 'calc(100% - 40px)' }}>
            <CodingMissionTracker result={codingMissionTool.result} />
          </div>
        )}
        {showToolDetails && (
          <div className={styles.toolCalls}>
            {toolInvocations.map((tool, i) => (
              <ToolCallInline
                key={tool.toolCallId || i}
                tool={tool}
                conversationId={conversationId}
                viewMode={viewMode}
                onConfirm={onConfirmTool}
                onCancel={onCancelTool}
                onRetry={onRetryTool}
                showMissionTracker={false}
              />
            ))}
          </div>
        )}
        {modelBadge}
      </div>
    );
  }

  if (isToolResult) return null;

  const allImages = [...imageParts, ...inlineImages];

  return (
    <div className={`${styles.wrapper} ${isUser ? styles.wrapperUser : styles.wrapperAssistant}`} style={{ flexDirection: 'column', gap: '8px', opacity: 1, maxWidth: '100%' }}>
      {!isUser && reasoningBlock}
      {/* Images attachées (messages utilisateur) */}
      {isUser && allImages.length > 0 && (
        <div className={`${styles.wrapper} ${styles.wrapperUser}`} style={{ opacity: 1 }}>
          <div className={`${styles.bubble} ${styles.bubbleUser}`} style={{ padding: '8px', background: 'transparent', border: 'none' }}>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {allImages.map((src, idx) => (
                <img
                  key={idx}
                  src={src}
                  alt={`Image ${idx + 1}`}
                  style={{
                    maxWidth: '240px', maxHeight: '180px', borderRadius: '10px',
                    border: '1px solid var(--border-hover)', objectFit: 'cover',
                    cursor: 'pointer',
                  }}
                  onClick={() => window.open(src, '_blank')}
                />
              ))}
            </div>
          </div>
          <div className={`${styles.avatar} ${styles.avatarUser}`}>👤</div>
        </div>
      )}
      {(textContent || (isUser && allImages.length === 0)) && (
        <BubbleWrapper isUser={isUser}>
          <div style={{ position: 'relative', width: '100%' }}>
            {isUser
              ? <div className={styles.content} dangerouslySetInnerHTML={{ __html: htmlContent }} />
              : <ReadableContent html={htmlContent} text={textContent} viewMode={viewMode} />}
            {/* Speak button — only on assistant messages with text */}
            {!isUser && textContent && (
              <div style={{
                display: 'flex', gap: '6px', alignItems: 'center',
                marginTop: '6px', paddingTop: '6px',
                borderTop: '1px solid rgba(255,255,255,0.05)',
              }}>
                <SpeakButton text={textContent} compact />
                <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  Écouter la réponse
                </span>
              </div>
            )}
          </div>
        </BubbleWrapper>
      )}
      {/* Images dans les réponses de l'assistant (infographies, screenshots) */}
      {!isUser && message.resultImages && message.resultImages.map((src, idx) => (
        <BubbleWrapper key={idx} isUser={false}>
          <img
            src={src}
            alt={`Résultat ${idx + 1}`}
            style={{ maxWidth: '100%', borderRadius: '8px', cursor: 'pointer' }}
            onClick={() => window.open(src, '_blank')}
          />
        </BubbleWrapper>
      ))}
      {modelBadge}
      {!isUser && <CortexTrace message={message} />}
    </div>
  );
}

function BubbleWrapper({ isUser, children }) {
  return (
    <div className={`${styles.wrapper} ${isUser ? styles.wrapperUser : styles.wrapperAssistant}`} style={{ opacity: 1 }}>
      <div className={`${styles.avatar} ${isUser ? styles.avatarUser : styles.avatarAssistant}`}
        style={!isUser ? {
          background: '#111',
          border: '1px solid var(--border-hover)',
          overflow: 'hidden',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        } : {}}>
        {isUser ? '👤' : (
          <img src="/marvin-logo.svg" alt="Marvin" style={{ width: '80%', height: '80%', objectFit: 'contain' }} />
        )}
      </div>
      <div className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleAssistant}`}>
        {children}
      </div>
    </div>
  );
}

function ReadableContent({ html, text, viewMode }) {
  const isLong = text.length > 2400 || text.split('\n').length > 45;
  const [expanded, setExpanded] = useState(viewMode !== 'reading');
  useEffect(() => setExpanded(viewMode !== 'reading'), [viewMode]);

  return (
    <div className={styles.readableResponse}>
      <div
        className={`${styles.content} ${isLong && !expanded ? styles.contentCollapsed : ''}`}
        dangerouslySetInnerHTML={{ __html: html }}
      />
      {isLong && (
        <button
          type="button"
          className={styles.readMoreButton}
          onClick={() => setExpanded((current) => !current)}
          aria-expanded={expanded}
        >
          {expanded ? 'Réduire la réponse' : 'Lire la réponse complète'}
        </button>
      )}
    </div>
  );
}

// ─── Outils critiques nécessitant confirmation ───
const CRITICAL_TOOLS = [
  'file_delete', 'file_rename', 'file_move', 'file_write', 'file_organize',
  'file_create_docx', 'file_convert_docx_to_pdf',
  'email_send', 'email_reply',
  'calendar_create_event', 'calendar_update_event', 'calendar_delete_event',
  'pc_open_file', 'pc_run_command', 'pc_process_kill', 'pc_pull_ollama_model',
  'project_delete'
];

// v2.146 — Bandeau de MODE en tête de réponse : demandé explicitement (« que l'on sache
// que Marvin selon nos requêtes travaille d'une certaine manière précise »). Jusqu'ici
// tous les tours (réponse rapide, agent à outils, recherche approfondie, panel d'experts,
// sous-tâches parallèles, tâche longue, Code Interpreter) rendaient EXACTEMENT la même
// bulle générique — invisible à l'œil nu qu'un mode différent était utilisé. Inspiré du
// pattern Perplexity Pro Search (bandeau d'étapes en langage clair, priorité à la
// réponse) : détecté par le nom d'outil appelé, pas de changement backend nécessaire.
const SPECIAL_MODES = [
  { match: 'web_deep_research', icon: '🔍', label: 'Recherche approfondie', color: '#0ea5e9' },
  { match: 'ai_model_council', icon: '🧑‍🤝‍🧑', label: "Panel d'experts IA", color: '#a855f7' },
  { match: 'ai_research_swarm', icon: 'R', label: 'Research Swarm', color: '#14b8a6' },
  { match: 'ai_adaptive_team', icon: 'A', label: 'Équipe adaptative', color: '#a78bfa' },
  { match: 'ai_code_forge', icon: 'C', label: 'Code Forge', color: '#22c55e' },
  { match: 'ai_test_forge', icon: 'T', label: 'Test Forge', color: '#06b6d4' },
  { match: 'ai_subagents_run', icon: '🧩', label: 'Sous-tâches parallèles', color: '#f59e0b' },
  { match: 'long_task_start', icon: '🗂️', label: 'Tâche longue démarrée', color: '#10b981' },
  { match: 'code_python', icon: '🐍', label: 'Code Interpreter', color: '#3b82f6' },
  { match: 'webapp_create', icon: '🌐', label: 'Mini-appli web', color: '#3b82f6' },
];

function detectTurnMode(toolInvocations, modelInfo) {
  for (const mode of SPECIAL_MODES) {
    if (toolInvocations.some(t => t.toolName === mode.match)) return mode;
  }
  if (modelInfo?.label && modelInfo.label.includes('Compétence')) {
    return { icon: '🧠', label: modelInfo.label.replace(/^🛠️\s*/, ''), color: '#8b5cf6' };
  }
  if (toolInvocations.length > 0) {
    return { icon: '🛠️', label: 'Agent (outils)', color: 'var(--accent-primary)' };
  }
  return null;
}

// v2.148 — trouvé en auditant le repli d'étapes (v2.146) : un outil CRITIQUE en attente de
// confirmation (ex. supprimer un fichier, envoyer un email) pouvait se retrouver caché
// derrière "▼ Afficher" si le tour comptait 3 outils ou plus — une confirmation d'action
// potentiellement dangereuse ne doit JAMAIS être masquée par défaut. Extrait en fonction
// autonome (réutilisée par ToolCallInline ET par le calcul du repli) pour ne dupliquer
// cette logique de détection nulle part.
function toolNeedsAttention(tool) {
  const state = tool.state || (tool.result !== undefined ? 'result' : 'pending');
  if (state === 'result' && tool.result) {
    const resObj = unwrapToolResult(tool.result);
    return !!(resObj && resObj.requiresConfirmation);
  }
  return false;
}

function unwrapToolResult(result) {
  let value = result;
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch { return value; }
  }
  if (value && typeof value === 'object' && value.type === 'json' && value.value !== undefined) {
    return value.value;
  }
  return value;
}

function compactText(value, maxLength = 180) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function toolHasFailed(tool) {
  if (!tool) return false;
  if (tool.state === 'error') return true;
  const result = unwrapToolResult(tool.result);
  return !!(result && typeof result === 'object'
    && (result.success === false || result.ok === false || result.error));
}

function toolAccessIsLimited(tool) {
  const result = unwrapToolResult(tool?.result);
  return !!(result && typeof result === 'object' && result.access_limited === true);
}

function summarizeToolResult(toolName = '', rawResult) {
  const result = unwrapToolResult(rawResult);
  if (typeof result === 'string') return compactText(result) || 'Résultat disponible';
  if (!result || typeof result !== 'object') return 'Résultat disponible';

  const error = result.error || result.detail || (result.success === false ? result.message : '');
  if (error) return compactText(error);

  if (toolName === 'web_search' || toolName === 'web_browse' || toolName.includes('research')) {
    const sourceCount = result.sources?.length ?? result.results?.length;
    if (Number.isFinite(sourceCount)) return `${sourceCount} source${sourceCount > 1 ? 's' : ''} consultée${sourceCount > 1 ? 's' : ''}`;
  }
  if (toolName === 'ai_code_forge') {
    const score = result.final_review?.score;
    const accepted = result.accepted ?? result.success;
    return `${accepted === false ? 'Livrable refusé' : 'Livrable produit'}${score != null ? ` · note ${score}/10` : ''}`;
  }
  if (toolName === 'ai_test_forge') {
    return result.production_ready === true ? 'Validation production réussie' : 'Validation production non acquise';
  }

  const count = result.count ?? result.total ?? result.items?.length ?? result.files?.length;
  if (Number.isFinite(count)) return `${count} élément${count > 1 ? 's' : ''}`;
  return compactText(result.summary || result.message || result.status) || 'Résultat disponible';
}

function TurnModeBadge({ mode }) {
  if (!mode) return null;
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: '6px',
      marginLeft: '40px', marginBottom: '2px', width: 'fit-content',
      padding: '3px 10px', borderRadius: '999px',
      background: `color-mix(in srgb, ${mode.color} 14%, transparent)`,
      border: `1px solid color-mix(in srgb, ${mode.color} 35%, transparent)`,
      fontSize: '11px', fontWeight: 600, color: mode.color,
      letterSpacing: '0.02em',
    }}>
      <span>{mode.icon}</span>
      <span>{mode.label}</span>
    </div>
  );
}

// ─── Icônes par catégorie d'outil ───
function getToolIcon(toolName) {
  if (toolName.startsWith('project_')) return '📂';
  if (toolName.startsWith('conversation_')) return '💬';
  if (toolName.startsWith('file_')) return '📁';
  if (toolName.startsWith('email_')) return '📧';
  if (toolName.startsWith('calendar_')) return '📅';
  if (toolName.startsWith('pc_')) return '🖥️';
  if (toolName.startsWith('web_')) return '🌐';
  if (toolName.startsWith('google_drive')) return '🔴';
  if (toolName.startsWith('onedrive')) return '🔵';
  if (toolName === 'infographic_create') return '📊';
  if (toolName.startsWith('search_')) return '🔍';
  if (toolName.startsWith('memory_')) return '🧠';
  if (toolName.startsWith('task_')) return '✅';
  if (toolName.startsWith('note_')) return '📝';
  return '🔧';
}

// v2.147 — rendus dédiés pour les 5 nouveaux outils "mode" (v2.141-145) : jusqu'ici
// retombaient sur le JSON générique malgré des résultats riches et structurés (sources,
// réponses par modèle, sous-tâches, checklist) — exactement le genre de détail que le
// bandeau de mode (v2.146) donne envie d'explorer une fois la carte dépliée.
function ToolCallInline({ tool, conversationId, viewMode, onConfirm, onCancel, onRetry, showMissionTracker = true }) {
  // v2.148 — chrono en direct pendant l'exécution (voir ChatContext.jsx::tool_start pour
  // l'horodatage `startedAt`). Hook appelé INCONDITIONNELLEMENT avant le early-return
  // `if (!tool)` ci-dessous (règle des hooks React) — la garde se fait à l'intérieur.
  const [elapsed, setElapsed] = useState(0);
  const [detailsOpen, setDetailsOpen] = useState(viewMode !== 'reading');
  useEffect(() => setDetailsOpen(viewMode !== 'reading'), [viewMode]);
  useEffect(() => {
    if (!tool || tool.state === 'result' || tool.state === 'error' || !tool.startedAt) return undefined;
    const update = () => setElapsed(Math.floor((Date.now() - tool.startedAt) / 1000));
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [tool?.startedAt, tool?.state]);

  const storedApprovalResult = tool?.state === 'result'
    ? unwrapToolResult(tool?.result)
    : null;
  const storedApprovalId = (
    storedApprovalResult
    && typeof storedApprovalResult === 'object'
    && storedApprovalResult.requiresConfirmation
  ) ? storedApprovalResult.approvalId : null;
  const [approvalState, setApprovalState] = useState(null);
  useEffect(() => {
    if (!storedApprovalId) {
      setApprovalState(null);
      return undefined;
    }
    let cancelled = false;
    let controller = null;
    const refresh = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        const response = await fetch(
          `${BACKEND_URL}/api/approvals/${encodeURIComponent(storedApprovalId)}`,
          { signal: controller.signal, cache: 'no-store' },
        );
        if (!response.ok) {
          if (!cancelled) setApprovalState({ status: 'unavailable', active: false });
          return;
        }
        const data = await response.json();
        if (!cancelled) setApprovalState(data);
      } catch (error) {
        if (!cancelled && error?.name !== 'AbortError') {
          setApprovalState({ status: 'unavailable', active: false });
        }
      }
    };
    const onApprovalChange = () => refresh();
    const onFocus = () => refresh();
    setApprovalState({ status: 'checking', active: false });
    refresh();
    window.addEventListener('marvin:approval-state-changed', onApprovalChange);
    window.addEventListener('focus', onFocus);
    const interval = window.setInterval(refresh, 15_000);
    return () => {
      cancelled = true;
      controller?.abort();
      window.clearInterval(interval);
      window.removeEventListener('marvin:approval-state-changed', onApprovalChange);
      window.removeEventListener('focus', onFocus);
    };
  }, [storedApprovalId]);

  if (!tool) return null;
  const toolName = tool.toolName || '';
  const icon = getToolIcon(toolName);
  const isCritical = CRITICAL_TOOLS.includes(toolName);
  const state = tool.state || (tool.result !== undefined ? 'result' : 'pending');
  const resultFailed = toolHasFailed(tool);
  const accessLimited = toolAccessIsLimited(tool);
  const limitedResult = accessLimited ? unwrapToolResult(tool.result) : null;
  const visualState = accessLimited ? 'limited' : resultFailed ? 'error' : state;

  const statusColors = {
    pending: 'var(--warning)',
    running: 'var(--info)',
    result: 'var(--success)',
    error: 'var(--danger)',
    limited: 'var(--warning)',
    'partial-call': 'var(--info)',
    call: 'var(--info)',
  };
  const borderColor = statusColors[visualState] || 'var(--border)';

  // Noms d'outils lisibles en français
  const toolLabels = {
    file_list: 'Lister les fichiers',
    file_search: 'Rechercher des fichiers',
    file_search_text: 'Rechercher dans les documents',
    file_info: 'Infos fichier',
    file_rename: 'Renommer',
    file_move: 'Déplacer',
    file_organize: 'Organiser les fichiers',
    file_create_folder: 'Créer un dossier',
    file_delete: 'Supprimer',
    file_read: 'Lire le fichier',
    file_write: 'Écrire un fichier',
    file_create_docx: 'Créer un document Word',
    file_convert_docx_to_pdf: 'Convertir Word → PDF',
    pc_open_file: 'Ouvrir un fichier',
    pc_run_command: 'Exécuter une commande',
    pc_system_info: 'Infos système',
    pc_clipboard_get: 'Lire le presse-papiers',
    pc_clipboard_set: 'Copier dans le presse-papiers',
    pc_process_list: 'Liste des processus',
    pc_process_kill: 'Arrêter un processus',
    computer_control: 'Contrôler le PC ou le navigateur',
    project_list: 'Lister les projets',
    project_create: 'Créer un projet Marvin',
    project_update: 'Modifier un projet Marvin',
    project_delete: 'Supprimer un projet Marvin',
    conversation_list: 'Lister les conversations',
    conversation_search: 'Rechercher des conversations',
    conversation_move: 'Déplacer une conversation',
    conversation_move_many: 'Déplacer plusieurs conversations',
    conversation_update: 'Organiser une conversation',
    pc_pull_ollama_model: 'Télécharger un modèle IA',
    email_list_inbox: 'Lister les emails',
    email_read: 'Lire un email',
    email_search: 'Rechercher des emails',
    email_send: 'Envoyer un email',
    email_reply: 'Répondre à un email',
    email_draft: 'Créer un brouillon',
    calendar_list_events: 'Lister les événements',
    calendar_create_event: 'Créer un événement',
    calendar_update_event: 'Modifier un événement',
    calendar_delete_event: 'Supprimer un événement',
    calendar_check_availability: 'Vérifier les disponibilités',
    // New tools
    web_search: 'Recherche web',
    web_browse: 'Visiter une page web',
    infographic_create: 'Créer une infographie',
    file_create_xlsx: 'Créer un tableau Excel',
    file_create_pdf: 'Créer un PDF',
    pc_screenshot: 'Capture d\'écran',
    google_drive_list: 'Google Drive — Lister',
    google_drive_read: 'Google Drive — Lire',
    google_drive_upload: 'Google Drive — Uploader',
    onedrive_list: 'OneDrive — Lister',
    onedrive_read: 'OneDrive — Lire',
    onedrive_upload: 'OneDrive — Uploader',
    // v2.146 — noms manquants trouvés en auditant le dictionnaire (repli sur le nom
    // technique brut jusqu'ici pour tous ces outils, contraire au principe "langage
    // clair" — cf. Perplexity Pro Search).
    code_python: 'Exécuter du code Python',
    webapp_create: 'Créer une mini-appli web',
    web_research: 'Recherche web approfondie',
    web_deep_research: 'Recherche approfondie multi-passes',
    ai_model_council: "Consulter un panel d'experts IA",
    ai_research_swarm: 'Lancer un essaim de recherche',
    ai_adaptive_team: 'Mobiliser une équipe adaptative',
    ai_code_forge: 'Produire un livrable code expert',
    ai_test_forge: 'Tester un livrable en environnement jetable',
    code_workspace_start: 'Démarrer une Coding Mission',
    code_workspace_status: 'Suivre une Coding Mission',
    code_workspace_control: 'Contrôler une Coding Mission',
    ai_subagents_run: 'Décomposer en sous-tâches',
    long_task_start: 'Démarrer une tâche longue',
    long_task_status: 'Vérifier une tâche longue',
    long_task_stop: 'Arrêter une tâche longue',
    document_ask: 'Interroger les documents',
    document_generate: 'Générer un document',
    document_index: 'Indexer un document',
    document_list: 'Lister les documents',
    document_refine_section: 'Affiner une section',
    memory_search: 'Chercher dans la mémoire',
    memory_save: 'Mémoriser',
    memory_list: 'Lister les souvenirs',
    task_create: 'Créer une tâche',
    task_update: 'Mettre à jour une tâche',
    task_list: 'Lister les tâches',
    ssh_list: 'Lister les connexions SSH',
    ssh_exec: 'Exécuter une commande SSH',
    ssh_exec_multi: 'Exécuter sur plusieurs serveurs',
    ssh_write_and_run: 'Écrire et lancer un script distant',
    ssh_upload: 'Envoyer un fichier (SFTP)',
    ssh_download: 'Télécharger un fichier (SFTP)',
    ssh_server_info: 'Diagnostic serveur',
    net_ping: 'Ping',
    net_port_scan: 'Scanner les ports',
    net_scan_local: 'Scanner le réseau local',
    net_dns_lookup: 'Recherche DNS',
    csv_analyze: 'Analyser un fichier CSV',
    system_cleanup: 'Nettoyer le système',
    pc_hardware_specs: 'Caractéristiques matérielles',
    pc_hardware_temps: 'Températures matérielles',
    pc_disk_smart_health: 'Santé disque (SMART)',
    pc_tool_reliability: 'Fiabilité des outils',
    billing_client_create: 'Créer un client',
    billing_quote_pdf: 'Générer un devis PDF',
    winget_install: 'Installer un logiciel',
    winget_search: 'Chercher un logiciel',
  };

  // v2.146 — repli : un nom d'outil non listé ci-dessus s'affichait tel quel
  // (snake_case brut) — traduit au minimum en mots séparés avec majuscule initiale
  // plutôt que d'exposer le nom technique interne.
  const prettyFallback = (n) => n.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
  const isCodingMissionTool = ['code_workspace_start', 'code_workspace_status', 'code_workspace_control'].includes(toolName);

  // Déterminer si on doit afficher les boutons de confirmation
  const approvalResult = state === 'result' ? unwrapToolResult(tool.result) : null;
  const hasPendingResultConfirmation = !!(
    approvalResult
    && typeof approvalResult === 'object'
    && approvalResult.requiresConfirmation
  );

  const approvalIsActive = hasPendingResultConfirmation
    && approvalState?.status === 'pending'
    && approvalState?.active === true;
  const needsConfirmation = approvalIsActive;
  const approvalFinalLabels = {
    approved: 'Action déjà autorisée et traitée',
    denied: 'Action refusée',
    expired: 'Autorisation expirée',
    superseded: 'Demande remplacée par une plus récente',
    failed: 'Action autorisée mais non aboutie',
    executing: 'Action en cours de traitement',
    unavailable: 'État de l’autorisation indisponible',
    checking: 'Vérification de l’autorisation…',
  };
  const approvalDisplayStatus = hasPendingResultConfirmation
    ? approvalState?.status || 'checking'
    : null;

  const statusLabel = approvalIsActive ? '⏳ En attente de votre confirmation'
    : approvalDisplayStatus ? approvalFinalLabels[approvalDisplayStatus] || 'Autorisation terminée'
    : accessLimited ? 'Accès restreint'
    : resultFailed ? '✕ Erreur'
    : state === 'result' ? '✓ Terminé'
    : state === 'error' ? '✗ Erreur'
    : state === 'call' && isCritical ? '⏳ En attente de votre confirmation'
    // v2.148 — chrono ajouté au-delà de 3s : sans lui, un outil lent (recherche
    // approfondie, panel d'experts, tâche longue...) reste sur "⟳ Exécution..." plusieurs
    // minutes sans aucun repère — symptôme déjà documenté (v2.125/v2.136).
    : state === 'call' ? `⟳ Exécution...${elapsed > 3 ? ` (${elapsed >= 60 ? `${Math.floor(elapsed / 60)}min ${elapsed % 60}s` : `${elapsed}s`})` : ''}`
    : state === 'partial-call' ? '⟳ Préparation...'
    : isCritical ? '⏳ En attente de votre confirmation'
    : '⟳ En cours...';

  const statusBadgeClass = approvalIsActive ? 'warning'
    : approvalDisplayStatus === 'approved' ? 'success'
    : approvalDisplayStatus ? 'info'
    : accessLimited ? 'warning'
    : resultFailed ? 'danger'
    : state === 'result' ? 'success'
    : state === 'error' ? 'danger'
    : 'info';

  return (
    <div style={{
      marginLeft: '40px',
      padding: '12px 16px',
      background: 'var(--bg-glass)',
      backdropFilter: 'blur(20px)',
      border: '1px solid var(--border)',
      borderLeft: `3px solid ${borderColor}`,
      borderRadius: '8px',
      fontSize: 'var(--font-sm)',
      animation: 'slideUp 0.3s ease',
    }}>
      {/* En-tête de l'outil */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
        <span>{icon}</span>
        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
          {toolLabels[toolName] || prettyFallback(toolName)}
        </span>
        <span className={`badge badge-${statusBadgeClass}`}>
          {statusLabel}
        </span>
      </div>

      {tool.result !== undefined && (
        <div className={resultFailed && !accessLimited ? styles.toolSummaryError : styles.toolSummary}>
          {summarizeToolResult(toolName, tool.result)}
        </div>
      )}

      {accessLimited && limitedResult && (
        <div style={{ marginTop: 8, color: 'var(--text-secondary)', fontSize: 12 }}>
          <div>Le contenu protégé n’a pas été utilisé comme source.</div>
          <a
            href={limitedResult.requested_url || limitedResult.url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ display: 'inline-block', marginTop: 6, color: 'var(--text-primary)', textDecoration: 'underline' }}
          >
            Ouvrir dans votre navigateur connecté
          </a>
        </div>
      )}

      {tool.evidence?.proof_recorded && (
        <div style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '6px' }}>
          Preuve durable vérifiée · séquence {tool.evidence.sequence}
        </div>
      )}

      {tool.evidence && !tool.evidence.proof_recorded && (
        <div style={{
          color: 'var(--warning)',
          background: 'rgba(245, 158, 11, 0.08)',
          border: '1px solid rgba(245, 158, 11, 0.25)',
          borderRadius: '6px',
          padding: '7px 9px',
          marginTop: '7px',
          fontSize: '11px',
        }}>
          Action exécutée, mais sa preuve durable n’a pas pu être enregistrée. Ne pas relancer
          automatiquement cette action ; vérifier son état réel.
        </div>
      )}

      {tool.result !== undefined && isCodingMissionTool && showMissionTracker && (
        <div style={{ marginTop: '10px' }}>
          <CodingMissionTracker result={tool.result} />
        </div>
      )}

      {/* Paramètres (si pas encore exécuté et outil critique) */}
      {needsConfirmation && tool.args && (
        <div style={{ color: 'var(--text-secondary)', fontSize: 'var(--font-xs)', marginTop: '6px' }}>
          <div style={{
            background: 'var(--bg-tertiary)', padding: '8px 12px', borderRadius: '6px',
            border: '1px solid var(--border)',
          }}>
            <strong>Paramètres :</strong>
            {Object.entries(tool.args).map(([key, val]) => (
              <div key={key} style={{ marginTop: '2px' }}>
                <span style={{ color: 'var(--accent-secondary)' }}>{key}</span>: <span style={{ color: 'var(--text-primary)' }}>{typeof val === 'string' ? val : JSON.stringify(val)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {approvalIsActive && (
        <div
          role="alertdialog"
          aria-label="Confirmation requise"
          style={{
            marginTop: 10,
            padding: '11px 12px',
            borderRadius: 10,
            border: '1px solid rgba(245,158,11,.36)',
            background: 'rgba(245,158,11,.08)',
          }}
        >
          <div style={{ color: 'var(--text-primary)', fontWeight: 700 }}>
            Confirmation requise
          </div>
          <div style={{ marginTop: 4, color: 'var(--text-secondary)', fontSize: 12 }}>
            {approvalResult.message || `Autoriser l’action « ${toolLabels[toolName] || prettyFallback(toolName)} » ?`}
          </div>
          <div style={{ marginTop: 5, color: 'var(--text-muted)', fontSize: 10.5 }}>
            Autorisation valable uniquement pour cet appel exact et pendant cinq minutes.
          </div>
        </div>
      )}

      {hasPendingResultConfirmation && !approvalIsActive && (
        <div
          role="status"
          style={{
            marginTop: 10,
            padding: '9px 11px',
            borderRadius: 10,
            border: '1px solid var(--border)',
            background: 'var(--bg-tertiary)',
            color: 'var(--text-secondary)',
            fontSize: 12,
          }}
        >
          {approvalFinalLabels[approvalDisplayStatus] || 'Cette autorisation n’est plus active.'}
          <div style={{ marginTop: 3, color: 'var(--text-muted)', fontSize: 10.5 }}>
            Les boutons ont été désactivés. Relancez explicitement l’action si elle reste nécessaire.
          </div>
        </div>
      )}

      {/* Résultat structuré */}
      {hasPendingResultConfirmation
        && !approvalIsActive
        && ['expired', 'superseded', 'failed'].includes(approvalDisplayStatus) && (
        <button
          type="button"
          onClick={() => onRetry?.(toolName, tool.args)}
          style={{ marginTop: 8, padding: '7px 11px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-glass)', color: 'var(--text-primary)', cursor: 'pointer' }}
        >
          Creer une nouvelle demande
        </button>
      )}

      {tool.result !== undefined && !isCodingMissionTool && (
        <div style={{ marginTop: '8px' }}>
          <button
            type="button"
            className={styles.technicalDetailsButton}
            onClick={() => setDetailsOpen((current) => !current)}
            aria-expanded={detailsOpen}
          >
            {detailsOpen ? 'Masquer les détails techniques' : 'Afficher les détails techniques'}
          </button>
          {detailsOpen && (
            <div className={styles.technicalDetails}>
              {renderToolResult(toolName, tool.result)}
            </div>
          )}
        </div>
      )}
      {tool.detailRef && (
        <ToolDetailControl tool={tool} conversationId={conversationId} />
      )}

      {/* Boutons de confirmation */}
      {needsConfirmation && (
        <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
          <button
            disabled={!approvalIsActive || !approvalResult?.approvalId}
            onClick={() => onConfirm?.(
              tool.toolCallId,
              approvalResult?.approvalId,
            )}
            style={{
              padding: '8px 16px',
              background: 'var(--accent-gradient)',
              border: 'none', borderRadius: '6px',
              color: 'white', cursor: 'pointer',
              fontWeight: 600, fontSize: 'var(--font-xs)',
              boxShadow: 'var(--accent-glow)',
              display: 'flex', alignItems: 'center', gap: '6px',
            }}
          >
            Oui, autoriser
          </button>
          <button
            disabled={!approvalIsActive || !approvalResult?.approvalId}
            onClick={() => onCancel?.(
              tool.toolCallId,
              approvalResult?.approvalId,
            )}
            style={{
              padding: '8px 16px',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border)', borderRadius: '6px',
              color: 'var(--text-primary)', cursor: 'pointer',
              fontSize: 'var(--font-xs)',
              display: 'flex', alignItems: 'center', gap: '6px',
            }}
          >
            Non, refuser
          </button>
        </div>
      )}
    </div>
  );
}

function ToolDetailControl({ tool, conversationId, compact = false }) {
  const [state, setState] = useState('available');
  const [detail, setDetail] = useState(null);
  const controllerRef = useRef(null);
  useEffect(() => () => controllerRef.current?.abort(), [controllerRef]);
  useEffect(() => {
    controllerRef.current?.abort();
    setState('available');
    setDetail(null);
  }, [conversationId, tool?.detailRef?.messageId, tool?.detailRef?.toolCallId]);
  const load = async () => {
    if (!conversationId || !tool?.detailRef || state === 'loading') return;
    controllerRef.current?.abort();
    controllerRef.current = new AbortController();
    setState('loading');
    try {
      const { messageId, toolCallId } = tool.detailRef;
      const response = await fetch(
        `/api/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/tool-results/${encodeURIComponent(toolCallId)}`,
        { signal: controllerRef.current.signal, cache: 'no-store' },
      );
      if (response.status === 404) {
        setState('unavailable');
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setDetail(payload.result);
      setState('loaded');
    } catch (error) {
      if (error?.name !== 'AbortError') setState('error');
    }
  };
  if (state === 'unavailable') {
    return <div role="status" style={{ marginTop: compact ? 0 : 8, color: 'var(--text-muted)', fontSize: 12 }}>Le résultat détaillé n’est plus disponible. Le résumé conservé reste accessible.</div>;
  }
  return (
    <div style={{ marginTop: compact ? 0 : 8 }}>
      {state !== 'loaded' && (
        <button type="button" onClick={load} disabled={state === 'loading'} style={{ padding: '6px 10px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-glass)', color: 'var(--text-primary)', cursor: state === 'loading' ? 'wait' : 'pointer', fontSize: 12 }}>
          {state === 'loading' ? 'Chargement du détail…' : state === 'error' ? 'Réessayer de charger le détail' : `Charger le détail de ${tool.toolName || 'l’outil'}`}
        </button>
      )}
      {state === 'error' && <div role="status" style={{ color: 'var(--warning)', fontSize: 11, marginTop: 4 }}>Le détail est temporairement indisponible. Aucun nouvel essai n’a été lancé automatiquement.</div>}
      {state === 'loaded' && <div style={{ marginTop: 6 }}>{renderToolResult(tool.toolName || '', detail)}</div>}
    </div>
  );
}
