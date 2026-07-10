'use client';
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';
import { marked } from 'marked';

function renderMarkdown(text) {
  try {
    const raw = marked(text || '');
    // Sanitize on client side only (DOMPurify requires window)
    if (typeof window !== 'undefined') {
      try {
        const DOMPurify = require('dompurify');
        return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
      } catch { /* dompurify not available, use raw */ }
    }
    return raw;
  } catch {
    return (text || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/^### (.+)$/gm, '<h3>$1</h3>')
      .replace(/^## (.+)$/gm, '<h2>$1</h2>')
      .replace(/^# (.+)$/gm, '<h1>$1</h1>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');
  }
}

function NotePreview({ content }) {
  const html = useMemo(() => renderMarkdown(content), [content]);
  return (
    <div
      style={{
        fontSize: 'var(--font-sm)', color: 'var(--text-primary)',
        lineHeight: 1.7, padding: '0',
      }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  // Le backend renvoie un timestamp SQLite UTC naïf ("2026-07-09 08:05:10", sans fuseau) —
  // `new Date()` l'interprète comme une heure LOCALE sans le 'Z', décalant l'affichage de
  // l'écart UTC de l'utilisateur (ex. "il y a 2h" sur une note tout juste créée). +'Z' force
  // l'interprétation UTC correcte.
  const d = new Date(dateStr.replace(' ', 'T') + 'Z');
  const now = new Date();
  const diffMs = now - d;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'À l\'instant';
  if (diffMin < 60) return `Il y a ${diffMin} min`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `Il y a ${diffH}h`;
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
}

export default function NotesPage() {
  const [notes, setNotes] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [search, setSearch] = useState('');
  const [previewMode, setPreviewMode] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const saveTimerRef = useRef(null);
  const isDirtyRef = useRef(false);

  const selectedNote = notes.find(n => n.id === selectedId) || null;

  const loadNotes = useCallback(async (q) => {
    try {
      const params = q ? `?q=${encodeURIComponent(q)}` : '';
      const res = await fetch(`/api/notes${params}`);
      const data = await res.json();
      setNotes(data.notes || []);
    } catch {
      setError('Impossible de charger les notes.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadNotes('');
  }, [loadNotes]);

  // Search debounce
  useEffect(() => {
    const timer = setTimeout(() => loadNotes(search), 300);
    return () => clearTimeout(timer);
  }, [search, loadNotes]);

  // When selected note changes, load its content into editor
  useEffect(() => {
    if (selectedNote) {
      setEditTitle(selectedNote.title);
      setEditContent(selectedNote.content);
      isDirtyRef.current = false;
    }
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-save debounce
  const scheduleSave = useCallback((id, title, content) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      if (!isDirtyRef.current) return;
      setSaving(true);
      try {
        await fetch('/api/notes', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'update', id, title, content }),
        });
        isDirtyRef.current = false;
        // Refresh note list silently
        const res = await fetch('/api/notes');
        const data = await res.json();
        setNotes(data.notes || []);
      } catch {
        setError('Sauvegarde échouée.');
      } finally {
        setSaving(false);
      }
    }, 1000);
  }, []);

  function handleTitleChange(val) {
    setEditTitle(val);
    isDirtyRef.current = true;
    if (selectedId) scheduleSave(selectedId, val, editContent);
  }

  function handleContentChange(val) {
    setEditContent(val);
    isDirtyRef.current = true;
    if (selectedId) scheduleSave(selectedId, editTitle, val);
  }

  async function createNote() {
    try {
      const res = await fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'create', title: 'Nouvelle note', content: '', tags: [] }),
      });
      const data = await res.json();
      if (data.note) {
        await loadNotes(search);
        setSelectedId(data.note.id);
      }
    } catch {
      setError('Création échouée.');
    }
  }

  async function deleteNote(id) {
    if (!confirm('Supprimer cette note ?')) return;
    try {
      await fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'delete', id }),
      });
      if (selectedId === id) {
        setSelectedId(null);
        setEditTitle('');
        setEditContent('');
      }
      loadNotes(search);
    } catch {
      setError('Suppression échouée.');
    }
  }

  async function togglePin(id, currentPinned) {
    try {
      await fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'update', id, pinned: !currentPinned }),
      });
      loadNotes(search);
    } catch {
      setError('Mise à jour échouée.');
    }
  }

  const inputStyle = {
    background: 'transparent', color: 'var(--text-primary)',
    border: 'none', outline: 'none',
    fontSize: 'var(--font-sm)', width: '100%',
  };

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 0px)', overflow: 'hidden' }}>
      {/* Left panel */}
      <div style={{
        width: '280px', flexShrink: 0,
        background: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '20px 16px 12px', borderBottom: '1px solid var(--border)' }}>
          <div className="page-header" style={{ marginBottom: '12px' }}>
            <h1 style={{
              fontSize: '18px', fontWeight: 700, margin: 0,
              background: 'var(--accent-gradient)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            }}>
              Notes
            </h1>
          </div>
          {/* Search */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            background: 'var(--bg-glass)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)', padding: '8px 12px',
          }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>🔍</span>
            <input
              placeholder="Rechercher..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ ...inputStyle, fontSize: 'var(--font-xs)' }}
            />
            {search && (
              <button onClick={() => setSearch('')} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--text-secondary)', fontSize: '12px', padding: 0,
              }}>✕</button>
            )}
          </div>
        </div>

        {/* New note button */}
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <button onClick={createNote} style={{
            width: '100%', background: 'var(--accent-gradient)',
            color: 'white', border: 'none', borderRadius: 'var(--radius-md)',
            padding: '8px', fontSize: 'var(--font-sm)', fontWeight: 600,
            cursor: 'pointer',
          }}>
            + Nouvelle note
          </button>
        </div>

        {/* Notes list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
          {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '20px' }}><LoadingRow /></div>
          ) : notes.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '20px', fontSize: 'var(--font-xs)' }}>
              {search ? 'Aucun résultat.' : 'Aucune note.'}
            </div>
          ) : (
            notes.map(note => {
              const isSelected = note.id === selectedId;
              const preview = (note.content || '').replace(/[#*`_\[\]]/g, '').slice(0, 80);
              return (
                <div
                  key={note.id}
                  onClick={() => setSelectedId(note.id)}
                  style={{
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    background: isSelected ? 'var(--bg-glass)' : 'transparent',
                    border: isSelected ? '1px solid var(--border)' : '1px solid transparent',
                    cursor: 'pointer', marginBottom: '4px',
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--bg-glass)'; }}
                  onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent'; }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '6px' }}>
                    <div style={{
                      fontSize: 'var(--font-sm)', fontWeight: 600,
                      color: 'var(--text-primary)',
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                      flex: 1,
                    }}>
                      {note.pinned && <span style={{ marginRight: '4px' }}>📌</span>}
                      {note.title}
                    </div>
                    <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                      <button
                        onClick={ev => { ev.stopPropagation(); togglePin(note.id, note.pinned); }}
                        title={note.pinned ? 'Désépingler' : 'Épingler'}
                        style={{
                          background: 'none', border: 'none', cursor: 'pointer',
                          color: note.pinned ? '#ffa502' : 'var(--text-secondary)',
                          fontSize: '12px', padding: '2px',
                          opacity: isSelected ? 1 : 0.4,
                        }}
                      >
                        📌
                      </button>
                      <button
                        onClick={ev => { ev.stopPropagation(); deleteNote(note.id); }}
                        title="Supprimer"
                        style={{
                          background: 'none', border: 'none', cursor: 'pointer',
                          color: 'var(--text-secondary)', fontSize: '11px', padding: '2px',
                          opacity: isSelected ? 1 : 0.4,
                        }}
                        onMouseEnter={e => e.currentTarget.style.color = 'var(--danger)'}
                        onMouseLeave={e => e.currentTarget.style.color = 'var(--text-secondary)'}
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                  <div style={{
                    fontSize: 'var(--font-xs)', color: 'var(--text-secondary)',
                    marginTop: '3px', overflow: 'hidden',
                    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                  }}>
                    {preview || 'Note vide'}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '4px', opacity: 0.7 }}>
                    {formatDate(note.updated_at)}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Right panel: editor */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-primary)' }}>
        {selectedNote ? (
          <>
            {/* Editor toolbar */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '12px',
              padding: '12px 20px', borderBottom: '1px solid var(--border)',
              background: 'var(--bg-secondary)',
            }}>
              <input
                value={editTitle}
                onChange={e => handleTitleChange(e.target.value)}
                style={{
                  ...inputStyle,
                  background: 'transparent',
                  fontSize: '16px', fontWeight: 700,
                  flex: 1,
                }}
                placeholder="Titre de la note"
              />
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                {saving && (
                  <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', opacity: 0.7 }}>
                    Sauvegarde...
                  </span>
                )}
                <button
                  onClick={() => setPreviewMode(!previewMode)}
                  style={{
                    background: previewMode ? 'var(--bg-glass)' : 'transparent',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-md)', padding: '5px 12px',
                    fontSize: 'var(--font-xs)', color: 'var(--text-secondary)',
                    cursor: 'pointer', transition: 'all 0.2s ease',
                  }}
                >
                  {previewMode ? 'Éditer' : 'Aperçu'}
                </button>
                <button
                  onClick={() => togglePin(selectedNote.id, selectedNote.pinned)}
                  title={selectedNote.pinned ? 'Désépingler' : 'Épingler'}
                  style={{
                    background: selectedNote.pinned ? 'rgba(255,165,2,0.15)' : 'transparent',
                    border: `1px solid ${selectedNote.pinned ? '#ffa502' : 'var(--border)'}`,
                    borderRadius: 'var(--radius-md)', padding: '5px 10px',
                    cursor: 'pointer', fontSize: '14px',
                  }}
                >
                  📌
                </button>
                <button
                  onClick={() => deleteNote(selectedNote.id)}
                  style={{
                    background: 'transparent', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-md)', padding: '5px 10px',
                    cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '14px',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--danger)'; e.currentTarget.style.color = 'var(--danger)'; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-secondary)'; }}
                >
                  🗑️
                </button>
              </div>
            </div>

            {/* Editor / Preview */}
            <div style={{ flex: 1, overflow: 'auto', padding: '24px' }}>
              {previewMode ? (
                <div style={{
                  maxWidth: '720px', margin: '0 auto',
                  lineHeight: 1.7,
                }}>
                  <NotePreview content={editContent} />
                </div>
              ) : (
                <textarea
                  value={editContent}
                  onChange={e => handleContentChange(e.target.value)}
                  placeholder="Commencez à écrire... (Markdown supporté)"
                  style={{
                    width: '100%', height: '100%', minHeight: '400px',
                    background: 'transparent', color: 'var(--text-primary)',
                    border: 'none', outline: 'none', resize: 'none',
                    fontSize: 'var(--font-sm)', lineHeight: 1.8,
                    fontFamily: 'inherit', boxSizing: 'border-box',
                    maxWidth: '720px', display: 'block', margin: '0 auto',
                  }}
                />
              )}
            </div>

            {/* Footer info */}
            <div style={{
              padding: '8px 20px', borderTop: '1px solid var(--border)',
              background: 'var(--bg-secondary)',
              display: 'flex', gap: '16px', alignItems: 'center',
            }}>
              <span style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.7 }}>
                Créé: {new Date(selectedNote.created_at.replace(' ', 'T') + 'Z').toLocaleString('fr-FR')}
              </span>
              <span style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.7 }}>
                Modifié: {new Date(selectedNote.updated_at.replace(' ', 'T') + 'Z').toLocaleString('fr-FR')}
              </span>
              <span style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.7 }}>
                {editContent.length} caractères
              </span>
            </div>
          </>
        ) : (
          <div style={{
            flex: 1, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            color: 'var(--text-secondary)',
          }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>📝</div>
            <div style={{ fontSize: 'var(--font-base)', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>
              Sélectionnez une note
            </div>
            <div style={{ fontSize: 'var(--font-sm)', textAlign: 'center', maxWidth: '280px' }}>
              Choisissez une note dans le panneau gauche, ou créez-en une nouvelle.
            </div>
            <button onClick={createNote} style={{
              marginTop: '20px', background: 'var(--accent-gradient)',
              color: 'white', border: 'none', borderRadius: 'var(--radius-md)',
              padding: '10px 20px', fontSize: 'var(--font-sm)', fontWeight: 600,
              cursor: 'pointer',
            }}>
              + Nouvelle note
            </button>
          </div>
        )}
      </div>

      {/* Error toast */}
      {error && (
        <div style={{
          position: 'fixed', bottom: '20px', right: '20px',
          background: 'rgba(255,71,87,0.95)', color: 'white',
          borderRadius: 'var(--radius-md)', padding: '12px 16px',
          fontSize: 'var(--font-sm)', zIndex: 9999,
          display: 'flex', gap: '10px', alignItems: 'center',
          boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
        }}>
          {error}
          <button onClick={() => setError('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'white', fontSize: '14px' }}>✕</button>
        </div>
      )}
    </div>
  );
}
