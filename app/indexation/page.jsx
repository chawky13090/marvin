'use client';

import { useRouter } from 'next/navigation';
import { useState, useEffect, useCallback, useRef } from 'react';
import { useToast } from '@/components/ui/Toast';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

const FILE_TYPES = [
  { v: '', label: 'Tous' },
  { v: 'pdf', label: 'PDF' },
  { v: 'docx', label: 'Word' },
  { v: 'xlsx', label: 'Excel/CSV' },
  { v: 'text', label: 'Texte/MD' },
];

function fmtSize(kb) {
  if (!kb) return '';
  if (kb < 1024) return Math.round(kb) + ' Ko';
  return (kb / 1024).toFixed(1) + ' Mo';
}

export function IndexationView() {
  const [docs, setDocs] = useState([]);

  // Recherche PC
  const [mode, setMode] = useState('content'); // content | name
  const [ftype, setFtype] = useState('');
  const [q, setQ] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState(null);
  const [busyPath, setBusyPath] = useState('');

  // Indexation par chemin / upload
  const [pathInput, setPathInput] = useState('');
  const [indexing, setIndexing] = useState(false);
  const fileRef = useRef(null);

  // Interrogation
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState(null);

  const { toast } = useToast();
  const flash = (m) => {
    const t = (m || '').trim();
    const type = t.startsWith('❌') ? 'error' : t.startsWith('⚠️') ? 'warning' : (t.startsWith('✅') || t.startsWith('📄')) ? 'success' : 'info';
    toast[type](t.replace(/^(✅|❌|⚠️|📄)\s*/, ''));
  };

  const loadDocs = useCallback(async () => {
    try { const r = await fetch(`${BACKEND}/api/documents`).then(r => r.json()); setDocs(r.documents || []); } catch {}
  }, []);
  useEffect(() => { loadDocs(); }, [loadDocs]);

  async function search(e) {
    e?.preventDefault();
    if (!q.trim() && mode === 'content') return;
    setSearching(true); setResults(null);
    const ep = mode === 'content' ? 'search-content' : 'search';
    const url = `${BACKEND}/api/system/${ep}?query=${encodeURIComponent(q.trim())}&file_type=${ftype}&max_results=40`;
    try {
      const r = await fetch(url).then(r => r.json());
      setResults(r.error ? { error: r.error } : r);
    } catch { setResults({ error: 'Backend injoignable' }); }
    setSearching(false);
  }

  async function indexPath(path) {
    if (!path?.trim()) return;
    setBusyPath(path); setIndexing(true);
    try {
      const r = await fetch(`${BACKEND}/api/documents/index`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: path.trim() }) }).then(r => r.json());
      flash(r.detail ? '❌ ' + r.detail : `📄 ${r.message || 'Indexé'}`);
    } catch { flash('❌ Échec de l\'indexation'); }
    setBusyPath(''); setIndexing(false);
    loadDocs();
  }

  async function openPath(path) {
    try {
      await fetch(`${BACKEND}/api/tools`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ toolName: 'pc_open_file', args: { path } }) });
    } catch {}
  }

  async function uploadFiles(files) {
    if (!files || !files.length) return;
    setIndexing(true);
    for (const file of files) {
      try {
        const fd = new FormData(); fd.append('file', file);
        const r = await fetch(`${BACKEND}/api/documents/upload`, { method: 'POST', body: fd }).then(r => r.json());
        flash(r.detail ? '❌ ' + r.detail : `📄 ${r.message || file.name + ' indexé'}`);
      } catch { flash('❌ Échec de l\'envoi'); }
    }
    setIndexing(false);
    if (fileRef.current) fileRef.current.value = '';
    loadDocs();
  }

  async function forget(id) {
    try { await fetch(`${BACKEND}/api/documents/${id}`, { method: 'DELETE' }); flash('🗑️ Document retiré'); loadDocs(); } catch {}
  }

  async function ask(e) {
    e?.preventDefault();
    if (!question.trim()) return;
    setAsking(true); setAnswer(null);
    try {
      const r = await fetch(`${BACKEND}/api/documents/ask`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: question.trim() }) }).then(r => r.json());
      setAnswer(r.detail ? { answer: '⚠️ ' + r.detail, sources: [] } : r);
    } catch { setAnswer({ answer: '❌ Backend injoignable', sources: [] }); }
    setAsking(false);
  }

  const indexedPaths = new Set(docs.map(d => d.path));
  const totalChunks = docs.reduce((a, d) => a + (d.chunks || 0), 0);

  const card = { background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 16, padding: '18px 20px', marginBottom: 16 };
  const inp = { padding: '10px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 14 };

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'transparent', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 900, margin: '0 auto' }}>
        <h1 style={{ margin: 0, fontSize: '1.6rem', color: '#a78bfa' }}>🗂️ Indexation & recherche PC</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20 }}>
          Indexe tes documents (Word, PDF, Markdown, Excel, PowerPoint, HTML…) pour que Marvin s'en serve, et fouille la mémoire du PC pour retrouver un fichier par son <strong>nom</strong> ou par son <strong>contenu</strong>. 100 % local.
        </div>

        {/* ── FOUILLER LE PC ───────────────────────────────────────────── */}
        <div style={card}>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>🔎 Fouiller la mémoire du PC</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
            Recherche instantanée via l'index Windows. « Contenu » trouve un document d'après ce qu'il contient.
          </div>

          <div style={{ display: 'inline-flex', borderRadius: 10, overflow: 'hidden', border: '1px solid var(--border)', marginBottom: 12 }}>
            {[['content', '📄 Par contenu'], ['name', '🏷️ Par nom']].map(([v, l]) => (
              <button key={v} onClick={() => { setMode(v); if (v === 'content' && ftype === 'folder') setFtype(''); }}
                style={{ padding: '8px 16px', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600,
                  background: mode === v ? '#a78bfa' : 'transparent', color: mode === v ? '#1a1a1a' : 'var(--text-secondary)' }}>{l}</button>
            ))}
          </div>

          <form onSubmit={search} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input value={q} onChange={e => setQ(e.target.value)} autoFocus
              placeholder={mode === 'content' ? 'Ce que le document CONTIENT (ex : « clause de résiliation », « facture Dupont »)' : 'Nom du fichier/dossier (ex : « rapport », « abdou »)'}
              style={{ ...inp, flex: 1, minWidth: 220 }} />
            <select value={ftype} onChange={e => setFtype(e.target.value)} style={{ ...inp, cursor: 'pointer' }}>
              {(mode === 'name' ? [...FILE_TYPES, { v: 'folder', label: '📁 Dossiers' }] : FILE_TYPES).map(t => <option key={t.v} value={t.v}>{t.label}</option>)}
            </select>
            <button type="submit" disabled={searching || (mode === 'content' && !q.trim())}
              style={{ padding: '10px 20px', borderRadius: 10, border: 'none', background: '#a78bfa', color: '#1a1a1a', fontWeight: 800, cursor: searching ? 'wait' : 'pointer', fontSize: 14 }}>
              {searching ? '⏳' : 'Chercher'}
            </button>
          </form>

          {results?.error && <div style={{ marginTop: 12, fontSize: 13, color: '#f87171' }}>⚠️ {results.error}</div>}
          {results && !results.error && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                {results.count} résultat(s){results.elapsed_ms != null ? ` · ${results.elapsed_ms} ms` : ''}
              </div>
              {(results.results || []).length === 0 && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>{results.hint || 'Aucun résultat.'}</div>}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {(results.results || []).map((r, i) => {
                  const isDir = r.is_dir;
                  const already = indexedPaths.has(r.path);
                  return (
                    <div key={i} style={{ padding: '10px 12px', borderRadius: 10, background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 13, fontWeight: 600 }}>{isDir ? '📁' : '📄'} {r.name}</span>
                        {r.size_kb ? <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{fmtSize(r.size_kb)}</span> : null}
                        <span style={{ flex: 1 }} />
                        <button onClick={() => openPath(r.path)} title="Ouvrir" style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>📂 Ouvrir</button>
                        {isDir
                          ? <button onClick={() => indexPath(r.path)} disabled={indexing && busyPath === r.path} title="Indexer tout le dossier (récursif, jusqu'à 200 fichiers)"
                              style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: 'none', background: 'rgba(167,139,250,0.25)', color: '#c4b5fd', cursor: 'pointer', fontWeight: 600 }}>
                              {indexing && busyPath === r.path ? '⏳ Indexation…' : '📁 Indexer le dossier'}</button>
                          : (already
                              ? <span style={{ fontSize: 11, color: '#34d399' }}>✓ indexé</span>
                              : <button onClick={() => indexPath(r.path)} disabled={indexing && busyPath === r.path} title="Ajouter à la base de connaissances"
                                  style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: 'none', background: 'rgba(167,139,250,0.25)', color: '#c4b5fd', cursor: 'pointer', fontWeight: 600 }}>
                                  {indexing && busyPath === r.path ? '⏳' : '➕ Indexer'}</button>)}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, wordBreak: 'break-all' }}>{r.path}</div>
                      {r.snippet && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4, fontStyle: 'italic' }}>« …{r.snippet}… »</div>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* ── INDEXER ──────────────────────────────────────────────────── */}
        <div style={card}>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>📥 Indexer des documents</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
            Colle un chemin de <strong>fichier ou dossier</strong> (tout le dossier sera indexé, récursivement), ou dépose des fichiers.
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <input value={pathInput} onChange={e => setPathInput(e.target.value)} placeholder="C:\Users\…\Documents\dossier-client  (ou un fichier précis)"
              onKeyDown={e => { if (e.key === 'Enter') { indexPath(pathInput); setPathInput(''); } }}
              style={{ ...inp, flex: 1, minWidth: 240, fontSize: 13 }} />
            <button onClick={() => { indexPath(pathInput); setPathInput(''); }} disabled={indexing || !pathInput.trim()}
              style={{ padding: '10px 18px', borderRadius: 10, border: 'none', background: '#a78bfa', color: '#1a1a1a', fontWeight: 700, cursor: 'pointer', fontSize: 13 }}>
              {indexing ? '⏳' : 'Indexer'}
            </button>
          </div>
          <div onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); uploadFiles(e.dataTransfer.files); }}
            style={{ padding: '14px', border: '1.5px dashed var(--border)', borderRadius: 12, textAlign: 'center', background: 'rgba(255,255,255,0.02)' }}>
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>📎 Glisse des fichiers ici, ou </span>
            <input ref={fileRef} type="file" multiple accept=".pdf,.docx,.txt,.md,.markdown,.csv,.tsv,.xlsx,.pptx,.html,.htm,.rtf,.xml,.json,.yaml,.yml,.rst" style={{ display: 'none' }} onChange={e => uploadFiles(e.target.files)} />
            <button onClick={() => fileRef.current?.click()} disabled={indexing}
              style={{ fontSize: 13, padding: '4px 12px', borderRadius: 8, border: 'none', background: 'rgba(167,139,250,0.25)', color: '#c4b5fd', cursor: 'pointer', fontWeight: 600 }}>parcourir</button>
          </div>
        </div>

        {/* ── BASE DE CONNAISSANCES ────────────────────────────────────── */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>📚 Base de connaissances</div>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{docs.length} document(s) · {totalChunks} fragments</span>
          </div>
          {docs.length === 0
            ? <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Rien d'indexé pour l'instant. Indexe un dossier ci-dessus, ou indexe un résultat de recherche.</div>
            : <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {docs.map(d => (
                  <span key={d.id} title={d.path} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 20, background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.25)', fontSize: 12 }}>
                    📄 {d.name} <span style={{ color: 'var(--text-muted)' }}>({d.chunks})</span>
                    <button onClick={() => forget(d.id)} title="Retirer" style={{ background: 'transparent', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: 13, padding: 0 }}>×</button>
                  </span>
                ))}
              </div>}

          <form onSubmit={ask} style={{ display: 'flex', gap: 8, marginTop: 16 }}>
            <input value={question} onChange={e => setQuestion(e.target.value)} placeholder="Interroge ta base… (ex : « que dit le contrat sur la garantie ? »)"
              style={{ ...inp, flex: 1 }} />
            <button type="submit" disabled={asking || !question.trim()}
              style={{ padding: '10px 20px', borderRadius: 10, border: 'none', background: '#a78bfa', color: '#1a1a1a', fontWeight: 800, cursor: asking ? 'wait' : 'pointer', fontSize: 14 }}>
              {asking ? '⏳' : 'Demander'}
            </button>
          </form>

          {answer && (
            <div style={{ marginTop: 14, padding: '16px 18px', background: 'rgba(167,139,250,0.06)', border: '1px solid rgba(167,139,250,0.25)', borderRadius: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#a78bfa', marginBottom: 8 }}>✨ Réponse</div>
              <div style={{ fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>{answer.answer}</div>
              {answer.sources?.length > 0 && (
                <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>SOURCES</div>
                  {answer.sources.map((s, i) => (
                    <div key={i} style={{ fontSize: 12, marginBottom: 6 }}>
                      <strong style={{ color: '#a78bfa' }}>📄 {s.name}</strong>
                      {s.extrait && <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', marginTop: 2 }}>« {s.extrait}… »</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'center', marginTop: 8 }}>
          💡 La recherche par contenu couvre les emplacements indexés par Windows (Bureau, Documents, Téléchargements…). Pour d'autres dossiers, ajoute-les dans « Options d'indexation » de Windows.
        </div>
      </div>
    </div>
  );
}

export default function RedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/fichiers?tab=indexation'); }, [router]);
  return null;
}
