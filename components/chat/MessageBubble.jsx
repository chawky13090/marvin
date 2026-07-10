'use client';
import { useState, useMemo } from 'react';
import { marked } from 'marked';
import styles from './MessageBubble.module.css';
import FileExplorerCard from './FileExplorerCard';
import SpeakButton from './SpeakButton';
import PrettyResult from './PrettyResult';
import { CircleGauge, BarRow, StatCard } from '@/components/ui/DashboardKit';

const BACKEND_URL = (typeof window !== 'undefined' && window.location)
  ? window.location.protocol + '//' + window.location.hostname + ':8005'
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005');

// v2.128 — les outils qui GÉNÈRENT un document (PDF/Word/Excel...) renvoyaient juste
// { success, message, path } → rendu par le fallback "succès générique" (un simple ✅),
// obligeant l'utilisateur à aller chercher le fichier lui-même sur le disque. Demandé
// explicitement (« j'aimerais pouvoir cliquer et ouvrir les documents générés directement
// depuis le chat »). Détecté par EXTENSION du path plutôt que par nom d'outil un par un
// (file_create_pdf, document_generate, billing_quote_pdf, file_convert_docx_to_pdf...
// tous partagent la même forme de résultat) — plus robuste à un futur outil de génération.
const DOCUMENT_EXTENSIONS = new Set([
  'pdf', 'docx', 'doc', 'rtf', 'odt', 'xlsx', 'xls', 'csv', 'pptx', 'ppt', 'txt', 'md',
]);

function docIcon(ext) {
  const map = {
    pdf: '📕', docx: '📝', doc: '📝', rtf: '📝', odt: '📝',
    xlsx: '📗', xls: '📗', csv: '📗', pptx: '📊', ppt: '📊', txt: '📄', md: '📄',
  };
  return map[ext] || '📄';
}

function GeneratedFileCard({ path, message, securityWarning }) {
  const [status, setStatus] = useState('idle'); // idle | opening | error
  const fileName = path.split(/[\\/]/).pop() || path;
  const ext = (fileName.split('.').pop() || '').toLowerCase();

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
function safeHtml(raw) {
  if (typeof window === 'undefined') return raw; // SSR: skip
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const DOMPurify = require('dompurify');
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  } catch {
    return raw; // fallback if dompurify unavailable
  }
}

export default function MessageBubble({ message, onConfirmTool, onCancelTool }) {
  const isUser = message.role === 'user';
  const isToolResult = message.role === 'tool';
  const [showReasoning, setShowReasoning] = useState(false);

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

  // Badge modèle (affiché sous les réponses de l'assistant en mode auto)
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
    </div>
  ) : null;

  // Messages avec tool invocations
  if (toolInvocations.length > 0) {
    return (
      <div className={`${styles.wrapper} ${styles.wrapperAssistant}`} style={{ flexDirection: 'column', gap: '8px', opacity: 1, maxWidth: '100%' }}>
        {reasoningBlock}
        {textContent && (
          <BubbleWrapper isUser={false}>
            <div className={styles.content} dangerouslySetInnerHTML={{ __html: htmlContent }} />
          </BubbleWrapper>
        )}
        <div className={styles.toolCalls}>
          {toolInvocations.map((tool, i) => (
            <ToolCallInline
              key={tool.toolCallId || i}
              tool={tool}
              onConfirm={onConfirmTool}
              onCancel={onCancelTool}
            />
          ))}
        </div>
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
                    border: '1px solid rgba(79, 140, 255,0.2)', objectFit: 'cover',
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
            <div className={styles.content} dangerouslySetInnerHTML={{ __html: htmlContent }} />
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
    </div>
  );
}

function BubbleWrapper({ isUser, children }) {
  return (
    <div className={`${styles.wrapper} ${isUser ? styles.wrapperUser : styles.wrapperAssistant}`} style={{ opacity: 1 }}>
      <div className={`${styles.avatar} ${isUser ? styles.avatarUser : styles.avatarAssistant}`}
        style={!isUser ? {
          background: '#111',
          border: '1px solid rgba(79, 140, 255,0.2)',
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

// ─── Outils critiques nécessitant confirmation ───
const CRITICAL_TOOLS = [
  'file_delete', 'file_rename', 'file_move', 'file_write', 'file_organize',
  'file_create_docx', 'file_convert_docx_to_pdf',
  'email_send', 'email_reply',
  'calendar_create_event', 'calendar_update_event', 'calendar_delete_event',
  'pc_open_file', 'pc_run_command', 'pc_process_kill', 'pc_pull_ollama_model'
];

// ─── Icônes par catégorie d'outil ───
function getToolIcon(toolName) {
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

  // ── Document généré (PDF/Word/Excel/PPT/texte) — clic pour ouvrir ─────
  if (result.success && typeof result.path === 'string') {
    const ext = (result.path.split(/[\\/]/).pop() || '').split('.').pop().toLowerCase();
    if (DOCUMENT_EXTENSIONS.has(ext)) {
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
          <CircleGauge value={result.ram_percent} label="RAM" size={90} color="#38bdf8" />
        </div>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          {result.os} · {result.hostname} · uptime {result.uptime}
        </div>
        {(result.disks || []).map((d, i) => (
          <BarRow key={i} label={d.drive} used={d.total_gb - d.free_gb} total={d.total_gb} color={d.used_pct >= 90 ? '#ef4444' : '#4f8cff'} />
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

function ToolCallInline({ tool, onConfirm, onCancel }) {
  if (!tool) return null;
  const toolName = tool.toolName || '';
  const icon = getToolIcon(toolName);
  const isCritical = CRITICAL_TOOLS.includes(toolName);
  const state = tool.state || (tool.result !== undefined ? 'result' : 'pending');

  const statusColors = {
    pending: 'var(--warning)',
    running: 'var(--info)',
    result: 'var(--success)',
    error: 'var(--danger)',
    'partial-call': 'var(--info)',
    call: 'var(--info)',
  };
  const borderColor = statusColors[state] || 'var(--border)';

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
  };

  // Déterminer si on doit afficher les boutons de confirmation
  let hasPendingResultConfirmation = false;
  if (state === 'result' && tool.result) {
    let resObj = tool.result;
    if (typeof resObj === 'string') {
      try { resObj = JSON.parse(resObj); } catch {}
    }
    if (resObj && resObj.type === 'json' && resObj.value !== undefined) {
      resObj = resObj.value;
    }
    if (resObj && resObj.requiresConfirmation) {
      hasPendingResultConfirmation = true;
    }
  }

  const needsConfirmation = isCritical && (
    (state !== 'result' && state !== 'error' && (state === 'call' || state === 'pending')) ||
    hasPendingResultConfirmation
  );

  const statusLabel = hasPendingResultConfirmation ? '⏳ En attente de votre confirmation'
    : state === 'result' ? '✓ Terminé'
    : state === 'error' ? '✗ Erreur'
    : state === 'call' && isCritical ? '⏳ En attente de votre confirmation'
    : state === 'call' ? '⟳ Exécution...'
    : state === 'partial-call' ? '⟳ Préparation...'
    : isCritical ? '⏳ En attente de votre confirmation'
    : '⟳ En cours...';

  const statusBadgeClass = hasPendingResultConfirmation ? 'warning'
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
          {toolLabels[toolName] || toolName}
        </span>
        <span className={`badge badge-${statusBadgeClass}`}>
          {statusLabel}
        </span>
      </div>

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

      {/* Résultat structuré */}
      {tool.result !== undefined && (
        <div style={{ marginTop: '8px' }}>
          {renderToolResult(toolName, tool.result)}
        </div>
      )}

      {/* Boutons de confirmation */}
      {needsConfirmation && (
        <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
          <button
            onClick={() => onConfirm?.(tool.toolCallId, toolName, tool.args)}
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
            ✅ Confirmer l&apos;action
          </button>
          <button
            onClick={() => onCancel?.(tool.toolCallId)}
            style={{
              padding: '8px 16px',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border)', borderRadius: '6px',
              color: 'var(--text-primary)', cursor: 'pointer',
              fontSize: 'var(--font-xs)',
              display: 'flex', alignItems: 'center', gap: '6px',
            }}
          >
            ❌ Annuler
          </button>
        </div>
      )}
    </div>
  );
}
