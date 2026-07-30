'use client';
/**
 * FileExplorerCard — Interactive file/folder browser embedded in chat messages.
 *
 * Renders results from system_search, file_find, and file_list tools with:
 *   - Clickable folders → expand inline to show contents
 *   - Clickable files → open in default app (via pc_open_file)
 *   - Per-row actions : Open, Copy path, Open containing folder, Read content
 *
 * No prop drilling needed — uses fetch() directly against the backend API.
 */
import { useState, useCallback } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';
import { BACKEND_URL } from '@/lib/backend';

function fileIcon(item) {
  if (item.is_dir || item.type === 'folder' || item.type === 'dossier') return '📁';
  const ext = (item.extension || (item.name || '').split('.').pop() || '').toLowerCase().replace('.', '');
  const map = {
    pdf: '📕',
    docx: '📝', doc: '📝', rtf: '📝', odt: '📝',
    xlsx: '📗', xls: '📗', csv: '📗',
    pptx: '📊', ppt: '📊',
    txt: '📄', md: '📄', log: '📄',
    jpg: '🖼️', jpeg: '🖼️', png: '🖼️', gif: '🖼️', webp: '🖼️', bmp: '🖼️', svg: '🖼️',
    mp3: '🎵', wav: '🎵', flac: '🎵', m4a: '🎵', ogg: '🎵',
    mp4: '🎬', mkv: '🎬', avi: '🎬', mov: '🎬', webm: '🎬',
    zip: '🗜️', rar: '🗜️', '7z': '🗜️', tar: '🗜️', gz: '🗜️',
    py: '🐍', js: '📜', ts: '📜', jsx: '⚛️', tsx: '⚛️', html: '🌐', css: '🎨',
    json: '📋', xml: '📋', yaml: '📋', yml: '📋',
    exe: '⚙️', msi: '⚙️', bat: '⚙️', ps1: '⚙️',
  };
  return map[ext] || '📄';
}

function formatSize(bytes) {
  if (!bytes || bytes <= 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} Mo`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} Go`;
}

function shortenPath(p, max = 60) {
  if (!p || p.length <= max) return p;
  const parts = p.split('\\');
  if (parts.length <= 2) return '…' + p.slice(-max + 1);
  return parts[0] + '\\…\\' + parts.slice(-2).join('\\');
}

async function callTool(toolName, args) {
  const res = await fetch(`${BACKEND_URL}/api/tools`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toolName, args }),
  });
  const data = await res.json();
  return data.result || {};
}

function Toast({ message, type = 'info' }) {
  if (!message) return null;
  const colors = {
    success: { bg: 'rgba(34,197,94,0.12)',  border: '#22c55e', text: '#4ade80' },
    error:   { bg: 'rgba(239,68,68,0.12)',  border: '#ef4444', text: '#f87171' },
    info:    { bg: 'rgba(255,255,255,0.055)', border: '#8f9299', text: '#c7c9ce' },
  }[type] || { bg: '#222', border: '#444', text: '#fff' };
  return (
    <div style={{
      position: 'absolute', top: '8px', right: '8px', zIndex: 10,
      padding: '6px 12px',
      background: colors.bg, border: `1px solid ${colors.border}40`,
      borderRadius: '6px',
      color: colors.text, fontSize: '11px', fontWeight: 600,
      animation: 'slideUp 0.2s ease',
    }}>
      {message}
    </div>
  );
}

/**
 * Single file/folder row with inline expand for folders.
 */
function FileRow({ item, onOpenInChat, depth = 0 }) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);

  const isDir = item.is_dir || item.type === 'folder' || item.type === 'dossier';
  const path = item.path || '';
  const name = item.name || path.split(/[\\\/]/).pop() || '';

  const showToast = (msg, type = 'info') => {
    setToast({ message: msg, type });
    setTimeout(() => setToast(null), 2000);
  };

  const handleExpand = useCallback(async () => {
    if (!isDir) return;
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (children) {
      setExpanded(true);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await callTool('file_list', { path });
      if (result.error) {
        setError(result.error);
      } else {
        // Normalize the list — handle both `files` and `entries` keys
        const list = result.files || result.entries || [];
        setChildren(list.map(f => ({
          name: f.name,
          path: f.path || `${path}\\${f.name}`,
          is_dir: f.type === 'dossier' || f.type === 'folder' || f.is_dir,
          size: f.size_bytes || f.size || 0,
          extension: f.extension || '',
        })));
        setExpanded(true);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [isDir, expanded, children, path]);

  const handleOpen = useCallback(async (e) => {
    e.stopPropagation();
    try {
      const result = await callTool('pc_open_file', { path, confirmed: true });
      if (result.error) {
        showToast('Erreur: ' + result.error.slice(0, 40), 'error');
      } else {
        showToast(isDir ? '📁 Ouvert dans Explorateur' : '✅ Fichier ouvert', 'success');
      }
    } catch (e) {
      showToast('Erreur: ' + e.message.slice(0, 40), 'error');
    }
  }, [path, isDir]);

  const handleCopyPath = useCallback((e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(path).then(
      () => showToast('📋 Chemin copié', 'success'),
      () => showToast('Erreur copie', 'error')
    );
  }, [path]);

  const handleOpenContainer = useCallback(async (e) => {
    e.stopPropagation();
    const parent = path.replace(/[\\/][^\\\/]*$/, '');
    if (!parent) return;
    try {
      await callTool('pc_open_file', { path: parent, confirmed: true });
      showToast('📂 Dossier parent ouvert', 'success');
    } catch (err) {
      showToast('Erreur', 'error');
    }
  }, [path]);

  const handleReadFile = useCallback(async (e) => {
    e.stopPropagation();
    onOpenInChat?.(path);
  }, [path, onOpenInChat]);

  return (
    <div style={{ position: 'relative' }}>
      {/* Main row */}
      <div
        onClick={isDir ? handleExpand : undefined}
        style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          padding: '6px 10px',
          paddingLeft: `${10 + depth * 18}px`,
          marginBottom: '2px',
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid rgba(255,255,255,0.05)',
          borderRadius: '6px',
          cursor: isDir ? 'pointer' : 'default',
          transition: 'all 0.15s',
          fontSize: '12px',
        }}
        onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.045)'}
        onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.02)'}
      >
        <span style={{ fontSize: '14px', flexShrink: 0, width: '14px', textAlign: 'center' }}>
          {isDir ? (expanded ? '▼' : '▶') : ' '}
        </span>
        <span style={{ fontSize: '14px', flexShrink: 0 }}>{fileIcon(item)}</span>
        <span style={{
          flex: 1, color: 'var(--text-primary)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontWeight: isDir ? 500 : 400,
        }}>
          {name}
        </span>
        {item.size > 0 && (
          <span style={{ fontSize: '10px', color: 'var(--text-muted)', flexShrink: 0 }}>
            {formatSize(item.size)}
          </span>
        )}
        {/* Action buttons — visible on hover via opacity */}
        <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
          <ActionBtn title="Ouvrir" onClick={handleOpen}>🔓</ActionBtn>
          {!isDir && (
            <ActionBtn title="Lire le contenu dans le chat" onClick={handleReadFile}>👁️</ActionBtn>
          )}
          <ActionBtn title="Ouvrir le dossier parent" onClick={handleOpenContainer}>📂</ActionBtn>
          <ActionBtn title="Copier le chemin" onClick={handleCopyPath}>📋</ActionBtn>
        </div>
      </div>

      {/* Toast */}
      {toast && <div style={{ position: 'absolute', top: 0, right: 0 }}><Toast {...toast} /></div>}

      {/* Error inline */}
      {error && (
        <div style={{
          fontSize: '11px', color: '#f87171', padding: '4px 12px',
          marginLeft: `${10 + (depth + 1) * 18}px`,
        }}>
          ⚠️ {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div style={{
          padding: '4px 12px',
          marginLeft: `${10 + (depth + 1) * 18}px`,
        }}>
          <LoadingRow size={11} />
        </div>
      )}

      {/* Children (expanded folder contents) */}
      {expanded && children && (
        <div style={{ marginBottom: '4px' }}>
          {children.length === 0 ? (
            <div style={{
              fontSize: '11px', color: 'var(--text-muted)', padding: '4px 12px',
              marginLeft: `${10 + (depth + 1) * 18}px`,
              fontStyle: 'italic',
            }}>
              (Dossier vide)
            </div>
          ) : (
            children.slice(0, 100).map((child, i) => (
              <FileRow key={i} item={child} onOpenInChat={onOpenInChat} depth={depth + 1} />
            ))
          )}
          {children.length > 100 && (
            <div style={{
              fontSize: '10px', color: 'var(--text-muted)', padding: '4px 12px',
              marginLeft: `${10 + (depth + 1) * 18}px`,
            }}>
              … et {children.length - 100} de plus
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ActionBtn({ title, onClick, children }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        width: '24px', height: '22px', padding: 0,
        border: '1px solid rgba(255,255,255,0.08)',
        background: 'rgba(255,255,255,0.04)',
        borderRadius: '4px',
        cursor: 'pointer',
        fontSize: '12px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        opacity: 0.7,
        transition: 'all 0.15s',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.opacity = 1; e.currentTarget.style.background = 'rgba(255,255,255,0.075)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.opacity = 0.7; e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
    >
      {children}
    </button>
  );
}

/**
 * Main component.
 * Props:
 *   - items: array of {name, path, is_dir, size, extension}
 *   - title: header label
 *   - method: optional metadata to show (e.g. "windows_search_index")
 *   - elapsedMs: search time
 *   - onOpenInChat?: (path) => void — for "read file" action
 */
export default function FileExplorerCard({
  items = [],
  title,
  method,
  elapsedMs,
  onOpenInChat,
  directory,
  nextOffset = null,
  totalCount = null,
}) {
  const [visibleItems, setVisibleItems] = useState(items);
  const [remainingOffset, setRemainingOffset] = useState(nextOffset);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState('');
  const safeItems = visibleItems.filter(i => i && (i.path || i.name));

  const loadMore = useCallback(async () => {
    if (!directory || remainingOffset == null || loadingMore) return;
    setLoadingMore(true);
    setLoadError('');
    try {
      const result = await callTool('file_list', {
        path: directory,
        offset: remainingOffset,
        limit: 100,
      });
      if (result.error) throw new Error(result.error);
      const list = result.files || result.entries || [];
      setVisibleItems(current => [
        ...current,
        ...list.map(f => ({
          name: f.name,
          path: f.path || `${directory}\\${f.name}`,
          is_dir: f.type === 'dossier' || f.type === 'folder' || f.is_dir,
          size: f.size_bytes || (typeof f.size === 'number' ? f.size : 0),
          extension: f.extension || '',
        })),
      ]);
      setRemainingOffset(result.has_more ? result.next_offset : null);
    } catch (error) {
      setLoadError(error.message);
    } finally {
      setLoadingMore(false);
    }
  }, [directory, loadingMore, remainingOffset]);
  if (safeItems.length === 0) {
    return (
      <div style={{
        padding: '12px',
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: '8px',
        fontSize: '12px', color: 'var(--text-muted)',
        textAlign: 'center',
      }}>
        Aucun résultat trouvé.
      </div>
    );
  }

  return (
    <div style={{
      background: 'rgba(13,17,23,0.4)',
      border: '1px solid rgba(228, 228, 231,0.08)',
      borderRadius: '10px',
      padding: '10px',
      maxHeight: '500px',
      overflowY: 'auto',
    }}>
      {title && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '4px 8px 10px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          marginBottom: '8px',
        }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
            {title} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({safeItems.length})</span>
          </span>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
            {method === 'windows_search_index' && '🚀'} {elapsedMs != null && `${elapsedMs}ms`}
          </span>
        </div>
      )}
      <div>
        {safeItems.map((item, i) => (
          <FileRow key={i} item={item} onOpenInChat={onOpenInChat} />
        ))}
      </div>
      {remainingOffset != null && (
        <button
          type="button"
          onClick={loadMore}
          disabled={loadingMore}
          style={{
            width: '100%', marginTop: '8px', padding: '8px',
            borderRadius: '7px', border: '1px solid var(--border)',
            background: 'var(--bg-tertiary)', color: 'var(--accent)',
            cursor: loadingMore ? 'wait' : 'pointer',
          }}
        >
          {loadingMore
            ? 'Chargement…'
            : `Afficher la suite (${Math.max(0, (totalCount || 0) - safeItems.length)} restant(s))`}
        </button>
      )}
      {loadError && (
        <div style={{ color: '#f87171', fontSize: '11px', marginTop: '6px' }}>
          {loadError}
        </div>
      )}
      <div style={{
        marginTop: '8px', paddingTop: '6px',
        borderTop: '1px solid rgba(255,255,255,0.05)',
        fontSize: '10px', color: 'var(--text-muted)',
        textAlign: 'center',
      }}>
        💡 Cliquez sur un dossier pour explorer · 🔓 ouvrir · 👁️ lire · 📂 dossier parent · 📋 copier chemin
      </div>
    </div>
  );
}
