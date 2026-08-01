'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Archive,
  Download,
  FolderInput,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from 'lucide-react';

export default function ConversationRow({
  conv,
  isActive,
  onSelect,
  onDelete,
  onAssign,
  onRename,
  onTogglePin,
  onArchive,
  onRestore,
  onExport,
  projects,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conv.title || '');
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const close = (event) => {
      if (!menuRef.current?.contains(event.target)) setMenuOpen(false);
    };
    const escape = (event) => {
      if (event.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [menuOpen]);

  const commit = () => {
    setEditing(false);
    const title = draft.trim();
    if (title && title !== conv.title) onRename(conv.id, title);
  };

  const run = (callback) => {
    setMenuOpen(false);
    callback();
  };

  return (
    <div
      role="listitem"
      data-conversation-id={conv.id}
      className={`conversation-row ${isActive ? 'conversation-row-active' : ''}`}
    >
      {editing ? (
        <input
          autoFocus
          value={draft}
          maxLength={200}
          aria-label="Nouveau titre de la conversation"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') commit();
            if (event.key === 'Escape') {
              setEditing(false);
              setDraft(conv.title || '');
            }
          }}
          onBlur={commit}
          className="conversation-row-input"
        />
      ) : (
        <button
          type="button"
          aria-current={isActive ? 'page' : undefined}
          aria-label={`Ouvrir la conversation ${conv.title || 'Sans titre'}`}
          onClick={() => onSelect(conv.id)}
          className="conversation-row-main"
        >
          {Boolean(conv.pinned) && <Pin size={12} aria-label="Épinglée" />}
          <span>{conv.title || 'Sans titre'}</span>
        </button>
      )}

      {!editing && (
        <div ref={menuRef} className="conversation-row-menu-shell">
          <button
            type="button"
            aria-label={`Actions pour ${conv.title || 'cette conversation'}`}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
            className="conversation-row-menu-trigger"
          >
            <MoreHorizontal size={17} aria-hidden="true" />
          </button>
          {menuOpen && (
            <div className="conversation-row-menu" role="group" aria-label="Actions de la conversation">
              <button type="button" onClick={() => run(() => onTogglePin(conv.id, Boolean(conv.pinned)))}>
                {conv.pinned ? <PinOff size={15} /> : <Pin size={15} />}
                {conv.pinned ? 'Désépingler' : 'Épingler'}
              </button>
              <button type="button" onClick={() => run(() => { setDraft(conv.title || ''); setEditing(true); })}>
                <Pencil size={15} /> Renommer
              </button>
              {projects.length > 0 && (
                <label className="conversation-row-project">
                  <span><FolderInput size={15} /> Déplacer</span>
                  <select
                    value={conv.project_id || 'none'}
                    aria-label={`Déplacer ${conv.title || 'cette conversation'} vers un projet`}
                    onChange={(event) => run(() => onAssign(conv.id, event.target.value))}
                  >
                    <option value="none">Sans projet</option>
                    {projects.map((project) => (
                      <option key={project.id} value={project.id}>{project.name}</option>
                    ))}
                  </select>
                </label>
              )}
              <button type="button" onClick={() => run(() => onExport(conv, 'markdown'))}>
                <Download size={15} /> Exporter en Markdown
              </button>
              <button type="button" onClick={() => run(() => onExport(conv, 'json'))}>
                <Download size={15} /> Exporter en JSON
              </button>
              <button type="button" onClick={() => run(() => onExport(conv, 'docx'))}>
                <Download size={15} /> Exporter en Word
              </button>
              <button type="button" onClick={() => run(() => onExport(conv, 'pdf'))}>
                <Download size={15} /> Exporter en PDF
              </button>
              {conv.archived_at ? (
                <button type="button" onClick={() => run(() => onRestore(conv.id))}>
                  <Archive size={15} /> Restaurer
                </button>
              ) : (
                <button type="button" onClick={() => run(() => onArchive(conv.id))}>
                  <Archive size={15} /> Archiver
                </button>
              )}
              <button type="button" className="danger" onClick={() => run(() => onDelete(conv.id))}>
                <Trash2 size={15} /> Supprimer définitivement
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
