'use client';
import { useState, useCallback, useEffect, useMemo, useRef, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { LoadingRow } from '@/components/ui/Spinner';
import PrettyResult from '@/components/chat/PrettyResult';
import { useToast } from '@/components/ui/Toast';

import { BACKEND_URL } from '@/lib/backend';

// ══════════════════════════════════════════════════════════════════════════════
import {
  CATEGORIES,
  GROUPS,
  SYNTHETIC_CATEGORIES,
  applyOverride,
  groupOf,
  pickAutoIcon,
  pickCategoryId,
  prettifyToolId,
  schemaToParams,
} from '@/lib/tools/catalog';

function buildArgs(tool, values) {
  const args = {};
  (tool.params || []).forEach(p => {
    const v = values[p.name];
    if (p.type === 'tags' || p.type === 'numbers') {
      const arr = String(v).split(',').map(s => s.trim()).filter(Boolean);
      args[p.name] = p.type === 'numbers' ? arr.map(Number) : arr;
    } else if (p.type === 'jsonarray') {
      try { args[p.name] = JSON.parse(v || '[]'); } catch { args[p.name] = []; }
    } else if (p.type === 'checkbox') {
      args[p.name] = !!v;
    } else if (p.type === 'number') {
      args[p.name] = v !== '' ? Number(v) : undefined;
    } else if (v !== '' && v !== undefined) {
      args[p.name] = v;
    }
  });
  return args;
}

function ToolCard({ tool, categoryColor }) {
  const [expanded, setExpanded] = useState(false);
  const initValues = () => {
    const init = {};
    (tool.params || []).forEach(p => {
      init[p.name] = p.defaultValue ?? (p.type === 'checkbox' ? false : '');
    });
    return init;
  };
  const [values, setValues] = useState(initValues);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  // Templates
  const [templates, setTemplates] = useState([]);
  const [savingTpl, setSavingTpl] = useState(false);
  const [tplName, setTplName] = useState('');
  const [showTplSave, setShowTplSave] = useState(false);

  // Charger les templates de cet outil
  useEffect(() => {
    if (!expanded) return;
    fetch(`${BACKEND_URL}/api/templates?tool_name=${encodeURIComponent(tool.id)}`)
      .then(r => r.json())
      .then(setTemplates)
      .catch(() => {});
  }, [expanded, tool.id]);

  const handleChange = useCallback((name, val) => {
    setValues(prev => ({ ...prev, [name]: val }));
  }, []);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setResult(null);
    setError(null);
    const args = buildArgs(tool, values);
    try {
      const res = await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName: tool.id, args }),
      });
      const data = await res.json();
      if (data.result?.error) setError(data.result.error);
      else setResult(data.result);
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }, [tool, values]);

  const handleSaveTemplate = useCallback(async () => {
    if (!tplName.trim()) return;
    setSavingTpl(true);
    try {
      const args = buildArgs(tool, values);
      await fetch(`${BACKEND_URL}/api/templates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: tplName.trim(), tool_name: tool.id, args, category: tool.id }),
      });
      const updated = await fetch(`${BACKEND_URL}/api/templates?tool_name=${encodeURIComponent(tool.id)}`).then(r => r.json());
      setTemplates(updated);
      setTplName('');
      setShowTplSave(false);
    } catch {}
    setSavingTpl(false);
  }, [tool, values, tplName]);

  const handleLoadTemplate = useCallback((tpl) => {
    const merged = initValues();
    if (tpl.args) Object.assign(merged, tpl.args);
    setValues(merged);
  }, []);

  const handleDeleteTemplate = useCallback(async (tplId, e) => {
    e.stopPropagation();
    await fetch(`${BACKEND_URL}/api/templates/${tplId}`, { method: 'DELETE' });
    setTemplates(prev => prev.filter(t => t.id !== tplId));
  }, []);

  const hasRequired = (tool.params || []).filter(p => p.required).every(p => {
    const v = values[p.name];
    return v !== '' && v !== undefined && v !== null;
  });

  return (
    <div style={{
      background: 'var(--bg-glass)',
      border: `1px solid ${expanded ? categoryColor + '40' : 'rgba(255,255,255,0.06)'}`,
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
      transition: 'border-color 0.2s, box-shadow 0.2s',
      boxShadow: expanded ? `0 0 24px ${categoryColor}18` : 'none',
    }}>
      {/* ── En-tête ── */}
      <div
        onClick={() => setExpanded(e => !e)}
        style={{
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
          padding: '16px 18px', cursor: 'pointer', gap: '12px',
          background: expanded ? `${categoryColor}08` : 'transparent',
          transition: 'background 0.2s',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', flex: 1 }}>
          <span style={{
            fontSize: '1.4rem', lineHeight: 1, marginTop: '1px',
            filter: expanded ? 'none' : 'grayscale(0.3)',
          }}>
            {tool.icon}
          </span>
          <div style={{ flex: 1 }}>
            <div style={{
              fontWeight: 600, fontSize: 'var(--font-sm)',
              color: expanded ? categoryColor : 'var(--text-primary)',
              transition: 'color 0.2s',
            }}>
              {tool.name}
            </div>
            <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginTop: '3px', lineHeight: 1.45 }}>
              {tool.description}
            </div>
            {tool.requiresAuth && (
              <span style={{
                display: 'inline-block', marginTop: '6px',
                fontSize: '10px', padding: '2px 8px',
                borderRadius: '10px', fontWeight: 600,
                background: 'rgba(239,68,68,0.12)', color: '#f87171',
                border: '1px solid rgba(239,68,68,0.2)',
              }}>
                🔐 Connexion {tool.requiresAuth === 'google' ? 'Google' : 'Microsoft'} requise
              </span>
            )}
          </div>
        </div>
        <span style={{
          fontSize: '12px', color: 'var(--text-muted)', flexShrink: 0, marginTop: '3px',
          transform: expanded ? 'rotate(180deg)' : 'none',
          transition: 'transform 0.2s',
        }}>▼</span>
      </div>

      {/* ── Formulaire (expandable) ── */}
      {expanded && tool.custom === 'fileManager' && (
        <div style={{ padding: '0 12px 14px', borderTop: `1px solid ${categoryColor}20` }}>
          <FileManager accentColor={categoryColor} />
        </div>
      )}
      {expanded && tool.custom !== 'fileManager' && (
        <div style={{ padding: '0 18px 18px', borderTop: `1px solid ${categoryColor}20` }}>
          {/* Tips */}
          {tool.tips?.length > 0 && (
            <div style={{
              margin: '14px 0 12px',
              padding: '10px 14px',
              background: `${categoryColor}0d`,
              borderRadius: 'var(--radius-md)',
              borderLeft: `3px solid ${categoryColor}`,
            }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: categoryColor, marginBottom: '5px', letterSpacing: '0.06em' }}>
                💡 CONSEILS
              </div>
              {tool.tips.map((tip, i) => (
                <div key={i} style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  • {tip}
                </div>
              ))}
            </div>
          )}

          {/* Paramètres */}
          {(tool.params || []).length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: tool.tips?.length ? 0 : '14px' }}>
              {tool.params.map(param => (
                <ParamInput
                  key={param.name}
                  param={param}
                  value={values[param.name]}
                  onChange={val => handleChange(param.name, val)}
                  accentColor={categoryColor}
                />
              ))}
            </div>
          )}

          {/* Templates chargement */}
          {templates.length > 0 && (
            <div style={{ marginTop: '14px', display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>📂 TEMPLATES :</span>
              {templates.map(tpl => (
                <div key={tpl.id} style={{
                  display: 'inline-flex', alignItems: 'center', gap: '4px',
                  padding: '3px 10px 3px 8px',
                  background: `${categoryColor}15`, border: `1px solid ${categoryColor}30`,
                  borderRadius: '20px', cursor: 'pointer', fontSize: '11px', color: categoryColor,
                }}
                  onClick={() => handleLoadTemplate(tpl)}
                  title={`Charger "${tpl.name}"`}
                >
                  <span>{tpl.name}</span>
                  <span
                    onClick={e => handleDeleteTemplate(tpl.id, e)}
                    style={{ opacity: 0.5, fontSize: '10px', marginLeft: '2px' }}
                    title="Supprimer"
                  >✕</span>
                </div>
              ))}
            </div>
          )}

          {/* Bouton Exécuter + Sauvegarder template */}
          <div style={{ marginTop: '16px', display: 'flex', gap: '8px' }}>
            <button
              onClick={handleRun}
              disabled={running || !hasRequired}
              style={{
                flex: 1, padding: '10px',
                background: (running || !hasRequired) ? 'rgba(255,255,255,0.04)' : `linear-gradient(135deg, ${categoryColor}cc, ${categoryColor}88)`,
                color: (running || !hasRequired) ? 'var(--text-muted)' : 'white',
                border: `1px solid ${(running || !hasRequired) ? 'var(--border)' : categoryColor + '60'}`,
                borderRadius: 'var(--radius-md)',
                cursor: (running || !hasRequired) ? 'not-allowed' : 'pointer',
                fontWeight: 700, fontSize: 'var(--font-sm)',
                letterSpacing: '0.04em',
                transition: 'all 0.2s',
              }}
            >
              {running ? '⏳ En cours…' : `▶ Exécuter`}
            </button>
            {(tool.params || []).length > 0 && (
              <button
                onClick={() => setShowTplSave(s => !s)}
                title="Sauvegarder cette configuration comme template"
                style={{
                  padding: '10px 14px',
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-md)',
                  cursor: 'pointer', fontSize: '14px', color: 'var(--text-muted)',
                  transition: 'all 0.2s',
                }}
              >
                💾
              </button>
            )}
          </div>

          {/* Formulaire sauvegarde template */}
          {showTplSave && (
            <div style={{
              marginTop: '10px', display: 'flex', gap: '8px',
              padding: '10px 12px',
              background: 'rgba(255,255,255,0.03)',
              border: `1px solid ${categoryColor}30`,
              borderRadius: 'var(--radius-md)',
            }}>
              <input
                value={tplName}
                onChange={e => setTplName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSaveTemplate()}
                placeholder="Nom du template…"
                style={{
                  flex: 1, padding: '6px 10px', fontSize: '12px',
                  background: 'var(--bg-primary)', border: '1px solid var(--border)',
                  borderRadius: '6px', color: 'var(--text-primary)', outline: 'none',
                }}
              />
              <button
                onClick={handleSaveTemplate}
                disabled={!tplName.trim() || savingTpl}
                style={{
                  padding: '6px 14px', fontSize: '12px', fontWeight: 600,
                  background: tplName.trim() ? categoryColor : 'rgba(255,255,255,0.04)',
                  color: tplName.trim() ? 'white' : 'var(--text-muted)',
                  border: 'none', borderRadius: '6px', cursor: tplName.trim() ? 'pointer' : 'not-allowed',
                }}
              >
                {savingTpl ? '…' : 'Sauver'}
              </button>
            </div>
          )}

          {/* Résultat */}
          {(result || error) && (
            <ResultPanel result={result} error={error} accentColor={categoryColor} />
          )}
        </div>
      )}
    </div>
  );
}

// ── Champ de paramètre générique ──────────────────────────────────────────────

// Appelle un outil backend (pour les actions sur fichiers)
async function callBackendTool(toolName, args) {
  try {
    const res = await fetch(`${BACKEND_URL}/api/tools`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ toolName, args }),
    });
    return (await res.json()).result || {};
  } catch (e) { return { error: String(e) }; }
}

function FileAction({ icon, title, onClick }) {
  return (
    <button onClick={onClick} title={title}
      style={{ padding: '2px 6px', borderRadius: 4, border: '1px solid rgba(255,255,255,0.1)',
        background: 'rgba(255,255,255,0.05)', cursor: 'pointer', fontSize: 11, lineHeight: 1 }}
      onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.12)'}
      onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}>
      {icon}
    </button>
  );
}

// ── Explorateur de fichiers Windows (sélecteur) ───────────────────────────────
const FILE_ICONS = {
  pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', csv: '📊', ppt: '📙', pptx: '📙',
  png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️', svg: '🖼️', bmp: '🖼️',
  mp4: '🎬', mov: '🎬', avi: '🎬', mkv: '🎬', webm: '🎬', mp3: '🎵', wav: '🎵', flac: '🎵',
  zip: '🗜️', rar: '🗜️', '7z': '🗜️', txt: '📃', md: '📃', json: '🔣', xml: '🔣',
  exe: '⚙️', msi: '⚙️', bat: '⚙️', ps1: '⚙️', py: '🐍', js: '📜', html: '🌐', css: '🎨',
};
const fileIcon = (e) => e.is_dir ? '📁' : (FILE_ICONS[e.ext] || '📄');

function FilePicker({ open, mode = 'any', onSelect, onClose }) {
  const [cwd, setCwd] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('');

  const load = useCallback(async (path) => {
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName: 'pc_browse', args: { path: path || '' } }),
      });
      const d = (await res.json()).result || {};
      if (d.error && !d.entries) { setData({ ...d, entries: [] }); }
      else { setData(d); setCwd(d.path || path || ''); }
    } catch (e) { setData({ error: String(e), entries: [], roots: [] }); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (open) { setFilter(''); load(''); } }, [open, load]);
  if (!open) return null;

  const entries = (data?.entries || []).filter(e =>
    !filter || e.name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 2000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 'min(820px,95vw)', height: 'min(620px,90vh)', background: 'var(--bg-secondary)',
        border: '1px solid var(--border)', borderRadius: 12, display: 'flex', flexDirection: 'column',
        overflow: 'hidden', boxShadow: '0 12px 40px rgba(0,0,0,0.5)',
      }}>
        {/* Barre du haut : remonter + chemin + recherche */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
          <button onClick={() => load(data?.parent || '')} disabled={!data?.parent}
            title="Dossier parent" style={pkBtn(!data?.parent)}>⬆️</button>
          <button onClick={() => load('')} title="Accueil" style={pkBtn(false)}>🏠</button>
          <div style={{ flex: 1, fontFamily: 'monospace', fontSize: 12, color: 'var(--text-secondary)',
            background: 'var(--bg-primary)', padding: '6px 10px', borderRadius: 6, overflow: 'hidden',
            whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{cwd || '…'}</div>
          <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="🔍 filtrer"
            style={{ width: 130, padding: '6px 10px', background: 'var(--bg-primary)', border: '1px solid var(--border)',
              borderRadius: 6, color: 'var(--text-primary)', fontSize: 12, outline: 'none' }} />
          <button onClick={onClose} style={pkBtn(false)}>✕</button>
        </div>

        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          {/* Accès rapides */}
          <div style={{ width: 165, borderRight: '1px solid var(--border)', overflowY: 'auto', padding: 8, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 700, padding: '4px 6px', letterSpacing: '0.05em' }}>ACCÈS RAPIDE</div>
            {(data?.roots || []).map(r => (
              <div key={r.path} onClick={() => load(r.path)} style={{
                display: 'flex', gap: 7, alignItems: 'center', padding: '6px 8px', borderRadius: 6,
                cursor: 'pointer', fontSize: 12, color: 'var(--text-secondary)',
              }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-glass)'}
                 onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                <span>{r.icon}</span><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.label}</span>
              </div>
            ))}
          </div>

          {/* Liste des éléments */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {loading ? <div style={{ padding: 24 }}><LoadingRow /></div>
              : data?.error ? <div style={{ padding: 24, color: '#f87171', fontSize: 13 }}>⚠️ {data.error}</div>
              : entries.length === 0 ? <div style={{ padding: 24, color: 'var(--text-muted)', fontSize: 13 }}>Dossier vide</div>
              : entries.map(e => (
                <div key={e.path}
                  onClick={() => e.is_dir ? load(e.path) : onSelect(e.path)}
                  onDoubleClick={() => onSelect(e.path)}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 14px', cursor: 'pointer',
                    borderBottom: '1px solid var(--border)', fontSize: 13 }}
                  onMouseEnter={ev => ev.currentTarget.style.background = 'var(--bg-glass)'}
                  onMouseLeave={ev => ev.currentTarget.style.background = 'transparent'}>
                  <span style={{ fontSize: 16 }}>{fileIcon(e)}</span>
                  <span style={{ flex: 1, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.name}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{e.size_human}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', width: 105, textAlign: 'right' }}>{e.modified}</span>
                  {e.is_dir && <span style={{ color: 'var(--text-muted)' }}>›</span>}
                </div>
              ))}
          </div>
        </div>

        {/* Pied : sélectionner le dossier courant / annuler */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderTop: '1px solid var(--border)' }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {data?.folders ?? 0} dossiers · {data?.files ?? 0} fichiers — clic sur un dossier pour entrer, sur un fichier pour le choisir
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            {mode !== 'file' && (
              <button onClick={() => onSelect(cwd)} style={{ ...pkBtn(false), padding: '7px 14px', fontWeight: 600 }}>
                📁 Choisir ce dossier
              </button>
            )}
            <button onClick={onClose} style={{ ...pkBtn(false), padding: '7px 14px' }}>Annuler</button>
          </div>
        </div>
      </div>
    </div>
  );
}
const pkBtn = (disabled) => ({
  padding: '6px 10px', background: 'var(--bg-glass)', border: '1px solid var(--border)',
  borderRadius: 6, color: 'var(--text-secondary)', cursor: disabled ? 'not-allowed' : 'pointer',
  fontSize: 13, opacity: disabled ? 0.4 : 1,
});

// ── Gestionnaire de fichiers complet (naviguer + agir) ─────────────────────────
function FileManager({ accentColor }) {
  const [cwd, setCwd] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('');
  const [clip, setClip] = useState(null);   // { path, op:'move'|'copy', name }
  const { toast } = useToast();

  const flash = (m) => {
    const t = (m || '').trim();
    const isErr = t.startsWith('⚠️') || t.startsWith('❌') || /erreur/i.test(t);
    toast[isErr ? 'error' : 'success'](t.replace(/^(⚠️|❌)\s*/, ''));
  };
  const load = useCallback(async (path) => {
    setLoading(true);
    try {
      const d = await callBackendTool('pc_browse', { path: path || '' });
      if (d.entries) { setData(d); setCwd(d.path || path || ''); }
      else flash(d.error || 'Erreur');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(''); }, [load]);

  const act = async (name, args, okMsg) => {
    const r = await callBackendTool(name, args);
    if (r.error) flash('⚠️ ' + r.error);
    else { flash(okMsg || r.message || 'OK'); load(cwd); }
    return r;
  };
  const doRename = async (e) => {
    const nn = prompt('Nouveau nom :', e.name); if (!nn || nn === e.name) return;
    act('file_rename', { source: e.path, new_name: nn }, `Renommé en ${nn}`);
  };
  const doDelete = async (e) => {
    if (!confirm(`Supprimer « ${e.name} » ?\n${e.path}`)) return;
    act('file_delete', { path: e.path, confirmed: true }, 'Supprimé');
  };
  const doInfo = async (e) => {
    const r = await callBackendTool('file_info', { path: e.path });
    if (r.error) return flash(r.error);
    alert(`${e.name}\n\nChemin : ${e.path}\nTaille : ${r.size_human || r.size || '—'}\nModifié : ${r.modified || '—'}\nType : ${r.type || (e.is_dir ? 'dossier' : 'fichier')}`);
  };
  const paste = async () => {
    if (!clip) return;
    const dest = (cwd.replace(/[\\/]$/, '')) + '\\' + clip.name;
    await act(clip.op === 'move' ? 'file_move' : 'file_copy', { source: clip.path, destination: dest },
      clip.op === 'move' ? 'Déplacé' : 'Copié');
    setClip(null);
  };
  const newFolder = async () => {
    const n = prompt('Nom du nouveau dossier :'); if (!n) return;
    act('file_create_folder', { path: (cwd.replace(/[\\/]$/, '')) + '\\' + n }, `Dossier « ${n} » créé`);
  };

  const entries = (data?.entries || []).filter(e => !filter || e.name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div style={{ marginTop: 12 }}>
      {/* Barre d'outils */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        <button onClick={() => load(data?.parent || '')} disabled={!data?.parent} style={pkBtn(!data?.parent)} title="Parent">⬆️</button>
        <button onClick={() => load('')} style={pkBtn(false)} title="Accueil">🏠</button>
        <button onClick={() => load(cwd)} style={pkBtn(false)} title="Actualiser">🔄</button>
        <button onClick={newFolder} style={pkBtn(false)} title="Nouveau dossier">📁➕</button>
        {clip && <button onClick={paste} style={{ ...pkBtn(false), color: accentColor, fontWeight: 600 }}>📋 Coller ({clip.op === 'move' ? 'déplacer' : 'copier'}) « {clip.name} »</button>}
        <div style={{ flex: 1, fontFamily: 'monospace', fontSize: 11, color: 'var(--text-muted)', background: 'var(--bg-primary)', padding: '5px 8px', borderRadius: 5, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{cwd || '…'}</div>
        <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="🔍 filtrer" style={{ width: 110, padding: '5px 8px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text-primary)', fontSize: 12, outline: 'none' }} />
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        {/* Accès rapides */}
        <div style={{ width: 150, flexShrink: 0 }}>
          {(data?.roots || []).map(r => (
            <div key={r.path} onClick={() => load(r.path)} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '6px 8px', borderRadius: 5, cursor: 'pointer', fontSize: 12, color: 'var(--text-secondary)' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-glass)'} onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <span>{r.icon}</span><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.label}</span>
            </div>
          ))}
        </div>

        {/* Liste */}
        <div style={{ flex: 1, maxHeight: 420, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8 }}>
          {loading ? <div style={{ padding: 20 }}><LoadingRow /></div>
            : entries.length === 0 ? <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: 13 }}>Dossier vide</div>
            : entries.map(e => (
              <div key={e.path} className="fm-row" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderBottom: '1px solid var(--border)', fontSize: 13 }}
                onDoubleClick={() => e.is_dir ? load(e.path) : callBackendTool('pc_open_file', { path: e.path })}>
                <span style={{ fontSize: 15, cursor: 'pointer' }} onClick={() => e.is_dir && load(e.path)}>{fileIcon(e)}</span>
                <span style={{ flex: 1, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: e.is_dir ? 'pointer' : 'default' }}
                  onClick={() => e.is_dir && load(e.path)} title={e.path}>{e.name}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap', width: 70, textAlign: 'right' }}>{e.size_human}</span>
                <span style={{ display: 'flex', gap: 3, flexShrink: 0 }}>
                  {!e.is_dir && <FileAction icon="📂" title="Ouvrir" onClick={() => callBackendTool('pc_open_file', { path: e.path })} />}
                  <FileAction icon="🔎" title="Révéler" onClick={() => callBackendTool('pc_reveal', { path: e.path })} />
                  <FileAction icon="✏️" title="Renommer" onClick={() => doRename(e)} />
                  <FileAction icon="✂️" title="Couper" onClick={() => { setClip({ path: e.path, op: 'move', name: e.name }); flash('Coupé — naviguez puis Coller'); }} />
                  <FileAction icon="📑" title="Copier" onClick={() => { setClip({ path: e.path, op: 'copy', name: e.name }); flash('Copié — naviguez puis Coller'); }} />
                  <FileAction icon="ℹ️" title="Propriétés" onClick={() => doInfo(e)} />
                  <FileAction icon="🗑️" title="Supprimer" onClick={() => doDelete(e)} />
                </span>
              </div>
            ))}
        </div>
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6 }}>
        {data?.folders ?? 0} dossiers · {data?.files ?? 0} fichiers · double-clic pour ouvrir/entrer
      </div>
    </div>
  );
}

function ParamInput({ param, value, onChange, accentColor }) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const inputStyle = {
    width: '100%', padding: '8px 12px',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    color: 'var(--text-primary)',
    fontSize: 'var(--font-sm)',
    outline: 'none',
    boxSizing: 'border-box',
    transition: 'border-color 0.2s',
  };

  return (
    <div>
      <label style={{
        display: 'flex', gap: '5px', alignItems: 'center',
        fontSize: 'var(--font-xs)', fontWeight: 600,
        color: 'var(--text-secondary)', marginBottom: '5px',
      }}>
        {param.label}
        {param.required && <span style={{ color: accentColor, fontSize: '11px' }}>*</span>}
      </label>

      {param.type === 'select' && (
        <select value={value} onChange={e => onChange(e.target.value)} style={{ ...inputStyle, cursor: 'pointer' }}>
          {!param.required && <option value="">— Optionnel —</option>}
          {param.options.map(o =>
            typeof o === 'string'
              ? <option key={o} value={o}>{o}</option>
              : <option key={o.value} value={o.value}>{o.label}</option>
          )}
        </select>
      )}

      {param.type === 'textarea' && (
        <textarea
          value={value} onChange={e => onChange(e.target.value)}
          placeholder={param.placeholder}
          rows={4}
          style={{ ...inputStyle, resize: 'vertical', fontFamily: 'monospace', lineHeight: 1.5 }}
        />
      )}

      {param.type === 'checkbox' && (
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', marginTop: '2px' }}>
          <input
            type="checkbox"
            checked={!!value}
            onChange={e => onChange(e.target.checked)}
            style={{ width: '16px', height: '16px', accentColor: accentColor }}
          />
          <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>
            {value ? 'Activé' : 'Désactivé'}
          </span>
        </label>
      )}

      {param.type === 'path' && (
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            type="text" value={value} onChange={e => onChange(e.target.value)}
            placeholder={param.placeholder || 'Cliquez sur Parcourir…'}
            style={{ ...inputStyle, flex: 1 }}
            onFocus={e => e.target.style.borderColor = accentColor}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
          <button type="button" onClick={() => setPickerOpen(true)}
            title="Parcourir l'arborescence Windows"
            style={{ padding: '8px 12px', background: `${accentColor}1a`, border: `1px solid ${accentColor}40`,
              borderRadius: 'var(--radius-sm)', color: accentColor, cursor: 'pointer', fontSize: 13,
              whiteSpace: 'nowrap', fontWeight: 600 }}>
            📂 Parcourir
          </button>
          <FilePicker open={pickerOpen}
            onSelect={(p) => { onChange(p); setPickerOpen(false); }}
            onClose={() => setPickerOpen(false)} />
        </div>
      )}

      {['text', 'url', 'tags', 'numbers', 'jsonarray', 'number', 'date'].includes(param.type) && (
        <input
          type={param.type === 'date' ? 'date' : param.type === 'number' ? 'number' : 'text'}
          value={value}
          onChange={e => onChange(param.type === 'number' ? Number(e.target.value) : e.target.value)}
          placeholder={param.placeholder}
          min={param.min}
          max={param.max}
          style={inputStyle}
          onFocus={e => e.target.style.borderColor = accentColor}
          onBlur={e => e.target.style.borderColor = 'var(--border)'}
        />
      )}

      {(param.type === 'tags' || param.type === 'numbers') && (
        <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '3px' }}>
          Séparez les valeurs par des virgules
        </div>
      )}
    </div>
  );
}

// ── Affichage des résultats ───────────────────────────────────────────────────

function ResultPanel({ result, error, accentColor }) {
  const [collapsed, setCollapsed] = useState(false);
  const [showJson, setShowJson] = useState(false);

  if (error) return (
    <div style={{
      marginTop: '12px', padding: '12px 14px',
      background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
      borderRadius: 'var(--radius-md)', color: '#f87171', fontSize: 'var(--font-xs)',
    }}>
      ⚠️ {error}
    </div>
  );

  if (!result) return null;

  // Image (screenshot, infographie)
  const img = result.image || result.path?.match(/\.(png|jpg|jpeg|gif|webp)$/i)?.[0];
  const isImage = result.image?.startsWith('data:image') || false;

  // Fichiers listés
  const fileList = result.entries || result.files || result.results || result.items;
  const isFileList = Array.isArray(fileList);

  // Résultats web
  const webResults = result.results && Array.isArray(result.results) && result.results[0]?.url;

  return (
    <div style={{ marginTop: '12px' }}>
      {/* Header résultat */}
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px',
          background: `${accentColor}10`, borderRadius: collapsed ? 'var(--radius-md)' : 'var(--radius-md) var(--radius-md) 0 0',
          border: `1px solid ${accentColor}25`,
        }}
      >
        <span
          onClick={() => setCollapsed(c => !c)}
          style={{ fontSize: 'var(--font-xs)', fontWeight: 700, color: accentColor, cursor: 'pointer', flex: 1 }}
        >
          ✅ Résultat {collapsed ? '▼' : '▲'}
        </span>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            onClick={() => setShowJson(j => !j)}
            title={showJson ? 'Affichage lisible' : 'Voir le JSON brut'}
            style={{
              padding: '2px 8px', borderRadius: '4px',
              border: `1px solid ${showJson ? accentColor + '66' : 'rgba(255,255,255,0.1)'}`,
              background: showJson ? `${accentColor}22` : 'rgba(255,255,255,0.05)',
              color: showJson ? accentColor : 'var(--text-muted)', fontSize: '10px', cursor: 'pointer',
            }}
          >
            {showJson ? '✨ Lisible' : '{ } JSON'}
          </button>
          <button
            onClick={() => {
              const text = typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result);
              navigator.clipboard.writeText(text).catch(() => {});
            }}
            title="Copier en JSON"
            style={{
              padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.1)',
              background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
              fontSize: '10px', cursor: 'pointer',
            }}
          >
            📋 Copier
          </button>
          {result?.text && (
            <button
              onClick={() => navigator.clipboard.writeText(result.text).catch(() => {})}
              title="Copier le texte"
              style={{
                padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
                fontSize: '10px', cursor: 'pointer',
              }}
            >
              📝 Texte
            </button>
          )}
          {result?.path && (
            <button
              onClick={() => navigator.clipboard.writeText(result.path).catch(() => {})}
              title="Copier le chemin"
              style={{
                padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
                fontSize: '10px', cursor: 'pointer',
              }}
            >
              📂 Chemin
            </button>
          )}
        </div>
      </div>

      {!collapsed && showJson && (
        <pre style={{
          margin: 0, padding: '12px 14px', background: 'var(--bg-primary)',
          borderRadius: '0 0 var(--radius-md) var(--radius-md)',
          border: `1px solid ${accentColor}20`, borderTop: 'none',
          maxHeight: '420px', overflowY: 'auto', fontSize: '11px',
          color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result)}
        </pre>
      )}

      {!collapsed && !showJson && (
        <div style={{
          padding: '12px 14px',
          background: 'var(--bg-primary)',
          borderRadius: '0 0 var(--radius-md) var(--radius-md)',
          border: `1px solid ${accentColor}20`,
          borderTop: 'none',
          maxHeight: '380px', overflowY: 'auto',
        }}>
          {/* Succès simple */}
          {result.success && result.message && (
            <div style={{ color: '#4ade80', fontSize: 'var(--font-xs)', marginBottom: isFileList || isImage ? '10px' : 0 }}>
              ✓ {result.message}
              {result.path && !isImage && (
                <div style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: '10px', marginTop: '4px' }}>
                  📍 {result.path}
                </div>
              )}
            </div>
          )}

          {/* Image inline */}
          {isImage && (
            <img src={result.image} alt="Résultat"
              style={{ maxWidth: '100%', borderRadius: '6px', marginTop: '8px', cursor: 'pointer' }}
              onClick={() => window.open(result.image, '_blank')}
            />
          )}

          {/* Résultats de recherche web */}
          {webResults && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {result.results.map((r, i) => (
                <div key={i} style={{
                  padding: '8px 10px', borderRadius: '6px',
                  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)',
                }}>
                  <a href={r.url} target="_blank" rel="noopener noreferrer"
                    style={{ color: accentColor, fontWeight: 600, fontSize: 'var(--font-xs)', textDecoration: 'none' }}>
                    {r.title || r.url}
                  </a>
                  <div style={{ color: 'var(--text-muted)', fontSize: '10px', marginTop: '2px', fontFamily: 'monospace' }}>{r.url}</div>
                  {r.snippet && <div style={{ color: 'var(--text-secondary)', fontSize: '11px', marginTop: '4px', lineHeight: 1.4 }}>{r.snippet}</div>}
                </div>
              ))}
            </div>
          )}

          {/* Liste de fichiers */}
          {isFileList && !webResults && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {fileList.slice(0, 40).map((f, i) => {
                const fpath = (typeof f === 'object') ? (f.path || f.full_path || f.filepath || f.location) : null;
                return (
                  <div key={i} className="file-row" style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    gap: 8, padding: '5px 8px', borderRadius: '4px',
                    background: 'rgba(255,255,255,0.02)', fontSize: '11px',
                  }}>
                    <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}
                      title={fpath || ''}>
                      {f.is_dir ? '📁 ' : '📄 '}{f.name || (typeof f === 'string' ? f : fpath) || '—'}
                    </span>
                    {f.size_human && <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{f.size_human}</span>}
                    {fpath && (
                      <span style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                        <FileAction icon="📂" title="Ouvrir" onClick={() => callBackendTool('pc_open_file', { path: fpath })} />
                        <FileAction icon="🔎" title="Révéler dans l'Explorateur" onClick={() => callBackendTool('pc_reveal', { path: fpath })} />
                        <FileAction icon="📋" title="Copier le chemin" onClick={() => navigator.clipboard.writeText(fpath).catch(() => {})} />
                      </span>
                    )}
                  </div>
                );
              })}
              {fileList.length > 40 && (
                <div style={{ color: 'var(--text-muted)', fontSize: '10px', textAlign: 'center', marginTop: '4px' }}>
                  +{fileList.length - 40} éléments supplémentaires
                </div>
              )}
            </div>
          )}

          {/* Texte brut (read, system_info, etc.) */}
          {result.content && (
            <pre style={{
              fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.5,
              whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
            }}>
              {String(result.content).slice(0, 3000)}
              {String(result.content).length > 3000 && '\n…(tronqué)'}
            </pre>
          )}

          {/* OCR — texte extrait */}
          {result.text && !result.content && (
            <div>
              {result.model && (
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '8px', fontFamily: 'monospace' }}>
                  Modèle : {result.model} — {result.char_count} caractères extraits
                </div>
              )}
              <pre style={{
                fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.6,
                whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
                padding: '10px', background: 'rgba(255,255,255,0.03)',
                borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)',
              }}>
                {result.text}
              </pre>
            </div>
          )}

          {/* Réseau — output texte (ping, traceroute) */}
          {result.output && (
            <div>
              {result.summary && (
                <div style={{ marginBottom: '8px', padding: '6px 10px', background: `${accentColor}12`, borderRadius: '6px',
                  fontSize: '12px', color: accentColor, fontFamily: 'monospace' }}>
                  ⚡ {result.summary.trim()}
                </div>
              )}
              <pre style={{
                fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.5,
                whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
                maxHeight: '260px', overflowY: 'auto',
              }}>
                {result.output}
              </pre>
            </div>
          )}

          {/* Réseau — ports ouverts */}
          {result.open_ports !== undefined && (
            <div>
              <div style={{ fontSize: '12px', color: accentColor, marginBottom: '8px', fontFamily: 'monospace' }}>
                {result.summary}
              </div>
              {result.open_ports.length > 0 ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {result.open_ports.map(p => (
                    <span key={p} style={{
                      padding: '3px 10px', borderRadius: '12px', fontSize: '12px',
                      background: '#22c55e22', border: '1px solid #22c55e44', color: '#4ade80',
                      fontFamily: 'monospace',
                    }}>
                      :{p}
                    </span>
                  ))}
                </div>
              ) : (
                <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Aucun port ouvert trouvé.</div>
              )}
            </div>
          )}

          {/* Réseau — appareils ARP */}
          {result.devices !== undefined && Array.isArray(result.devices) && (
            <div>
              <div style={{ fontSize: '12px', color: accentColor, marginBottom: '10px', fontFamily: 'monospace' }}>
                {result.count} appareil{result.count > 1 ? 's' : ''} détecté{result.count > 1 ? 's' : ''}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {result.devices.map((d, i) => (
                  <div key={i} style={{
                    display: 'grid', gridTemplateColumns: '140px 160px 1fr',
                    gap: '8px', padding: '5px 8px', borderRadius: '5px',
                    background: 'rgba(255,255,255,0.02)', fontSize: '11px', fontFamily: 'monospace',
                  }}>
                    <span style={{ color: accentColor }}>{d.ip}</span>
                    <span style={{ color: 'var(--text-muted)' }}>{d.mac}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>{d.type}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Réseau — DNS */}
          {result.addresses && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>ADRESSES IP</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {result.addresses.map((a, i) => (
                    <span key={i} style={{
                      padding: '3px 10px', borderRadius: '12px',
                      background: `${accentColor}15`, border: `1px solid ${accentColor}30`,
                      color: accentColor, fontFamily: 'monospace', fontSize: '12px',
                    }}>{a}</span>
                  ))}
                </div>
              </div>
              {result.hostname && (
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                  ↩ {result.hostname}
                </div>
              )}
              {result.nslookup && (
                <pre style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'pre-wrap', margin: 0, maxHeight: '160px', overflowY: 'auto' }}>
                  {result.nslookup}
                </pre>
              )}
            </div>
          )}

          {/* Réseau — WHOIS */}
          {result.whois && (
            <pre style={{
              fontSize: '10px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap',
              fontFamily: 'monospace', margin: 0, maxHeight: '260px', overflowY: 'auto',
              lineHeight: 1.5,
            }}>
              {result.whois}
            </pre>
          )}

          {/* Couleur (color_tool) */}
          {result.hex && result.rgb && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                <div style={{
                  width: '60px', height: '60px', borderRadius: '10px',
                  background: result.hex, border: '2px solid rgba(255,255,255,0.1)',
                  flexShrink: 0,
                }} />
                <div style={{ flex: 1 }}>
                  {[
                    ['HEX', result.hex],
                    ['RGB', result.rgb_str],
                    ['HSL', result.hsl_str],
                    ['Luminance', result.luminance],
                    ['Clarté', result.brightness],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display: 'flex', gap: '8px', fontSize: '12px', marginBottom: '2px' }}>
                      <span style={{ color: 'var(--text-muted)', minWidth: '80px' }}>{k}</span>
                      <code style={{ color: accentColor }}>{v}</code>
                    </div>
                  ))}
                </div>
                {result.complementary && (
                  <div style={{ textAlign: 'center' }}>
                    <div style={{
                      width: '40px', height: '40px', borderRadius: '8px',
                      background: result.complementary, border: '2px solid rgba(255,255,255,0.1)',
                    }} />
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '4px' }}>Comp.</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* IP Info */}
          {result.country && result.city && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
              {[
                ['IP', result.ip], ['Pays', `${result.country_code} ${result.country}`],
                ['Ville', result.city], ['Région', result.region],
                ['Fuseau', result.timezone], ['ISP', result.isp],
                ['ASN', result.asn], ['Lat/Lon', `${result.latitude}, ${result.longitude}`],
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{k}</span>
                  <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: '11px' }}>{v}</span>
                </div>
              ))}
            </div>
          )}

          {/* Hash */}
          {result.hash && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{result.algorithm} ({result.source})</div>
              <code style={{
                wordBreak: 'break-all', padding: '8px 10px', background: 'rgba(255,255,255,0.04)',
                borderRadius: '6px', fontSize: '12px', color: accentColor, fontFamily: 'monospace',
                border: '1px solid rgba(255,255,255,0.06)',
              }}>
                {result.hash}
              </code>
            </div>
          )}

          {/* URL Analyze */}
          {result.status && result.url && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{
                  padding: '2px 10px', borderRadius: '12px', fontWeight: 700,
                  background: result.status < 400 ? '#22c55e22' : '#ef444422',
                  color: result.status < 400 ? '#4ade80' : '#f87171',
                  border: `1px solid ${result.status < 400 ? '#22c55e44' : '#ef444444'}`,
                }}>
                  HTTP {result.status}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>{result.response_time_ms}ms</span>
                {result.server && <span style={{ color: 'var(--text-muted)' }}>🖥️ {result.server}</span>}
              </div>
              {result.title && <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{result.title}</div>}
              {result.description && <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>{result.description}</div>}
              <a href={result.url} target="_blank" rel="noopener noreferrer" style={{ color: accentColor, fontSize: '11px', wordBreak: 'break-all' }}>{result.url}</a>
            </div>
          )}

          {/* PDF Info */}
          {result.pages !== undefined && result.file && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
              {[
                ['Fichier', result.file?.split('\\').pop()],
                ['Pages', result.pages],
                ['Taille', `${result.size_kb} Ko`],
                ['Chiffré', result.encrypted ? 'Oui' : 'Non'],
                ['Titre', result.title],
                ['Auteur', result.author],
                ['Créateur', result.creator],
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{k}</span>
                  <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: '11px', wordBreak: 'break-all' }}>{v}</span>
                </div>
              ))}
            </div>
          )}

          {/* XLSX / CSV data table */}
          {result.headers && result.data && Array.isArray(result.data) && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
                <thead>
                  <tr>
                    {result.headers.map(h => (
                      <th key={h} style={{
                        padding: '5px 8px', textAlign: 'left', borderBottom: `1px solid ${accentColor}30`,
                        color: accentColor, fontWeight: 700, whiteSpace: 'nowrap',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.data.slice(0, 20).map((row, i) => (
                    <tr key={i} style={{ background: i % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'transparent' }}>
                      {result.headers.map(h => (
                        <td key={h} style={{
                          padding: '4px 8px', color: 'var(--text-secondary)',
                          borderBottom: '1px solid rgba(255,255,255,0.04)',
                          maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {row[h] ?? ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.data.length > 20 && (
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textAlign: 'center', marginTop: '6px' }}>
                  +{result.data.length - 20} lignes supplémentaires
                </div>
              )}
            </div>
          )}

          {/* QR Code image */}
          {result.output && result.size_px && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'flex-start' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                💾 Sauvegardé : <code style={{ color: accentColor }}>{result.output?.split('\\').pop()}</code>
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                {result.size_px?.[0]}×{result.size_px?.[1]} px · {result.size_kb} Ko
              </div>
            </div>
          )}

          {/* Base64 result */}
          {result.action === 'encode' && result.result && !result.hex && (
            <code style={{
              wordBreak: 'break-all', padding: '8px 10px', background: 'rgba(255,255,255,0.04)',
              borderRadius: '6px', fontSize: '12px', color: accentColor, fontFamily: 'monospace',
              border: '1px solid rgba(255,255,255,0.06)', display: 'block',
            }}>
              {result.result}
            </code>
          )}

          {/* Translation result */}
          {result.translated && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '11px' }}>
                {result.source_lang?.toUpperCase()} → {result.target_lang?.toUpperCase()}
              </div>
              <div style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                {result.translated}
              </div>
            </div>
          )}

          {/* Password result */}
          {result.password && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <code style={{
                padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px',
                fontSize: '16px', color: accentColor, fontFamily: 'monospace', letterSpacing: '0.05em',
                border: `1px solid ${accentColor}30`,
              }}>
                {result.password}
              </code>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                Entropie : {result.entropy_bits} bits · Force : {result.strength}
              </div>
            </div>
          )}

          {/* Code Python result */}
          {result.stdout !== undefined && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {result.stdout && result.stdout !== '(aucune sortie)' && (
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>STDOUT</div>
                  <pre style={{
                    padding: '8px 12px', background: '#0d1117', borderRadius: '6px',
                    fontSize: '12px', color: '#c9d1d9', fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap', margin: 0, maxHeight: '200px', overflowY: 'auto',
                    border: '1px solid rgba(228, 228, 231,0.08)',
                  }}>
                    {result.stdout}
                  </pre>
                </div>
              )}
              {result.stderr && (
                <div>
                  <div style={{ fontSize: '10px', color: '#f87171', marginBottom: '4px' }}>STDERR</div>
                  <pre style={{ padding: '8px 12px', background: '#1a0808', borderRadius: '6px', fontSize: '11px', color: '#f87171', fontFamily: 'monospace', whiteSpace: 'pre-wrap', margin: 0 }}>
                    {result.stderr}
                  </pre>
                </div>
              )}
              {result.result !== null && result.result !== undefined && (
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '12px' }}>
                  <span style={{ color: 'var(--text-muted)' }}>result =</span>
                  <code style={{ color: accentColor, fontFamily: 'monospace' }}>{String(result.result)}</code>
                </div>
              )}
              {result.vars && Object.keys(result.vars).length > 0 && (
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  Variables: {Object.entries(result.vars).map(([k,v]) => `${k}=${v}`).join(', ')}
                </div>
              )}
            </div>
          )}

          {/* JSON brut fallback — pour tout le reste */}
          {!result.content && !result.text && !result.output && result.open_ports === undefined
           && !result.devices && !result.addresses && !result.whois
           && !result.hex && !result.country && !result.hash && !result.status
           && !result.pages && !result.headers && !result.translated && !result.password
           && result.stdout === undefined
           && !(result.success && result.message) && !isFileList && !webResults && !isImage && (
            <PrettyResult result={result} />
          )}
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Page principale
// ══════════════════════════════════════════════════════════════════════════════

function OutilsPageInner() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState('infographie');
  const [activeGroup, setActiveGroup] = useState(() => groupOf('infographie'));
  const [search, setSearch] = useState(() => searchParams.get('q') || '');

  // v2.157/v2.158 — complète le catalogue statique avec les outils backend absents d'ici,
  // auto-catégorisés par préfixe (voir pickCategoryId/pickAutoIcon ci-dessus) plutôt que
  // dans un vrac unique. Best-effort : si l'appel échoue, le catalogue statique reste
  // utilisable tel quel, rien ne casse.
  const [extraTools, setExtraTools] = useState([]);
  useEffect(() => {
    const curatedIds = new Set(CATEGORIES.flatMap(c => c.tools.map(t => t.id)));
    fetch(`${BACKEND_URL}/api/tools/list`)
      .then(r => r.json())
      .then(d => {
        const extra = (d.tools || [])
          .map(t => t.function)
          .filter(f => f && f.name && !curatedIds.has(f.name))
          .map(f => applyOverride({
            id: f.name, icon: pickAutoIcon(f.name), name: prettifyToolId(f.name),
            description: f.description || '', params: schemaToParams(f.parameters),
            _categoryId: pickCategoryId(f.name),
          }));
        setExtraTools(extra);
      })
      .catch(() => {});
  }, []);

  // Regroupe les outils manquants par catégorie cible, puis fusionne CHAQUE catégorie
  // statique concernée (copie, tools[] curatés d'abord + auto ajoutés ensuite — le tableau
  // CATEGORIES original n'est jamais muté). Les catégories synthétiques (facturation, quiz)
  // ne sont créées que si au moins un outil y atterrit réellement.
  const categories = useMemo(() => {
    if (!extraTools.length) return CATEGORIES;
    const byCategory = new Map();
    for (const t of extraTools) {
      const { _categoryId, ...tool } = t;
      if (!byCategory.has(_categoryId)) byCategory.set(_categoryId, []);
      byCategory.get(_categoryId).push(tool);
    }
    const merged = CATEGORIES.map(cat => {
      const extras = byCategory.get(cat.id);
      return extras ? { ...cat, tools: [...cat.tools, ...extras] } : cat;
    });
    const staticIds = new Set(CATEGORIES.map(c => c.id));
    for (const [catId, tools] of byCategory) {
      if (!staticIds.has(catId) && SYNTHETIC_CATEGORIES[catId]) {
        merged.push({ ...SYNTHETIC_CATEGORIES[catId], tools });
      }
    }
    return merged;
  }, [extraTools]);

  const groups = useMemo(() => {
    if (!extraTools.length) return GROUPS;
    const presentIds = new Set(categories.map(c => c.id));
    return GROUPS.map(g => {
      const toAdd = Object.keys(SYNTHETIC_CATEGORIES).filter(id => presentIds.has(id) && !g.categories.includes(id));
      // Les deux catégories synthétiques actuelles (facturation, quiz) sont de l'organisation.
      return g.id === 'organisation' && toAdd.length ? { ...g, categories: [...g.categories, ...toAdd] } : g;
    });
  }, [extraTools, categories]);

  const activeCategory = categories.find(c => c.id === activeTab) || categories[0];
  const totalTools = categories.reduce((acc, c) => acc + c.tools.length, 0);
  const groupCategories = categories.filter(c => groups.find(g => g.id === activeGroup)?.categories.includes(c.id));

  const selectGroup = (groupId) => {
    setActiveGroup(groupId);
    const first = groups.find(g => g.id === groupId)?.categories[0];
    if (first) setActiveTab(first);
  };

  // Search: filter across all categories
  const searchLower = search.trim().toLowerCase();
  const searchResults = searchLower
    ? categories.flatMap(cat =>
        cat.tools
          .filter(t =>
            t.name.toLowerCase().includes(searchLower) ||
            t.description?.toLowerCase().includes(searchLower) ||
            t.id.toLowerCase().includes(searchLower)
          )
          .map(t => ({ ...t, _category: cat }))
      )
    : null;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ─── En-tête ─────────────────────────────────────────────────────── */}
      <div className="page-header" style={{ borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              🔧 Boîte à outils
            </h1>
            <p style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', margin: '4px 0 0', letterSpacing: '0.03em' }}>
              {totalTools} outils disponibles — exécutables directement ou via Marvin
            </p>
          </div>
          {/* Search bar */}
          <div style={{ position: 'relative', flexShrink: 0 }}>
            <span style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: '14px', pointerEvents: 'none' }}>🔍</span>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={`Rechercher parmi ${totalTools} outils…`}
              style={{
                padding: '8px 12px 8px 32px',
                background: 'var(--bg-glass)',
                border: search ? '1px solid var(--accent)' : '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                fontSize: 'var(--font-sm)',
                width: '280px',
                outline: 'none',
              }}
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                style={{ position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '14px', lineHeight: 1 }}
              >✕</button>
            )}
          </div>
        </div>
      </div>

      {/* ─── Familles (niveau 1, hidden during search) ─────────────────────── */}
      <div style={{
        display: searchResults !== null ? 'none' : 'flex',
        gap: '6px', padding: '12px 24px 0', flexShrink: 0,
      }}>
        {groups.map(g => {
          const isActive = g.id === activeGroup;
          const count = g.categories.reduce((acc, cid) => acc + (categories.find(c => c.id === cid)?.tools.length || 0), 0);
          return (
            <button
              key={g.id}
              onClick={() => selectGroup(g.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: '7px',
                padding: '7px 14px', border: `1px solid ${isActive ? 'var(--accent-primary)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-full)', cursor: 'pointer',
                background: isActive ? 'rgba(79, 140, 255,0.12)' : 'transparent',
                color: isActive ? 'var(--accent-primary)' : 'var(--text-secondary)',
                fontWeight: isActive ? 700 : 500, fontSize: 'var(--font-xs)',
                transition: 'all 0.15s',
              }}
            >
              <span>{g.icon}</span>
              <span>{g.label}</span>
              <span style={{ fontSize: '10px', opacity: 0.6 }}>{count}</span>
            </button>
          );
        })}
      </div>

      {/* ─── Catégories du groupe actif (niveau 2, hidden during search) ───── */}
      <div style={{
        display: searchResults !== null ? 'none' : 'flex',
        gap: '4px', padding: '10px 24px 0',
        overflowX: 'auto', flexShrink: 0,
        borderBottom: '1px solid var(--border)',
        scrollbarWidth: 'none',
      }}>
        {groupCategories.map(cat => {
          const isActive = cat.id === activeTab;
          return (
            <button
              key={cat.id}
              onClick={() => setActiveTab(cat.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '8px 16px', border: 'none', borderRadius: 'var(--radius-md) var(--radius-md) 0 0',
                cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
                background: isActive ? 'var(--bg-glass)' : 'transparent',
                color: isActive ? cat.color : 'var(--text-muted)',
                borderBottom: isActive ? `2px solid ${cat.color}` : '2px solid transparent',
                fontWeight: isActive ? 700 : 400,
                fontSize: 'var(--font-xs)',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.color = 'var(--text-secondary)'; }}
              onMouseLeave={e => { if (!isActive) e.currentTarget.style.color = 'var(--text-muted)'; }}
            >
              <span>{cat.icon}</span>
              <span>{cat.label}</span>
              <span style={{
                fontSize: '10px', padding: '1px 6px', borderRadius: '10px',
                background: isActive ? `${cat.color}20` : 'rgba(255,255,255,0.05)',
                color: isActive ? cat.color : 'var(--text-muted)',
              }}>
                {cat.tools.length}
              </span>
            </button>
          );
        })}
      </div>

      {/* ─── Contenu ─────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px 32px' }}>

        {/* ── Search results ───────────────────────────────────────────── */}
        {searchResults !== null ? (
          <>
            <div style={{
              display: 'flex', alignItems: 'center', gap: '10px',
              padding: '10px 14px', marginBottom: '16px',
              background: 'rgba(79, 140, 255,0.06)',
              border: '1px solid rgba(79, 140, 255,0.2)',
              borderRadius: 'var(--radius-md)',
              fontSize: 'var(--font-xs)', color: '#4f8cff',
            }}>
              🔍 <strong>{searchResults.length}</strong> outil{searchResults.length !== 1 ? 's' : ''} correspondant{searchResults.length !== 1 ? 's' : ''} à «&nbsp;{search}&nbsp;»
            </div>
            {searchResults.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
                Aucun outil ne correspond à cette recherche.
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '14px' }}>
                {searchResults.map(tool => (
                  <ToolCard key={tool.id} tool={tool} categoryColor={tool._category.color} />
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            {/* ── Category header ───────────────────────────────────────── */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '14px',
              padding: '14px 18px', marginBottom: '20px',
              background: `${activeCategory.color}0a`,
              borderRadius: 'var(--radius-lg)',
              border: `1px solid ${activeCategory.color}22`,
            }}>
              <span style={{ fontSize: '2rem' }}>{activeCategory.icon}</span>
              <div>
                <div style={{ fontWeight: 700, fontSize: 'var(--font-sm)', color: activeCategory.color }}>
                  {activeCategory.label}
                </div>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', marginTop: '2px' }}>
                  {activeCategory.description}
                </div>
              </div>
              <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 800, color: activeCategory.color }}>
                  {activeCategory.tools.length}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>outil{activeCategory.tools.length > 1 ? 's' : ''}</div>
              </div>
            </div>

            {/* ── Tools grid ────────────────────────────────────────────── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '14px' }}>
              {activeCategory.tools.map(tool => (
                <ToolCard key={tool.id} tool={tool} categoryColor={activeCategory.color} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function OutilsPage() {
  return (
    <Suspense fallback={null}>
      <OutilsPageInner />
    </Suspense>
  );
}
