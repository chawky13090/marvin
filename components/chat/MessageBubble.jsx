'use client';
import { useState, useMemo, useEffect } from 'react';
import { marked } from 'marked';
import styles from './MessageBubble.module.css';
import FileExplorerCard from './FileExplorerCard';
import SpeakButton from './SpeakButton';
import PrettyResult from './PrettyResult';
import CortexTrace from './CortexTrace';
import CodingMissionTracker from './CodingMissionTracker';
import { CircleGauge, BarRow, StatCard } from '@/components/ui/DashboardKit';
import { useToast } from '@/components/ui/Toast';
import { BACKEND_URL } from '@/lib/backend';

// v2.128 — les outils qui GÉNÈRENT un document (PDF/Word/Excel...) renvoyaient juste
// { success, message, path } → rendu par le fallback "succès générique" (un simple ✅),
// obligeant l'utilisateur à aller chercher le fichier lui-même sur le disque. Demandé
// explicitement (« j'aimerais pouvoir cliquer et ouvrir les documents générés directement
// depuis le chat »). Détecté par EXTENSION du path plutôt que par nom d'outil un par un
// (file_create_pdf, document_generate, billing_quote_pdf, file_convert_docx_to_pdf...
// tous partagent la même forme de résultat) — plus robuste à un futur outil de génération.
const DOCUMENT_EXTENSIONS = new Set([
  'pdf', 'docx', 'doc', 'rtf', 'odt', 'xlsx', 'xls', 'csv', 'pptx', 'ppt', 'txt', 'md',
  // v2.145 — webapp_create ("ChatGPT Sites") génère une mini-appli HTML autonome ;
  // pc_open_file (os.startfile) ouvre déjà un .html dans le navigateur par défaut,
  // zéro code supplémentaire nécessaire côté ouverture — juste la reconnaître ici.
  'html', 'htm',
]);
// v2.142 — code_python capture désormais les fichiers écrits par le code exécuté (Code
// Interpreter local) : le cas le plus courant est un graphique matplotlib. Set séparé
// (pas fusionné à DOCUMENT_EXTENSIONS) pour permettre un rendu en VIGNETTE plutôt qu'une
// simple icône cliquable — voir GeneratedFileCard.
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp']);

function docIcon(ext) {
  const map = {
    pdf: '📕', docx: '📝', doc: '📝', rtf: '📝', odt: '📝',
    xlsx: '📗', xls: '📗', csv: '📗', pptx: '📊', ppt: '📊', txt: '📄', md: '📄',
    html: '🌐', htm: '🌐',
  };
  return map[ext] || '📄';
}

// v2.183 — laisser le choix du format même APRÈS génération (demandé explicitement) :
// docx<->pdf uniquement pour l'instant (voir document_convert_format côté backend).
const CONVERTIBLE_TARGET = { docx: 'pdf', pdf: 'docx' };

function GeneratedFileCard({ path, message, securityWarning }) {
  const [status, setStatus] = useState('idle'); // idle | opening | error
  const [converting, setConverting] = useState(false);
  const { toast } = useToast();
  const fileName = path.split(/[\\/]/).pop() || path;
  const ext = (fileName.split('.').pop() || '').toLowerCase();
  const isImage = IMAGE_EXTENSIONS.has(ext);
  const convertTarget = CONVERTIBLE_TARGET[ext];

  const handleOpen = async () => {
    setStatus('opening');
    try {
      const res = await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName: 'pc_open_file', args: { path, confirmed: true } }),
      });
      const data = await res.json();
      setStatus(data?.result?.success ? 'idle' : 'error');
    } catch {
      setStatus('error');
    }
  };

  const handleConvert = async (e) => {
    e.stopPropagation();
    if (!convertTarget || converting) return;
    setConverting(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          toolName: 'document_convert_format',
          args: { path, target_format: convertTarget, confirmed: true },
        }),
      });
      const data = await res.json();
      if (data?.result?.success) {
        toast.success(`Converti en ${convertTarget.toUpperCase()}`, data.result.path.split(/[\\/]/).pop());
      } else {
        toast.error('Échec de la conversion', data?.result?.error || data?.error || '');
      }
    } catch (err) {
      toast.error('Échec de la conversion', err.message);
    } finally {
      setConverting(false);
    }
  };

  // v2.142 — un fichier image (graphique généré par code_python) se prête à une
  // VIGNETTE inline plutôt qu'à une simple icône — sert le fichier via l'endpoint
  // déjà existant /api/files/raw (utilisé ailleurs pour la visionneuse de fichiers).
  if (isImage) {
    return (
      <div>
        <div
          onClick={handleOpen}
          title={`${path} — cliquer pour ouvrir`}
          style={{
            display: 'inline-block', padding: '8px', background: 'var(--bg-tertiary)',
            border: '1px solid var(--border)', borderRadius: '8px', cursor: 'pointer',
          }}
        >
          <img
            src={`${BACKEND_URL}/api/files/raw?path=${encodeURIComponent(path)}`}
            alt={fileName}
            style={{ maxWidth: '360px', maxHeight: '320px', display: 'block', borderRadius: '4px' }}
          />
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '6px', textAlign: 'center' }}>
            {fileName}{message ? ` — ${message}` : ''}
          </div>
        </div>
        {securityWarning && (
          <div style={{
            marginTop: '6px', padding: '8px 12px',
            background: 'var(--danger-bg, rgba(239,68,68,0.08))', border: '1px solid var(--danger)',
            borderRadius: '6px', fontSize: '11px', color: 'var(--danger)', whiteSpace: 'pre-wrap',
          }}>
            {securityWarning}
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      <div
        onClick={handleOpen}
        title={path}
        style={{
          display: 'flex', alignItems: 'center', gap: '10px',
          padding: '10px 14px', background: 'var(--bg-tertiary)',
          border: '1px solid var(--border)', borderRadius: '8px',
          cursor: status === 'opening' ? 'wait' : 'pointer',
        }}
      >
        <span style={{ fontSize: '22px' }}>{docIcon(ext)}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 'var(--font-xs)', color: 'var(--accent-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {fileName}
          </div>
          {message && (
            <div style={{ fontSize: '11px', color: 'var(--success)', marginTop: '2px' }}>✅ {message}</div>
          )}
          {status === 'error' && (
            <div style={{ fontSize: '11px', color: 'var(--danger)', marginTop: '2px' }}>Impossible d'ouvrir le fichier — vérifie qu'il existe toujours.</div>
          )}
        </div>
        <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
          {status === 'opening' ? '⏳ Ouverture...' : '📂 Ouvrir'}
        </span>
        {convertTarget && (
          <span
            onClick={handleConvert}
            title={`Convertir en .${convertTarget}`}
            style={{
              fontSize: 'var(--font-xs)', color: 'var(--accent-secondary)', whiteSpace: 'nowrap',
              cursor: converting ? 'wait' : 'pointer', borderLeft: '1px solid var(--border)', paddingLeft: '10px',
            }}
          >
            {converting ? '⏳ Conversion...' : `⇄ En .${convertTarget}`}
          </span>
        )}
      </div>
      {/* v2.133 — filet déterministe étendu au CONTENU des documents générés (pas seulement
          la réponse de chat visible) : le PDF GLPI qui a motivé ce chantier avait son problème
          dans le contenu du document, jamais dans le texte de chat lui-même. */}
      {securityWarning && (
        <div style={{
          marginTop: '6px', padding: '8px 12px',
          background: 'var(--danger-bg, rgba(239,68,68,0.08))', border: '1px solid var(--danger)',
          borderRadius: '6px', fontSize: '11px', color: 'var(--danger)', whiteSpace: 'pre-wrap',
        }}>
          {securityWarning}
        </div>
      )}
    </div>
  );
}

// Configure marked
marked.setOptions({ gfm: true, breaks: true });

// Safe HTML render — strips script/event-handler XSS from LLM output
let _dompurifyLinksHooked = false;
function safeHtml(raw) {
  if (typeof window === 'undefined') return raw; // SSR: skip
  try {
    const DOMPurify = require('dompurify');
    // Liens cliquables dans le chat = ouverture dans un NOUVEL onglet, jamais en quittant
    // Marvin — signalé par l'utilisateur (liens pertinents cités par Marvin qui faisaient
    // perdre la conversation). Hook DOMPurify plutôt qu'un renderer marked personnalisé :
    // couvre aussi bien les liens markdown [texte](url) que du HTML <a> brut éventuel dans
    // la réponse du modèle, indépendamment de la version de marked.
    if (!_dompurifyLinksHooked) {
      DOMPurify.addHook('afterSanitizeAttributes', (node) => {
        if (node.tagName === 'A' && node.hasAttribute('href')) {
          node.setAttribute('target', '_blank');
          node.setAttribute('rel', 'noopener noreferrer');
        }
      });
      _dompurifyLinksHooked = true;
    }
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  } catch {
    return raw; // fallback if dompurify unavailable
  }
}

export default function MessageBubble({ message, viewMode = 'reading', showMissionTracker = true, onConfirmTool, onCancelTool }) {
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

  const htmlContent = useMemo(() => safeHtml(marked.parse(textContent || '')), [textContent]);

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

  const provenanceLabel = message.modelInfo?.privacyMode === 'ultra_cloud'
    ? 'Cloud strict'
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
    return (
      <div className={`${styles.wrapper} ${styles.wrapperAssistant}`} style={{ flexDirection: 'column', gap: '8px', opacity: 1, maxWidth: '100%' }}>
        <TurnModeBadge mode={turnMode} />
        {reasoningBlock}
        {textContent && (
          <BubbleWrapper isUser={false}>
            <ReadableContent html={htmlContent} text={textContent} viewMode={viewMode} />
          </BubbleWrapper>
        )}
        <div className={styles.responseMetaRow}>
          {shouldCollapse && (
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
        {codingMissionTool && showMissionTracker && (
          <div style={{ marginLeft: '40px', width: 'calc(100% - 40px)' }}>
            <CodingMissionTracker result={codingMissionTool.result} />
          </div>
        )}
        {(!shouldCollapse || !stepsCollapsed) && (
          <div className={styles.toolCalls}>
            {toolInvocations.map((tool, i) => (
              <ToolCallInline
                key={tool.toolCallId || i}
                tool={tool}
                viewMode={viewMode}
                onConfirm={onConfirmTool}
                onCancel={onCancelTool}
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
function CollapsibleDetail({ label, children }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: '8px' }}>
      <div
        onClick={() => setOpen(!open)}
        style={{ cursor: 'pointer', userSelect: 'none', fontSize: '11px', color: 'var(--accent-primary)', fontWeight: 600 }}
      >
        {open ? '▲' : '▼'} {label}
      </div>
      {open && <div style={{ marginTop: '6px' }}>{children}</div>}
    </div>
  );
}

function MarkdownBlock({ text }) {
  const html = useMemo(() => safeHtml(marked.parse(text || '')), [text]);
  return <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-primary)', lineHeight: 1.5 }} dangerouslySetInnerHTML={{ __html: html }} />;
}

// ─── Rendu structuré des résultats d'outils ───
function renderToolResult(toolName, result) {
  if (!result) return null;
  if (typeof result === 'string') {
    try { result = JSON.parse(result); } catch { return <span>{result}</span>; }
  }

  // Désencapsuler le format du SDK ( { type: 'json', value: ... } )
  if (result && typeof result === 'object' && result.type === 'json' && result.value !== undefined) {
    result = result.value;
  }

  // Erreur
  if (result.error) {
    return (
      <div style={{ color: 'var(--danger)', display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span>❌</span> {typeof result.error === 'string' ? result.error : JSON.stringify(result.error)}
      </div>
    );
  }

  if (['code_workspace_start', 'code_workspace_status', 'code_workspace_control'].includes(toolName)) {
    return <CodingMissionTracker result={result} />;
  }

  // ── Image inline (screenshot embed, infographic) ─────
  if (result.image && result.image.startsWith('data:image/')) {
    return (
      <div>
        {result.message && (
          <div style={{ fontSize: 'var(--font-xs)', color: 'var(--success)', marginBottom: '8px' }}>✅ {result.message}</div>
        )}
        <img
          src={result.image}
          alt="Capture"
          style={{ maxWidth: '100%', maxHeight: '400px', borderRadius: '8px', border: '1px solid var(--border)', cursor: 'pointer' }}
          onClick={() => window.open(result.image, '_blank')}
        />
      </div>
    );
  }

  // ── web_deep_research (v2.142) ─────
  if (toolName === 'web_deep_research' && result.answer) {
    const coverage = result.source_coverage || {};
    return (
      <div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 9 }}>
          <span style={{ fontSize: 10, padding: '3px 7px', borderRadius: 999, background: 'rgba(20,184,166,.12)', color: '#5eead4' }}>
            {result.engine_version === 'v3' ? 'Recherche vérifiée v3' : 'Recherche approfondie'}
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            {coverage.queries_executed ?? result.rounds ?? 1} requête(s)
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            {coverage.pages_read ?? (result.sources || []).length} page(s) lue(s)
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            {(result.sources || []).length} source(s) unique(s)
          </span>
          {coverage.pages_rejected != null && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              {coverage.pages_rejected} rejet(s)
            </span>
          )}
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.sources || []).length > 0 && (
          <CollapsibleDetail label={`Sources (${result.sources.length})`}>
            {result.sources.map((s, i) => (
              <div key={i} style={{ fontSize: '11px', marginBottom: '4px' }}>
                <a href={s.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)' }}>
                  [{i + 1}] {s.title || s.url}
                </a>
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  if (toolName === 'ai_research_swarm' && result.answer) {
    const coverage = result.source_coverage || {};
    const forge = result.forge || {};
    return (
      <div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 9 }}>
          <span style={{ fontSize: 10, padding: '3px 7px', borderRadius: 999, background: 'rgba(20,184,166,.12)', color: '#5eead4' }}>
            {result.engine_version === 'v3' ? 'Recherche adaptative v3' : 'Research Swarm v2'}
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{(result.sources || []).length} sources</span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{coverage.unique_domains || 0} domaines</span>
          {forge.citation_validity != null && (
            <span style={{ fontSize: 10, color: forge.gate_passed ? '#34d399' : '#fbbf24' }}>
              {Math.round(forge.citation_validity * 100)} % de citations valides
            </span>
          )}
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.sources || []).length > 0 && (
          <CollapsibleDetail label={`Sources et preuves (${result.sources.length})`}>
            {result.sources.map((source, index) => (
              <div key={source.url || index} style={{ fontSize: 11, marginBottom: 6 }}>
                <a href={source.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)' }}>
                  [{source.id || source.citation || index + 1}] {source.title || source.url}
                </a>
                {source.source_type && <span style={{ marginLeft: 6, color: 'var(--text-muted)' }}>{source.source_type}</span>}
              </div>
            ))}
          </CollapsibleDetail>
        )}
        {(result.queries || []).length > 0 && (
          <CollapsibleDetail label={`Trajectoire de recherche (${result.queries.length})`}>
            {result.queries.map((query, index) => (
              <div key={query.id || index} style={{ fontSize: 11, marginBottom: 5, color: 'var(--text-secondary)' }}>
                {index + 1}. {query.query} · {query.accepted_sources || 0} source(s) retenue(s)
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  // ── ai_model_council (v2.141) — Panel d'experts IA ─────
  if (toolName === 'ai_model_council' && result.answer) {
    return (
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
          🧑‍🤝‍🧑 {(result.models_consulted || []).length} modèle(s) consulté(s) en parallèle
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.individual_answers || []).length > 0 && (
          <CollapsibleDetail label="Voir les réponses individuelles">
            {result.individual_answers.map((a, i) => (
              <div key={i} style={{ padding: '8px 10px', marginBottom: '6px', background: 'var(--bg-tertiary)', borderRadius: '6px', borderLeft: '3px solid var(--accent-primary)' }}>
                <div style={{ fontWeight: 600, fontSize: '11px', color: 'var(--accent-primary)', marginBottom: '4px', fontFamily: 'monospace' }}>{a.model}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{a.answer}</div>
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  if (toolName === 'ai_adaptive_team' && result.answer) {
    return (
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
          Équipe adaptative · {(result.stages || []).filter(stage => stage.success).length}/{(result.stages || []).length} étape(s)
          {(result.models_consulted || []).length ? ` · ${result.models_consulted.length} modèle(s)` : ''}
          {result.evidence_quality?.epistemic_debt != null ? ` · dette de preuve ${Math.round(result.evidence_quality.epistemic_debt * 100)} %` : ''}
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.stages || []).length > 0 && (
          <CollapsibleDetail label="Voir le raisonnement de l’équipe">
            {result.stages.map((stage, index) => (
              <div key={`${stage.name}-${index}`} style={{ padding: '8px 10px', marginBottom: 6, borderRadius: 7, background: 'var(--bg-tertiary)', borderLeft: `3px solid ${stage.success ? '#34d399' : '#f87171'}` }}>
                <div style={{ fontWeight: 700, fontSize: 11 }}>{index + 1}. {stage.name} · {stage.success ? 'réussi' : 'échoué'}</div>
                {stage.error && <div style={{ color: '#f87171', fontSize: 11, marginTop: 4 }}>{stage.error}</div>}
                {stage.answer && <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginTop: 5, whiteSpace: 'pre-wrap', maxHeight: 180, overflowY: 'auto' }}>{stage.answer}</div>}
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  if (toolName === 'ai_code_forge' && result.answer) {
    const validation = result.validation || {};
    const testReport = result.test_report || {};
    return (
      <div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
          Code Forge · {result.language || 'langage détecté'}
          {validation.syntax_valid === true ? ' · syntaxe validée' : validation.syntax_valid === false ? ' · syntaxe invalide' : ' · analyseur indisponible'}
          {` · ${result.critical_issues || 0} critique(s) restante(s)`}
          {result.final_review?.score != null ? ` · gate final ${result.final_review.score}/10` : ''}
          {testReport.production_ready === true ? ' · tests isolés réussis' : ' · tests isolés non validés'}
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.reviews || []).length > 0 && (
          <CollapsibleDetail label="Voir les revues indépendantes">
            {result.reviews.map((review, index) => (
              <div key={index} style={{ padding: '8px 10px', marginBottom: 6, background: 'var(--bg-tertiary)', borderRadius: 7 }}>
                <div style={{ fontWeight: 700, fontSize: 11 }}>{review.model || `Reviewer ${index + 1}`} · {review.score}/10</div>
                {(review.issues || []).map((issue, issueIndex) => (
                  <div key={issueIndex} style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 5 }}>
                    [{issue.severity}] {issue.problem}
                  </div>
                ))}
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  if (toolName === 'ai_test_forge' && Array.isArray(result.steps)) {
    return (
      <div>
        <div style={{ fontSize: 11, color: result.production_ready ? '#34d399' : '#f87171', marginBottom: 8, fontWeight: 700 }}>
          Test Forge · {result.language || 'langage inconnu'} · {result.production_ready ? 'prêt production' : 'refusé'}
        </div>
        {(result.steps || []).map((step, index) => (
          <div key={`${step.name}-${index}`} style={{ padding: '7px 9px', marginBottom: 6, borderRadius: 7, background: 'var(--bg-tertiary)', borderLeft: `3px solid ${step.passed ? '#34d399' : '#f87171'}` }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>{step.name} · {step.passed ? 'réussi' : 'échoué'} · code {step.exit_code}</div>
            {step.stderr && <div style={{ marginTop: 4, color: 'var(--text-secondary)', fontSize: 10, whiteSpace: 'pre-wrap', maxHeight: 120, overflowY: 'auto' }}>{step.stderr}</div>}
          </div>
        ))}
        {result.error && <div style={{ color: '#f87171', fontSize: 11 }}>{result.error}</div>}
      </div>
    );
  }

  // ── ai_subagents_run (v2.145) — sous-tâches parallèles ─────
  if (toolName === 'ai_subagents_run' && result.answer) {
    return (
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
          🧩 {(result.subtasks || []).length} sous-tâche(s) traitée(s) en parallèle
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.subtask_results || []).length > 0 && (
          <CollapsibleDetail label="Voir le détail par sous-tâche">
            {result.subtask_results.map((s, i) => (
              <div key={i} style={{ padding: '8px 10px', marginBottom: '6px', background: 'var(--bg-tertiary)', borderRadius: '6px', borderLeft: '3px solid var(--accent-primary)' }}>
                <div style={{ fontWeight: 600, fontSize: '11px', color: 'var(--text-primary)', marginBottom: '4px' }}>{s.subtask}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{s.result}</div>
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  // ── long_task_start (v2.145) — checklist de la tâche longue ─────
  if (toolName === 'long_task_start' && Array.isArray(result.steps)) {
    return (
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
          🗂️ {result.steps.length} étape(s) — reprise automatique toutes les 5 min
        </div>
        {result.steps.map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', fontSize: '11px', marginBottom: '4px', color: 'var(--text-secondary)' }}>
            <span>☐</span><span>{s}</span>
          </div>
        ))}
      </div>
    );
  }

  // ── long_task_status (v2.145) — avancement des tâches longues ─────
  if (toolName === 'long_task_status' && Array.isArray(result.groups)) {
    if (result.groups.length === 0) {
      return <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>Aucune tâche longue en cours.</span>;
    }
    return (
      <div>
        {result.groups.map((g, gi) => (
          <div key={gi} style={{ marginBottom: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              <span>{g.tag}</span>
              <span>{g.done}/{g.total}</span>
            </div>
            <div style={{ height: '4px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden', marginBottom: '6px' }}>
              <div style={{ height: '100%', width: `${g.total ? (g.done / g.total) * 100 : 0}%`, background: 'var(--success)' }} />
            </div>
            {(g.steps || []).map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', fontSize: '11px', marginBottom: '2px', color: s.status === 'done' ? 'var(--text-muted)' : 'var(--text-secondary)', textDecoration: s.status === 'done' ? 'line-through' : 'none' }}>
                <span>{s.status === 'done' ? '☑' : '☐'}</span><span>{s.title}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    );
  }

  // ── web_search ─────
  if (toolName === 'web_search' && result.results) {
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          🔍 {result.count || result.results.length} résultat(s) — {result.provider || 'Web'}
        </div>
        {result.results.map((r, i) => (
          <div key={i} style={{ padding: '6px 10px', marginBottom: '6px', background: 'var(--bg-tertiary)', borderRadius: '6px', borderLeft: '3px solid var(--accent-primary)' }}>
            <div style={{ fontWeight: 600, fontSize: 'var(--font-xs)', color: 'var(--accent-primary)' }}>
              <a href={r.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)', textDecoration: 'none' }}>{r.title}</a>
            </div>
            {r.snippet && <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>{r.snippet}</div>}
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', wordBreak: 'break-all' }}>{r.url}</div>
          </div>
        ))}
      </div>
    );
  }

  // ── web_browse ─────
  if (toolName === 'web_browse' && result.content) {
    return (
      <div>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '4px' }}>
          🌐 <a href={result.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)' }}>{result.title || result.url}</a>
        </div>
        <pre style={{ background: 'var(--bg-tertiary)', padding: '8px 12px', borderRadius: '6px', fontSize: '11px', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-family)', color: 'var(--text-secondary)', maxHeight: '200px', overflowY: 'auto' }}>
          {result.content.substring(0, 2000)}{result.content.length > 2000 && '\n...'}
        </pre>
      </div>
    );
  }

  // ── Google Drive / OneDrive list ─────
  if ((toolName.startsWith('google_drive') || toolName.startsWith('onedrive')) && result.files) {
    const icon = toolName.startsWith('google') ? '🔴' : '🔵';
    return (
      <div style={{ maxHeight: '250px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>{icon} {result.count || result.files.length} fichier(s)</div>
        {result.files.map((f, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 'var(--font-xs)' }}>
            <span>{f.type === 'dossier' ? '📁' : '📄'}</span>
            <span style={{ color: 'var(--text-primary)', flex: 1 }}>{f.name}</span>
            {f.size > 0 && <span style={{ color: 'var(--text-muted)' }}>{(f.size / 1024).toFixed(0)} Ko</span>}
          </div>
        ))}
      </div>
    );
  }

  // ── system_search (Windows index, ULTRA-FAST) ─────
  if (toolName === 'system_search' && Array.isArray(result.results)) {
    return (
      <FileExplorerCard
        title={`🚀 Recherche "${result.query || ''}"`}
        items={result.results}
        method={result.method}
        elapsedMs={result.elapsed_ms}
      />
    );
  }

  // ── file_find (glob search) ─────
  if (toolName === 'file_find' && Array.isArray(result.results)) {
    return (
      <FileExplorerCard
        title={`🔭 Motif "${result.pattern || ''}" dans ${result.root || result.scope || 'le système'}`}
        items={result.results}
        method={result.method}
      />
    );
  }

  // ── file_list ─────
  if (toolName === 'file_list' && (result.files || result.entries)) {
    const items = (result.files || result.entries || []).map(f => ({
      name: f.name,
      path: f.path || `${result.currentDir || result.path || ''}\\${f.name}`,
      is_dir: f.type === 'dossier' || f.type === 'folder' || f.is_dir,
      size: f.size_bytes || (typeof f.size === 'number' ? f.size : 0),
      extension: f.extension || '',
    }));
    return (
      <FileExplorerCard
        title={`📂 ${result.currentDir || result.path || 'Dossier'}`}
        items={items}
        directory={result.currentDir || result.path}
        nextOffset={result.has_more ? result.next_offset : null}
        totalCount={result.total_count ?? result.count ?? items.length}
      />
    );
  }

  // ── file_search / file_search_text ─────
  if ((toolName === 'file_search' || toolName === 'file_search_text') && (result.results || result.files)) {
    const items = result.results || result.files || [];
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          🔍 {result.count || items.length} résultat(s) trouvé(s)
        </div>
        {items.slice(0, 20).map((item, i) => (
          <div key={i} style={{
            padding: '6px 10px', marginBottom: '4px',
            background: 'var(--bg-tertiary)', borderRadius: '6px',
            borderLeft: '3px solid var(--accent-secondary)',
          }}>
            <div style={{ fontWeight: 600, fontSize: 'var(--font-xs)', color: 'var(--text-primary)' }}>
              📄 {item.name}
            </div>
            {item.snippet && (
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px', fontStyle: 'italic' }}>
                "{item.snippet}"
              </div>
            )}
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
              {item.path}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // ── file_read ─────
  if (toolName === 'file_read' && result.content) {
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '4px' }}>
          📖 Contenu de : {result.path || 'fichier'}
        </div>
        <pre style={{
          background: 'var(--bg-tertiary)', padding: '8px 12px', borderRadius: '6px',
          fontSize: '12px', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-family)',
          color: 'var(--text-primary)', border: '1px solid var(--border)',
          maxHeight: '250px', overflowY: 'auto',
        }}>
          {result.content.substring(0, 3000)}
          {result.content.length > 3000 && '\n\n... (contenu tronqué)'}
        </pre>
      </div>
    );
  }

  // ── email_list_inbox ─────
  if (toolName === 'email_list_inbox' && result.emails) {
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          📧 {result.count || result.emails.length} email(s) {result.mode === 'demo' ? '(mode démo)' : ''}
        </div>
        {result.emails.slice(0, 15).map((email, i) => (
          <div key={i} style={{
            padding: '8px 12px', marginBottom: '4px',
            background: 'var(--bg-tertiary)', borderRadius: '6px',
            borderLeft: `3px solid ${email.read ? 'var(--text-muted)' : 'var(--accent-primary)'}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: email.read ? 400 : 700, fontSize: 'var(--font-xs)', color: 'var(--text-primary)' }}>
                {email.subject}
              </span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{email.date}</span>
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              De : {email.from}
            </div>
            {email.preview && (
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                {email.preview}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  // ── pc_system_info ─────
  if (toolName === 'pc_system_info' && result.memory) {
    return (
      <div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-xs)' }}>
          <tbody>
            {[
              ['🖥️ Système', `${result.platform} ${result.release} (${result.arch})`],
              ['⏱️ Uptime', result.uptime],
              ['💾 RAM totale', result.memory.total],
              ['📗 RAM libre', result.memory.free],
              ['📕 RAM utilisée', result.memory.used],
              ['📂 Sandbox', result.sandbox],
            ].map(([label, val], i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '4px 8px', fontWeight: 600, color: 'var(--text-primary)' }}>{label}</td>
                <td style={{ padding: '4px 8px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{val}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // ── calendar_list_events ─────
  if (toolName === 'calendar_list_events' && result.events) {
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          📅 {result.count || result.events.length} événement(s)
        </div>
        {result.events.map((evt, i) => (
          <div key={i} style={{
            padding: '8px 12px', marginBottom: '4px',
            background: 'var(--bg-tertiary)', borderRadius: '6px',
            borderLeft: '3px solid var(--accent-primary)',
          }}>
            <div style={{ fontWeight: 600, fontSize: 'var(--font-xs)', color: 'var(--text-primary)' }}>
              {evt.title}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              {evt.start} → {evt.end} {evt.location ? `📍 ${evt.location}` : ''}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // ── Plusieurs fichiers générés (v2.142 — code_python peut écrire plusieurs
  // graphiques/CSV en une seule exécution) — une carte par fichier reconnu.
  if (result.success && Array.isArray(result.files) && result.files.length > 1) {
    const cards = result.files
      .filter(p => typeof p === 'string')
      .map(p => (p.split(/[\\/]/).pop() || '').split('.').pop().toLowerCase())
      .map((ext, i) => ({ ext, path: result.files[i] }))
      .filter(({ ext }) => DOCUMENT_EXTENSIONS.has(ext) || IMAGE_EXTENSIONS.has(ext));
    if (cards.length > 0) {
      return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          {cards.map(({ path }, i) => <GeneratedFileCard key={i} path={path} />)}
        </div>
      );
    }
  }

  // ── Document/fichier généré (PDF/Word/Excel/PPT/texte/image) — clic pour ouvrir ─────
  if (result.success && typeof result.path === 'string') {
    const ext = (result.path.split(/[\\/]/).pop() || '').split('.').pop().toLowerCase();
    if (DOCUMENT_EXTENSIONS.has(ext) || IMAGE_EXTENSIONS.has(ext)) {
      return <GeneratedFileCard path={result.path} message={result.message} securityWarning={result.security_warning} />;
    }
  }

  // ── Succès générique ─────
  if (result.success && result.message) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--success)' }}>
        <span>✅</span> {result.message}
      </div>
    );
  }

  // ── pc_run_command ─────
  if (toolName === 'pc_run_command' && (result.stdout || result.stderr)) {
    return (
      <div style={{ maxHeight: '250px', overflowY: 'auto' }}>
        {result.stdout && result.stdout !== 'Aucune sortie standard.' && (
          <pre style={{
            background: 'var(--bg-tertiary)', padding: '8px 12px', borderRadius: '6px',
            fontSize: '12px', whiteSpace: 'pre-wrap', fontFamily: 'monospace',
            color: 'var(--success)', border: '1px solid var(--border)',
          }}>
            {result.stdout.substring(0, 3000)}
          </pre>
        )}
        {result.stderr && result.stderr !== 'Aucune erreur signalée.' && (
          <pre style={{
            background: 'var(--danger-bg)', padding: '8px 12px', borderRadius: '6px',
            fontSize: '12px', whiteSpace: 'pre-wrap', fontFamily: 'monospace',
            color: 'var(--danger)', marginTop: '4px',
          }}>
            {result.stderr.substring(0, 2000)}
          </pre>
        )}
        {result.success && <div style={{ color: 'var(--success)', fontSize: 'var(--font-xs)', marginTop: '4px' }}>✅ Commande exécutée avec succès</div>}
      </div>
    );
  }

  // ── Clipboard ─────
  if (toolName === 'pc_clipboard_get' && result.text !== undefined) {
    return (
      <div>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '4px' }}>📋 Contenu du presse-papiers :</div>
        <pre style={{
          background: 'var(--bg-tertiary)', padding: '8px 12px', borderRadius: '6px',
          fontSize: '12px', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-family)',
          color: 'var(--text-primary)', border: '1px solid var(--border)',
        }}>
          {result.text || '(vide)'}
        </pre>
      </div>
    );
  }

  // ── win_system_report (v2.134) — jauges CPU/RAM + barres disques au lieu d'un
  // tableau markdown brut. Réutilise DashboardKit (déjà éprouvé sur Monitoring/Santé).
  if (toolName === 'win_system_report' && result.cpu_percent !== undefined) {
    return (
      <div>
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginBottom: '10px' }}>
          <CircleGauge value={result.cpu_percent} label="CPU" size={90} />
          <CircleGauge value={result.ram_percent} label="RAM" size={90} color="#b8bbc1" />
        </div>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          {result.os} · {result.hostname} · uptime {result.uptime}
        </div>
        {(result.disks || []).map((d, i) => (
          <BarRow key={i} label={d.drive} used={d.total_gb - d.free_gb} total={d.total_gb} color={d.used_pct >= 90 ? '#ef4444' : '#b8bbc1'} />
        ))}
        {result.alerts && result.alerts.length > 0 && (
          <div style={{ marginTop: '8px', color: 'var(--danger)', fontSize: 'var(--font-xs)' }}>
            {result.alerts.map((a, i) => <div key={i}>⚠️ {a}</div>)}
          </div>
        )}
        <div style={{ marginTop: '6px', fontSize: 'var(--font-xs)', color: 'var(--success)' }}>{result.health}</div>
      </div>
    );
  }

  // ── pc_hardware_temps (v2.134) — capteurs réels, jamais une supposition.
  if (toolName === 'pc_hardware_temps' && (result.cpu_temp_available !== undefined || result.gpu_temp_available !== undefined)) {
    return (
      <div>
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
          <StatCard label="CPU" value={result.cpu_temp_available ? result.cpu_temp_c : 'N/D'} unit={result.cpu_temp_available ? '°C' : ''}
                    color={result.cpu_temp_available && result.cpu_temp_c >= 85 ? 'var(--danger)' : 'var(--text-primary)'} icon="🌡️" />
          <StatCard label="GPU" value={result.gpu_temp_available ? result.gpu_temp_c : 'N/D'} unit={result.gpu_temp_available ? '°C' : ''}
                    color={result.gpu_temp_available && result.gpu_temp_c >= 83 ? 'var(--danger)' : 'var(--text-primary)'} icon="🌡️" />
        </div>
        {result.message && <div style={{ marginTop: '6px', fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>{result.message}</div>}
        {(result.warnings || []).map((w, i) => <div key={i} style={{ color: 'var(--danger)', fontSize: 'var(--font-xs)', marginTop: '4px' }}>{w}</div>)}
      </div>
    );
  }

  // ── pc_disk_smart_health (v2.134) ─────
  if (toolName === 'pc_disk_smart_health' && Array.isArray(result.disks)) {
    return (
      <div style={{ maxHeight: '260px', overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-xs)' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              <th style={{ textAlign: 'left', padding: '4px 8px' }}>Disque</th>
              <th style={{ textAlign: 'left', padding: '4px 8px' }}>État</th>
              <th style={{ textAlign: 'left', padding: '4px 8px' }}>Usure</th>
              <th style={{ textAlign: 'left', padding: '4px 8px' }}>Erreurs non corrigées</th>
            </tr>
          </thead>
          <tbody>
            {result.disks.map((d, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '4px 8px', color: 'var(--text-primary)' }}>{d.FriendlyName} ({d.MediaType})</td>
                <td style={{ padding: '4px 8px', color: d.HealthStatus === 'Healthy' ? 'var(--success)' : 'var(--danger)' }}>{d.HealthStatus}</td>
                <td style={{ padding: '4px 8px', color: (d.Wear ?? 0) >= 80 ? 'var(--danger)' : 'var(--text-secondary)' }}>{d.Wear != null ? `${d.Wear}%` : 'N/D'}</td>
                <td style={{ padding: '4px 8px', color: (d.ReadErrorsUncorrected ?? 0) > 0 ? 'var(--danger)' : 'var(--text-secondary)' }}>{d.ReadErrorsUncorrected ?? 'N/D'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(result.warnings || []).map((w, i) => <div key={i} style={{ color: 'var(--danger)', fontSize: 'var(--font-xs)', marginTop: '6px' }}>{w}</div>)}
      </div>
    );
  }

  // ── pc_event_log_errors (v2.134) ─────
  if (toolName === 'pc_event_log_errors' && Array.isArray(result.events)) {
    return (
      <div style={{ maxHeight: '260px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          {result.count} événement(s) sur {result.period_days} jour(s)
        </div>
        {(result.recurring_sources || []).length > 0 && (
          <div style={{ marginBottom: '6px', fontSize: 'var(--font-xs)', color: 'var(--danger)' }}>
            🔁 Sources récurrentes : {result.recurring_sources.join(', ')}
          </div>
        )}
        {result.events.map((e, i) => (
          <div key={i} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', fontSize: '11px' }}>
            <span style={{ color: 'var(--text-muted)' }}>{e.TimeCreated}</span>{' '}
            <span style={{ color: 'var(--danger)', fontWeight: 600 }}>{e.LevelDisplayName}</span>{' '}
            <span style={{ color: 'var(--accent-primary)' }}>{e.ProviderName}</span>
            <div style={{ color: 'var(--text-secondary)' }}>{e.Message}</div>
          </div>
        ))}
      </div>
    );
  }

  // ── Fallback générique : rendu lisible (JSON uniquement sur demande, via le
  // bouton « { } Voir en JSON » intégré à PrettyResult) — tout outil sans rendu
  // spécifique ci-dessus (ex. winget_search, la plupart des outils win_*/billing_*)
  // passait auparavant en JSON brut par défaut, corrigé v2.107.
  return <PrettyResult result={result} />;
}

function ToolCallInline({ tool, viewMode, onConfirm, onCancel, showMissionTracker = true }) {
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

  if (!tool) return null;
  const toolName = tool.toolName || '';
  const icon = getToolIcon(toolName);
  const isCritical = CRITICAL_TOOLS.includes(toolName);
  const state = tool.state || (tool.result !== undefined ? 'result' : 'pending');
  const resultFailed = toolHasFailed(tool);
  const visualState = resultFailed ? 'error' : state;

  const statusColors = {
    pending: 'var(--warning)',
    running: 'var(--info)',
    result: 'var(--success)',
    error: 'var(--danger)',
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

  const needsConfirmation = hasPendingResultConfirmation;

  const statusLabel = hasPendingResultConfirmation ? '⏳ En attente de votre confirmation'
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

  const statusBadgeClass = hasPendingResultConfirmation ? 'warning'
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
        <div className={resultFailed ? styles.toolSummaryError : styles.toolSummary}>
          {summarizeToolResult(toolName, tool.result)}
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

      {hasPendingResultConfirmation && (
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

      {/* Résultat structuré */}
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

      {/* Boutons de confirmation */}
      {needsConfirmation && (
        <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
          <button
            disabled={hasPendingResultConfirmation && !approvalResult?.approvalId}
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
            disabled={hasPendingResultConfirmation && !approvalResult?.approvalId}
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
