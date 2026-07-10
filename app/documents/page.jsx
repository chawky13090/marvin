'use client';

import { useRouter } from 'next/navigation';
import { useState, useEffect, useCallback, useRef } from 'react';
import { useToast } from '@/components/ui/Toast';

const BACKEND = (typeof window!=='undefined'&&window.location?window.location.protocol+'//'+window.location.hostname+':8005':(process.env.NEXT_PUBLIC_BACKEND_URL||'http://127.0.0.1:8005'));

export function DocumentsView() {
  const [docs, setDocs] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [pathInput, setPathInput] = useState('');
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState(null);
  const fileRef = useRef(null);
  const { toast } = useToast();
  const flash = (m) => {
    const t = (m || '').trim();
    const type = t.startsWith('❌') ? 'error' : t.startsWith('⚠️') ? 'warning' : t.startsWith('✅') ? 'success' : t.startsWith('📄') ? 'success' : 'info';
    toast[type](t.replace(/^(✅|❌|⚠️|📄)\s*/, ''));
  };

  const loadDocs = useCallback(async () => {
    try { const r = await fetch(`${BACKEND}/api/documents`).then(r => r.json()); setDocs(r.documents || []); } catch {}
  }, []);
  useEffect(() => { loadDocs(); }, [loadDocs]);

  async function uploadFiles(files) {
    if (!files || !files.length) return;
    setUploading(true);
    for (const file of files) {
      try {
        const fd = new FormData(); fd.append('file', file);
        const r = await fetch(`${BACKEND}/api/documents/upload`, { method: 'POST', body: fd }).then(r => r.json());
        flash(r.detail ? '❌ ' + r.detail : `📄 ${r.message || file.name + ' indexé'}`);
      } catch { flash('❌ Échec de l\'envoi'); }
    }
    setUploading(false);
    if (fileRef.current) fileRef.current.value = '';
    loadDocs();
  }

  async function indexByPath() {
    if (!pathInput.trim()) return;
    setUploading(true);
    try {
      const r = await fetch(`${BACKEND}/api/documents/index`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: pathInput.trim() }) }).then(r => r.json());
      flash(r.detail ? '❌ ' + r.detail : `📄 ${r.message}`);
      setPathInput('');
    } catch { flash('❌ Échec'); }
    setUploading(false);
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

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'transparent', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 860, margin: '0 auto' }}>
        <h1 style={{ margin: 0, fontSize: '1.6rem', color: '#60a5fa' }}>📄 Mes documents</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20 }}>
          Pose des questions à tes PDF, Word, Excel, PowerPoint… Marvin répond en citant les passages. 100 % local et privé.
        </div>

        {/* Zone d'ajout */}
        <div onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); uploadFiles(e.dataTransfer.files); }}
          style={{ padding: '18px', border: '1.5px dashed var(--border)', borderRadius: 14, marginBottom: 12, textAlign: 'center', background: 'rgba(255,255,255,0.02)' }}>
          <div style={{ fontSize: 14, marginBottom: 10 }}>📥 Glisse un fichier ici, ou</div>
          <input ref={fileRef} type="file" multiple accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.pptx" style={{ display: 'none' }} onChange={e => uploadFiles(e.target.files)} />
          <button onClick={() => fileRef.current?.click()} disabled={uploading}
            style={{ padding: '9px 18px', borderRadius: 10, border: 'none', background: 'var(--accent-gradient, #60a5fa)', color: '#1a1a1a', fontWeight: 700, cursor: 'pointer', fontSize: 13 }}>
            {uploading ? '⏳ Indexation…' : '📄 Choisir un fichier'}
          </button>
          <div style={{ display: 'flex', gap: 8, marginTop: 14, maxWidth: 560, marginInline: 'auto' }}>
            <input value={pathInput} onChange={e => setPathInput(e.target.value)} placeholder="…ou colle un chemin de fichier/dossier à indexer"
              style={{ flex: 1, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 12 }} />
            <button onClick={indexByPath} disabled={uploading || !pathInput.trim()} className="btn btn-ghost" style={{ fontSize: 12 }}>Indexer</button>
          </div>
        </div>

        {/* Liste des documents */}
        {docs.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 22 }}>
            {docs.map(d => (
              <span key={d.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 20, background: 'rgba(96,165,250,0.1)', border: '1px solid rgba(96,165,250,0.25)', fontSize: 12 }}>
                📄 {d.name} <span style={{ color: 'var(--text-muted)' }}>({d.chunks})</span>
                <button onClick={() => forget(d.id)} title="Retirer" style={{ background: 'transparent', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: 13, padding: 0 }}>×</button>
              </span>
            ))}
          </div>
        )}

        {/* Question */}
        <form onSubmit={ask} style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
          <input value={question} onChange={e => setQuestion(e.target.value)} placeholder="Pose une question à tes documents… (ex : « que dit le contrat sur la garantie ? »)"
            style={{ flex: 1, padding: '12px 14px', borderRadius: 12, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 14 }} />
          <button type="submit" disabled={asking || !question.trim()} style={{ padding: '12px 22px', borderRadius: 12, border: 'none', background: 'var(--accent-gradient, #60a5fa)', color: '#1a1a1a', fontWeight: 800, cursor: asking ? 'wait' : 'pointer', fontSize: 14 }}>
            {asking ? '⏳' : 'Demander'}
          </button>
        </form>

        {docs.length === 0 && !answer && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', textAlign: 'center', padding: 20 }}>
            Aucun document indexé pour l'instant. Ajoute un fichier ci-dessus pour commencer.
          </div>
        )}

        {/* Réponse */}
        {answer && (
          <div style={{ padding: '20px 22px', background: 'rgba(96,165,250,0.06)', border: '1px solid rgba(96,165,250,0.25)', borderRadius: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#60a5fa', marginBottom: 8 }}>✨ Réponse</div>
            <div style={{ fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>{answer.answer}</div>
            {answer.sources?.length > 0 && (
              <div style={{ marginTop: 14, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>SOURCES</div>
                {answer.sources.map((s, i) => (
                  <div key={i} style={{ fontSize: 12, marginBottom: 6 }}>
                    <strong style={{ color: '#60a5fa' }}>📄 {s.name}</strong>
                    {s.extrait && <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', marginTop: 2 }}>« {s.extrait}… »</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function RedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/fichiers?tab=documents'); }, [router]);
  return null;
}
