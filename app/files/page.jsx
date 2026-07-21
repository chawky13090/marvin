'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';

const FILE_ICONS = {
  Dossier: '📁', Documents: '📄', Images: '🖼️', Videos: '🎬',
  Musique: '🎵', Archives: '📦', Programmes: '⚙️', Autres: '📎',
};

import { BACKEND_URL } from '@/lib/backend';

// Aperçu d'un classeur Excel (xlsx_read → {headers, data})
function TablePreview({ data }) {
  const headers = data?.headers || [];
  const rows = data?.data || [];
  if (!rows.length) return <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Feuille vide ou illisible.</div>;
  const asObj = !Array.isArray(rows[0]);
  const th = { border: '1px solid var(--border)', padding: '5px 9px', textAlign: 'left', background: 'rgba(255,255,255,0.05)', position: 'sticky', top: 0, fontWeight: 700 };
  const td = { border: '1px solid var(--border)', padding: '4px 9px', whiteSpace: 'nowrap' };
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
        <thead><tr>{headers.map((h, i) => <th key={i} style={th}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.slice(0, 300).map((row, ri) => (
            <tr key={ri}>{headers.map((h, ci) => <td key={ci} style={td}>{String((asObj ? row[h] : row[ci]) ?? '')}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {rows.length > 300 && <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 6 }}>+{rows.length - 300} lignes…</div>}
    </div>
  );
}

// ── Composant Modal générique ─────────────────────────────────────────────────

function Modal({ title, onClose, children }) {
  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 9000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--bg-secondary)', borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border)', padding: '24px 28px', minWidth: '380px', maxWidth: '480px',
          boxShadow: 'var(--shadow-xl)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px' }}>
          <h3 style={{ margin: 0, fontSize: 'var(--font-base)', fontWeight: 700 }}>{title}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: '1.3rem' }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ── Barre d'opérations batch (flottante) ────────────────────────────────────

function BatchToolbar({ selected, onDelete, onMove, onCopy, onRename, onClear }) {
  const count = selected.length;
  if (count === 0) return null;
  return (
    <div style={{
      position: 'fixed', bottom: '28px', left: '50%', transform: 'translateX(-50%)',
      background: '#1a1a2e', border: '1px solid rgba(79, 140, 255,0.35)',
      borderRadius: '50px', padding: '10px 20px',
      display: 'flex', alignItems: 'center', gap: '8px',
      boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
      zIndex: 2000,
      animation: 'slideUp 0.25s ease',
    }}>
      <span style={{ fontSize: 'var(--font-xs)', color: 'var(--accent-primary)', fontWeight: 700, marginRight: '4px' }}>
        {count} sélectionné{count > 1 ? 's' : ''}
      </span>
      <div style={{ width: '1px', height: '20px', background: 'var(--border)', margin: '0 4px' }} />
      <BatchBtn icon="📋" label="Copier les chemins" onClick={() => {
        const paths = selected.map(f => f.path).join('\n');
        navigator.clipboard.writeText(paths).catch(() => {});
      }} />
      <BatchBtn icon="📤" label="Déplacer" onClick={onMove} />
      <BatchBtn icon="📋" label="Copier" onClick={onCopy} />
      {count > 1 && <BatchBtn icon="✏️" label="Renommer en série" onClick={onRename} />}
      <BatchBtn icon="🗑️" label="Supprimer" onClick={onDelete} danger />
      <button
        onClick={onClear}
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'var(--text-muted)', fontSize: '1.1rem', padding: '4px 6px',
          borderRadius: '50%', marginLeft: '4px',
        }}
        title="Désélectionner tout"
      >×</button>
    </div>
  );
}

function BatchBtn({ icon, label, onClick, danger }) {
  return (
    <button
      onClick={onClick}
      title={label}
      style={{
        background: danger ? 'rgba(239,68,68,0.1)' : 'rgba(255,255,255,0.06)',
        border: `1px solid ${danger ? 'rgba(239,68,68,0.3)' : 'rgba(255,255,255,0.1)'}`,
        color: danger ? '#ef4444' : 'var(--text-secondary)',
        borderRadius: '24px', padding: '5px 12px',
        fontSize: 'var(--font-xs)', cursor: 'pointer',
        display: 'flex', alignItems: 'center', gap: '5px',
        transition: 'all 0.15s',
        fontWeight: 500,
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = danger ? 'rgba(239,68,68,0.2)' : 'rgba(255,255,255,0.1)';
        e.currentTarget.style.color = danger ? '#f87171' : 'var(--text-primary)';
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = danger ? 'rgba(239,68,68,0.1)' : 'rgba(255,255,255,0.06)';
        e.currentTarget.style.color = danger ? '#ef4444' : 'var(--text-secondary)';
      }}
    >
      <span>{icon}</span>
      <span style={{ display: window?.innerWidth > 900 ? 'inline' : 'none' }}>{label}</span>
    </button>
  );
}

// ── Page principale ───────────────────────────────────────────────────────────

export function FilesView() {
  const [files, setFiles] = useState([]);
  const [currentPath, setCurrentPath] = useState('');
  const [sandboxRoot, setSandboxRoot] = useState('');
  const [systemPaths, setSystemPaths] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState('list');
  const [pathInput, setPathInput] = useState('');

  // Sélection multiple
  const [selected, setSelected] = useState([]); // tableau d'objets fichier
  const lastClickedIdx = useRef(null);

  // Modales
  const [modal, setModal] = useState(null); // 'move' | 'copy' | 'rename' | 'newFolder'
  const [modalDest, setModalDest] = useState('');
  const [renamePattern, setRenamePattern] = useState('{n}');
  const [newFolderName, setNewFolderName] = useState('');
  const [opResult, setOpResult] = useState(null);

  // Context-menu fichier unique
  const [contextMenu, setContextMenu] = useState(null); // {file, x, y}
  const [renamingFile, setRenamingFile] = useState(null);
  const [renameValue, setRenameValue] = useState('');

  // Visionneuse de fichier (aperçu image / lecture document)
  const [preview, setPreview] = useState(null);       // {file, data, loading}
  const openPreview = useCallback(async (file) => {
    if (!file || file.type === 'dossier') return;
    setPreview({ file, loading: true });
    try {
      const data = await fetch(`${BACKEND_URL}/api/files/preview?path=${encodeURIComponent(file.path)}`).then(r => r.json());
      setPreview({ file, data, loading: false });
    } catch {
      setPreview({ file, data: { kind: 'binary', error: 'Aperçu impossible' }, loading: false });
    }
  }, []);
  const openWithWindows = useCallback((path) => {
    fetch(`${BACKEND_URL}/api/tools`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ toolName: 'pc_open_file', args: { path } }) }).catch(() => {});
  }, []);

  useEffect(() => {
    fetch(`${BACKEND_URL}/api/system/paths`)
      .then(r => r.json())
      .then(data => {
        setSystemPaths(data);
        setCurrentPath(data.home);
      })
      .catch(() => setCurrentPath(''));
  }, []);

  useEffect(() => { if (currentPath !== '') fetchFiles(); }, [currentPath]);

  // Fermer le context-menu sur clic ailleurs
  useEffect(() => {
    const close = () => setContextMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, []);

  async function fetchFiles(dirPath) {
    setLoading(true);
    setSelected([]);
    try {
      const p = dirPath || currentPath || '.';
      const res = await fetch(`/api/files?path=${encodeURIComponent(p)}`);
      const data = await res.json();
      if (data.success) {
        setFiles(data.files || []);
        setSandboxRoot(data.sandboxRoot || '');
      }
    } catch { }
    setLoading(false);
  }

  async function handleSearch(e) {
    e.preventDefault();
    if (!searchQuery.trim()) { fetchFiles(); return; }
    setLoading(true);
    setSelected([]);
    try {
      const res = await fetch(`/api/files?action=search&path=${encodeURIComponent(currentPath || '.')}&q=${encodeURIComponent(searchQuery)}`);
      const data = await res.json();
      setFiles(data.results || []);
    } catch { }
    setLoading(false);
  }

  function navigateTo(dirPath) {
    setCurrentPath(dirPath);
    setSearchQuery('');
    setSelected([]);
  }

  function goUp() {
    if (!currentPath || currentPath === '.' || currentPath === sandboxRoot) return;
    const parts = currentPath.replace(/\\/g, '/').split('/');
    parts.pop();
    navigateTo(parts.join('/') || '.');
  }

  function goToPath(e) {
    e.preventDefault();
    if (pathInput.trim()) navigateTo(pathInput.trim());
  }

  // ── Sélection ────────────────────────────────────────────────────────────────

  function toggleSelect(file, idx, e) {
    e.stopPropagation();
    if (e.shiftKey && lastClickedIdx.current !== null) {
      // Shift+click — sélectionner la plage
      const start = Math.min(lastClickedIdx.current, idx);
      const end = Math.max(lastClickedIdx.current, idx);
      const range = files.slice(start, end + 1);
      setSelected(prev => {
        const existing = prev.map(f => f.path);
        const toAdd = range.filter(f => !existing.includes(f.path));
        return [...prev, ...toAdd];
      });
    } else {
      const isSelected = selected.some(f => f.path === file.path);
      if (isSelected) {
        setSelected(prev => prev.filter(f => f.path !== file.path));
      } else {
        setSelected(prev => [...prev, file]);
      }
      lastClickedIdx.current = idx;
    }
  }

  function selectAll() {
    setSelected(files.length === selected.length ? [] : [...files]);
  }

  // ── Opérations individuelles ─────────────────────────────────────────────────

  async function openContextMenu(e, file) {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ file, x: e.clientX, y: e.clientY });
  }

  async function singleDelete(file) {
    if (!confirm(`Supprimer "${file.name}" ?`)) return;
    await fetch('/api/files', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filePath: file.path }) });
    fetchFiles();
  }

  function startRename(file) {
    setRenamingFile(file.path);
    setRenameValue(file.name);
    setContextMenu(null);
  }

  async function confirmRename() {
    if (!renameValue.trim() || renameValue === renamingFile) { setRenamingFile(null); return; }
    await fetch('/api/files', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'rename', filePath: renamingFile, newName: renameValue.trim() }),
    });
    setRenamingFile(null);
    fetchFiles();
  }

  // ── Opérations batch ─────────────────────────────────────────────────────────

  async function batchDelete() {
    const count = selected.length;
    if (!confirm(`Supprimer ${count} élément${count > 1 ? 's' : ''} ? Cette action est irréversible.`)) return;
    const res = await fetch('/api/files', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filePaths: selected.map(f => f.path) }),
    });
    const data = await res.json();
    setOpResult({ type: 'delete', ...data });
    setSelected([]);
    fetchFiles();
  }

  async function batchMove() {
    if (!modalDest.trim()) return;
    const res = await fetch('/api/files', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'batchMove', filePaths: selected.map(f => f.path), destinationDir: modalDest }),
    });
    const data = await res.json();
    setOpResult({ type: 'move', ...data });
    setModal(null);
    setModalDest('');
    setSelected([]);
    fetchFiles();
  }

  async function batchCopy() {
    if (!modalDest.trim()) return;
    const res = await fetch('/api/files', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'batchCopy', filePaths: selected.map(f => f.path), destinationDir: modalDest }),
    });
    const data = await res.json();
    setOpResult({ type: 'copy', ...data });
    setModal(null);
    setModalDest('');
    fetchFiles();
  }

  async function batchRenameOp() {
    if (!renamePattern.trim()) return;
    const res = await fetch('/api/files', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'batchRename', filePaths: selected.map(f => f.path), pattern: renamePattern }),
    });
    const data = await res.json();
    setOpResult({ type: 'rename', ...data });
    setModal(null);
    setSelected([]);
    fetchFiles();
  }

  async function createFolder(e) {
    e.preventDefault();
    if (!newFolderName.trim()) return;
    await fetch('/api/files', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'createFolder', parentPath: currentPath, folderName: newFolderName.trim() }),
    });
    setNewFolderName('');
    setModal(null);
    fetchFiles();
  }

  // ── Breadcrumb ───────────────────────────────────────────────────────────────

  const displayPath = currentPath || sandboxRoot || 'Documents';
  const pathParts = displayPath.replace(/\\/g, '/').split('/').filter(Boolean);

  const buildPathUpTo = (idx) => {
    // Reconstruit le chemin jusqu'à l'élément idx
    const raw = displayPath.replace(/\\/g, '/');
    const hasLeadingSlash = raw.startsWith('/');
    const parts = raw.split('/').filter(Boolean);
    const slice = parts.slice(0, idx + 1).join('/');
    return hasLeadingSlash ? '/' + slice : slice;
  };

  // ── Rendu fichier ────────────────────────────────────────────────────────────

  function renderFileItem(file, idx) {
    const isSelected = selected.some(f => f.path === file.path);
    const isRenaming = renamingFile === file.path;

    const commonStyle = {
      position: 'relative',
      cursor: 'pointer',
      userSelect: 'none',
      background: isSelected ? 'rgba(79, 140, 255,0.08)' : 'transparent',
      border: `1px solid ${isSelected ? 'rgba(79, 140, 255,0.25)' : 'transparent'}`,
      transition: 'all 0.15s',
    };

    if (viewMode === 'grid') {
      return (
        <div
          key={file.name + idx}
          className="card"
          onContextMenu={e => openContextMenu(e, file)}
          onClick={e => {
            if (selected.length > 0 || e.ctrlKey || e.metaKey) {
              toggleSelect(file, idx, e);
            } else if (file.type === 'dossier') {
              navigateTo(file.path);
            } else {
              openPreview(file);
            }
          }}
          onDoubleClick={() => { if (file.type === 'dossier') navigateTo(file.path); }}
          style={{
            ...commonStyle,
            cursor: 'pointer',
            textAlign: 'center', padding: '16px 12px',
            borderRadius: 'var(--radius-md)',
            animation: `slideUp 0.3s ease ${idx * 0.03}s both`,
          }}
        >
          {/* Checkbox */}
          <div
            onClick={e => toggleSelect(file, idx, e)}
            style={{
              position: 'absolute', top: '8px', left: '8px',
              width: '18px', height: '18px', borderRadius: '4px',
              background: isSelected ? 'var(--accent-primary)' : 'rgba(255,255,255,0.08)',
              border: `1.5px solid ${isSelected ? 'var(--accent-primary)' : 'rgba(255,255,255,0.2)'}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              opacity: isSelected || selected.length > 0 ? 1 : 0,
              transition: 'opacity 0.15s',
            }}
            className="file-checkbox"
          >
            {isSelected && <span style={{ color: 'white', fontSize: '11px', lineHeight: 1 }}>✓</span>}
          </div>
          <div style={{ fontSize: '2.5rem', marginBottom: '8px' }}>{FILE_ICONS[file.category] || '📎'}</div>
          {isRenaming ? (
            <input
              autoFocus value={renameValue}
              onChange={e => setRenameValue(e.target.value)}
              onBlur={confirmRename}
              onKeyDown={e => { if (e.key === 'Enter') confirmRename(); if (e.key === 'Escape') setRenamingFile(null); }}
              onClick={e => e.stopPropagation()}
              style={{
                width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--accent-primary)',
                borderRadius: '4px', color: 'var(--text-primary)', fontSize: 'var(--font-sm)',
                padding: '2px 6px', textAlign: 'center',
              }}
            />
          ) : (
            <>
              <div style={{ fontSize: 'var(--font-sm)', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginBottom: '4px' }} title={file.name}>{file.name}</div>
              <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>{file.size || '--'}</div>
            </>
          )}
        </div>
      );
    }

    // List view
    return (
      <div
        key={file.name + idx}
        className="glass"
        onContextMenu={e => openContextMenu(e, file)}
        onClick={e => {
          if (selected.length > 0 || e.ctrlKey || e.metaKey) {
            toggleSelect(file, idx, e);
          } else if (file.type === 'dossier') {
            navigateTo(file.path);
          } else {
            openPreview(file);
          }
        }}
        onDoubleClick={() => { if (file.type === 'dossier') navigateTo(file.path); }}
        style={{
          ...commonStyle,
          display: 'flex', alignItems: 'center', gap: '10px',
          padding: '9px 14px', borderRadius: 'var(--radius-md)',
          cursor: 'pointer',
          animation: `slideUp 0.2s ease ${idx * 0.02}s both`,
        }}
        onMouseEnter={e => { e.currentTarget.querySelector('.file-checkbox').style.opacity = 1; }}
        onMouseLeave={e => { if (!isSelected && selected.length === 0) e.currentTarget.querySelector('.file-checkbox').style.opacity = 0; }}
      >
        {/* Checkbox */}
        <div
          className="file-checkbox"
          onClick={e => toggleSelect(file, idx, e)}
          style={{
            width: '17px', height: '17px', borderRadius: '4px', flexShrink: 0,
            background: isSelected ? 'var(--accent-primary)' : 'rgba(255,255,255,0.06)',
            border: `1.5px solid ${isSelected ? 'var(--accent-primary)' : 'rgba(255,255,255,0.2)'}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            opacity: isSelected || selected.length > 0 ? 1 : 0,
            transition: 'opacity 0.15s, background 0.15s',
          }}
        >
          {isSelected && <span style={{ color: 'white', fontSize: '10px', lineHeight: 1 }}>✓</span>}
        </div>

        <span style={{ fontSize: '1.2rem', flexShrink: 0 }}>{FILE_ICONS[file.category] || '📎'}</span>

        {isRenaming ? (
          <input
            autoFocus value={renameValue}
            onChange={e => setRenameValue(e.target.value)}
            onBlur={confirmRename}
            onKeyDown={e => { if (e.key === 'Enter') confirmRename(); if (e.key === 'Escape') setRenamingFile(null); }}
            onClick={e => e.stopPropagation()}
            style={{
              flex: 1, background: 'var(--bg-primary)', border: '1px solid var(--accent-primary)',
              borderRadius: '4px', color: 'var(--text-primary)', fontSize: 'var(--font-sm)',
              padding: '2px 8px',
            }}
          />
        ) : (
          <span style={{ flex: 1, fontSize: 'var(--font-sm)', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{file.name}</span>
        )}

        <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', width: '72px', textAlign: 'right', flexShrink: 0 }}>{file.size || '--'}</span>
        <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', width: '96px', textAlign: 'right', flexShrink: 0 }}>
          {file.modified ? new Date(file.modified).toLocaleDateString('fr-FR') : ''}
        </span>
        <span className="badge badge-info" style={{ fontSize: '10px', flexShrink: 0 }}>{file.category}</span>
      </div>
    );
  }

  // ── JSX principal ────────────────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }} onClick={() => setContextMenu(null)}>

      {/* Header */}
      <div className="page-header">
        <h1>📁 Fichiers</h1>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn btn-secondary" onClick={() => setModal('newFolder')} style={{ fontSize: 'var(--font-xs)', padding: '7px 12px' }}>+ Dossier</button>
          <button className={`btn ${viewMode === 'grid' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setViewMode('grid')} style={{ padding: '8px 12px' }}>⊞</button>
          <button className={`btn ${viewMode === 'list' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setViewMode('list')} style={{ padding: '8px 12px' }}>☰</button>
        </div>
      </div>

      {/* Barre de navigation */}
      <div style={{ padding: '10px 24px', borderBottom: '1px solid var(--border)', display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="btn btn-ghost" onClick={goUp} title="Remonter">⬆️</button>

        {/* Breadcrumb cliquable */}
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'nowrap', overflow: 'hidden',
          padding: '6px 12px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border)', fontSize: 'var(--font-sm)',
        }}>
          {pathParts.map((part, i) => (
            <span key={i} style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
              {i > 0 && <span style={{ color: 'var(--text-muted)' }}>/</span>}
              <span
                style={{ color: i === pathParts.length - 1 ? 'var(--accent-primary)' : 'var(--text-secondary)', cursor: i < pathParts.length - 1 ? 'pointer' : 'default' }}
                onClick={() => i < pathParts.length - 1 && navigateTo(buildPathUpTo(i))}
              >
                {part}
              </span>
            </span>
          ))}
        </div>

        <form onSubmit={handleSearch} className="search-bar" style={{ maxWidth: '240px' }}>
          <span className="search-bar-icon">🔍</span>
          <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Rechercher..." />
          {searchQuery && <button type="button" onClick={() => { setSearchQuery(''); fetchFiles(); }} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}>×</button>}
        </form>
      </div>

      {/* Raccourcis */}
      <div style={{ padding: '8px 24px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {systemPaths && (
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {[
              { label: '🏠 Accueil', path: systemPaths.home },
              { label: '🖥️ Bureau', path: systemPaths.desktop },
              { label: '📄 Documents', path: systemPaths.documents },
              { label: '⬇️ Téléchargements', path: systemPaths.downloads },
              { label: '🖼️ Images', path: systemPaths.pictures },
            ].map(({ label, path }) => (
              <button key={path} className={`btn btn-ghost ${currentPath === path ? 'btn-primary' : ''}`}
                onClick={() => navigateTo(path)}
                style={{ fontSize: 'var(--font-xs)', padding: '5px 10px' }}>
                {label}
              </button>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: '8px' }}>
          <form onSubmit={goToPath} style={{ display: 'flex', gap: '8px', flex: 1 }}>
            <input className="input" value={pathInput} onChange={e => setPathInput(e.target.value)}
              placeholder={systemPaths ? `ex: ${systemPaths.desktop}` : 'Naviguer vers un chemin...'}
              style={{ flex: 1, padding: '7px 12px', fontSize: 'var(--font-sm)' }} />
            <button type="submit" className="btn btn-secondary" style={{ padding: '7px 14px' }}>Aller</button>
          </form>
        </div>
      </div>

      {/* Barre de sélection */}
      {files.length > 0 && !loading && (
        <div style={{ padding: '6px 24px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '12px', background: selected.length > 0 ? 'rgba(79, 140, 255,0.04)' : 'transparent' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
            <input type="checkbox" checked={selected.length === files.length && files.length > 0}
              onChange={selectAll} style={{ accentColor: 'var(--accent-primary)' }} />
            Tout sélectionner
          </label>
          {selected.length > 0 && (
            <span style={{ fontSize: 'var(--font-xs)', color: 'var(--accent-primary)', fontWeight: 600 }}>
              {selected.length} / {files.length} sélectionné{selected.length > 1 ? 's' : ''}
            </span>
          )}
          <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginLeft: 'auto' }}>
            Ctrl+clic ou Shift+clic pour sélectionner
          </span>
        </div>
      )}

      {/* Résultat opération */}
      {opResult && (
        <div style={{
          margin: '0 24px 0',
          padding: '10px 16px',
          background: opResult.success ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
          border: `1px solid ${opResult.success ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
          borderRadius: 'var(--radius-md)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          fontSize: 'var(--font-sm)',
          color: opResult.success ? '#22c55e' : '#ef4444',
        }}>
          <span>
            {opResult.type === 'delete' && `✅ ${opResult.deleted?.length || 0} élément(s) supprimé(s)`}
            {opResult.type === 'move'   && `✅ ${opResult.moved?.length || 0} élément(s) déplacé(s)`}
            {opResult.type === 'copy'   && `✅ ${opResult.copied?.length || 0} élément(s) copié(s)`}
            {opResult.type === 'rename' && `✅ ${opResult.renamed?.length || 0} fichier(s) renommé(s)`}
            {opResult.errors?.length > 0 && ` — ⚠️ ${opResult.errors.length} erreur(s)`}
          </span>
          <button onClick={() => setOpResult(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontSize: '1.1rem' }}>×</button>
        </div>
      )}

      {/* Contenu */}
      <div className="page-body" style={{ paddingTop: opResult ? '12px' : undefined }}>
        {loading ? (
          <div style={{ display: 'grid', gridTemplateColumns: viewMode === 'grid' ? 'repeat(auto-fill, minmax(160px, 1fr))' : '1fr', gap: '10px' }}>
            {[1,2,3,4,5,6].map(i => <div key={i} className="skeleton" style={{ height: viewMode === 'grid' ? '120px' : '46px' }} />)}
          </div>
        ) : files.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📂</div>
            <div className="empty-state-title">Dossier vide</div>
            <div className="empty-state-text">Ce répertoire ne contient aucun fichier</div>
          </div>
        ) : viewMode === 'grid' ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '12px' }}>
            {files.map((f, i) => renderFileItem(f, i))}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            {files.map((f, i) => renderFileItem(f, i))}
          </div>
        )}
      </div>

      {/* Toolbar batch flottante */}
      <BatchToolbar
        selected={selected}
        onDelete={batchDelete}
        onMove={() => { setModalDest(currentPath); setModal('move'); }}
        onCopy={() => { setModalDest(currentPath); setModal('copy'); }}
        onRename={() => setModal('rename')}
        onClear={() => setSelected([])}
      />

      {/* Context-menu clic droit */}
      {contextMenu && (
        <div
          onClick={e => e.stopPropagation()}
          style={{
            position: 'fixed', left: contextMenu.x, top: contextMenu.y,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)',
            zIndex: 3000, minWidth: '180px', padding: '6px',
            animation: 'scaleIn 0.15s ease',
          }}
        >
          {[
            ...(contextMenu.file.type !== 'dossier' ? [
              { label: '👁️ Ouvrir dans Marvin', action: () => { openPreview(contextMenu.file); setContextMenu(null); } },
              { label: '🪟 Ouvrir avec Windows', action: () => { openWithWindows(contextMenu.file.path); setContextMenu(null); } },
            ] : [
              { label: '📂 Ouvrir le dossier', action: () => { navigateTo(contextMenu.file.path); setContextMenu(null); } },
            ]),
            { label: '✏️ Renommer', action: () => startRename(contextMenu.file) },
            { label: '📤 Déplacer', action: () => { setSelected([contextMenu.file]); setModalDest(currentPath); setModal('move'); setContextMenu(null); } },
            { label: '📋 Copier', action: () => { setSelected([contextMenu.file]); setModalDest(currentPath); setModal('copy'); setContextMenu(null); } },
            { label: '📋 Copier le chemin', action: () => { navigator.clipboard.writeText(contextMenu.file.path).catch(() => {}); setContextMenu(null); } },
            { label: '🗑️ Supprimer', action: () => { singleDelete(contextMenu.file); setContextMenu(null); }, danger: true },
          ].map(item => (
            <button key={item.label} onClick={item.action} style={{
              display: 'flex', alignItems: 'center', gap: '8px',
              width: '100%', textAlign: 'left', padding: '8px 12px',
              background: 'none', border: 'none', cursor: 'pointer',
              color: item.danger ? '#ef4444' : 'var(--text-primary)',
              fontSize: 'var(--font-sm)', borderRadius: '6px',
              transition: 'background 0.1s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-glass)'}
            onMouseLeave={e => e.currentTarget.style.background = 'none'}
            >{item.label}</button>
          ))}
        </div>
      )}

      {/* Visionneuse de fichier */}
      {preview && (
        <div onClick={() => setPreview(null)} style={{ position: 'fixed', inset: 0, zIndex: 3500, background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div onClick={e => e.stopPropagation()} style={{ width: 'min(1000px, 94vw)', maxHeight: '90vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
            {/* En-tête */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontSize: '1.2rem' }}>{FILE_ICONS[preview.file.category] || '📄'}</span>
              <span style={{ flex: 1, fontWeight: 600, fontSize: 'var(--font-sm)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{preview.file.name}</span>
              <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => openWithWindows(preview.file.path)} title="Ouvrir avec l'application Windows par défaut">🪟 Ouvrir avec Windows</button>
              <a className="btn btn-ghost" style={{ fontSize: 12, textDecoration: 'none' }} href={`${BACKEND_URL}/api/files/raw?path=${encodeURIComponent(preview.file.path)}`} target="_blank" rel="noreferrer">⬇️ Télécharger</a>
              <button onClick={() => setPreview(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: '1.4rem', lineHeight: 1 }}>×</button>
            </div>
            {/* Corps */}
            <div style={{ flex: 1, overflow: 'auto', padding: 16, background: 'var(--bg-primary)' }}>
              {preview.loading && <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>⏳ Ouverture…</div>}
              {!preview.loading && preview.data && (() => {
                const d = preview.data;
                const rawUrl = `${BACKEND_URL}/api/files/raw?path=${encodeURIComponent(preview.file.path)}`;
                if (d.error) return <div style={{ color: '#f87171', fontSize: 13 }}>⚠️ {d.error}</div>;
                if (d.kind === 'image') return <div style={{ textAlign: 'center' }}><img src={rawUrl} alt={d.name} style={{ maxWidth: '100%', maxHeight: '74vh', borderRadius: 8 }} /></div>;
                if (d.kind === 'pdf') return <iframe src={rawUrl} title={d.name} style={{ width: '100%', height: '74vh', border: 'none', borderRadius: 8, background: '#fff' }} />;
                if (d.kind === 'text') return <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12.5, lineHeight: 1.6, color: 'var(--text-secondary)', fontFamily: d.lang && ['md','markdown','txt','log','csv'].includes(d.lang) ? 'inherit' : 'monospace' }}>{d.content || '(vide)'}</pre>;
                if (d.kind === 'table') return <TablePreview data={d.data} />;
                return (
                  <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 30 }}>
                    <div style={{ fontSize: 40, marginBottom: 10 }}>📦</div>
                    <div>Aperçu non disponible pour ce type de fichier.</div>
                    <button className="btn btn-primary" style={{ marginTop: 14 }} onClick={() => openWithWindows(preview.file.path)}>🪟 Ouvrir avec Windows</button>
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {/* Modal Déplacer */}
      {modal === 'move' && (
        <Modal title={`Déplacer ${selected.length} élément(s)`} onClose={() => setModal(null)}>
          <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-muted)', display: 'block', marginBottom: '8px' }}>
            Dossier de destination
          </label>
          <input className="input" value={modalDest} onChange={e => setModalDest(e.target.value)}
            placeholder="ex: C:\Users\...\Documents" style={{ width: '100%', marginBottom: '16px' }} />
          {systemPaths && (
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '16px' }}>
              {[systemPaths.desktop, systemPaths.documents, systemPaths.downloads].map(p => (
                <button key={p} onClick={() => setModalDest(p)} className="btn btn-ghost"
                  style={{ fontSize: '10px', padding: '3px 8px' }}>
                  {p.split(/[\\/]/).pop()}
                </button>
              ))}
            </div>
          )}
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary" onClick={() => setModal(null)}>Annuler</button>
            <button className="btn btn-primary" onClick={batchMove} disabled={!modalDest.trim()}>Déplacer</button>
          </div>
        </Modal>
      )}

      {/* Modal Copier */}
      {modal === 'copy' && (
        <Modal title={`Copier ${selected.length} élément(s)`} onClose={() => setModal(null)}>
          <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-muted)', display: 'block', marginBottom: '8px' }}>
            Dossier de destination
          </label>
          <input className="input" value={modalDest} onChange={e => setModalDest(e.target.value)}
            placeholder="ex: C:\Users\...\Documents" style={{ width: '100%', marginBottom: '16px' }} />
          {systemPaths && (
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '16px' }}>
              {[systemPaths.desktop, systemPaths.documents, systemPaths.downloads].map(p => (
                <button key={p} onClick={() => setModalDest(p)} className="btn btn-ghost"
                  style={{ fontSize: '10px', padding: '3px 8px' }}>
                  {p.split(/[\\/]/).pop()}
                </button>
              ))}
            </div>
          )}
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary" onClick={() => setModal(null)}>Annuler</button>
            <button className="btn btn-primary" onClick={batchCopy} disabled={!modalDest.trim()}>Copier</button>
          </div>
        </Modal>
      )}

      {/* Modal Renommage en série */}
      {modal === 'rename' && (
        <Modal title={`Renommer ${selected.length} fichier(s) en série`} onClose={() => setModal(null)}>
          <p style={{ fontSize: 'var(--font-sm)', color: 'var(--text-muted)', marginBottom: '12px' }}>
            Utilisez <code style={{ color: 'var(--accent-secondary)' }}>{'{n}'}</code> pour le numéro (1, 2, 3…) et <code style={{ color: 'var(--accent-secondary)' }}>{'{ext}'}</code> pour l'extension.
          </p>
          <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Pattern</label>
          <input className="input" value={renamePattern} onChange={e => setRenamePattern(e.target.value)}
            placeholder="ex: Photo_{n}" style={{ width: '100%', marginBottom: '8px' }} />
          <p style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
            Prévisualisation : {selected.slice(0, 3).map((f, i) => renamePattern.replace('{n}', i + 1).replace('{ext}', f.name.split('.').pop()) + '.' + f.name.split('.').pop()).join(', ')}{selected.length > 3 ? '…' : ''}
          </p>
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '16px' }}>
            <button className="btn btn-secondary" onClick={() => setModal(null)}>Annuler</button>
            <button className="btn btn-primary" onClick={batchRenameOp} disabled={!renamePattern.trim()}>Renommer</button>
          </div>
        </Modal>
      )}

      {/* Modal Nouveau dossier */}
      {modal === 'newFolder' && (
        <Modal title="Créer un dossier" onClose={() => setModal(null)}>
          <form onSubmit={createFolder}>
            <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-muted)', display: 'block', marginBottom: '8px' }}>Nom du dossier</label>
            <input className="input" autoFocus value={newFolderName} onChange={e => setNewFolderName(e.target.value)}
              placeholder="Nouveau dossier" style={{ width: '100%', marginBottom: '16px' }} />
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-secondary" onClick={() => setModal(null)}>Annuler</button>
              <button type="submit" className="btn btn-primary" disabled={!newFolderName.trim()}>Créer</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

export default function RedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/fichiers?tab=parcourir'); }, [router]);
  return null;
}
