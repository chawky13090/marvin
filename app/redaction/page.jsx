'use client';

import { useState, useEffect, useCallback } from 'react';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

export default function RedactionPage() {
  const [templates, setTemplates] = useState([]);
  const [tpl, setTpl] = useState('rapport_intervention');
  const [title, setTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [notes, setNotes] = useState('');
  const [useDocs, setUseDocs] = useState(false);
  const [pdf, setPdf] = useState(false);
  const [detailed, setDetailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState('');
  // En-tête personnalisable + signature (le rédacteur choisit les détails)
  const [lh, setLh] = useState({});
  const [showHeader, setShowHeader] = useState(false);
  const [savedMsg, setSavedMsg] = useState('');
  const [client, setClient] = useState('');
  const [reference, setReference] = useState('');
  const [includeHeader, setIncludeHeader] = useState(true);
  const [sign, setSign] = useState(false);
  const [lieu, setLieu] = useState('');
  // Affiner une section d'un document déjà généré
  const [refSection, setRefSection] = useState('');
  const [refInstr, setRefInstr] = useState('développe et complète cette section');
  const [refining, setRefining] = useState(false);
  const [refMsg, setRefMsg] = useState('');

  useEffect(() => { fetch(`${BACKEND}/api/documents/letterhead`).then(r => r.json()).then(d => setLh(d || {})).catch(() => {}); }, []);
  const setF = (k, v) => setLh(l => ({ ...l, [k]: v }));
  async function saveLetterhead() {
    try { await fetch(`${BACKEND}/api/documents/letterhead`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(lh) }); setSavedMsg('✅ En-tête enregistré'); setTimeout(() => setSavedMsg(''), 3000); } catch {}
  }
  async function uploadLogo(file) {
    if (!file) return;
    const fd = new FormData(); fd.append('file', file);
    try { const r = await fetch(`${BACKEND}/api/documents/logo`, { method: 'POST', body: fd }).then(r => r.json()); if (r.logo) setLh(l => ({ ...l, logo: r.logo })); } catch {}
  }

  useEffect(() => {
    fetch(`${BACKEND}/api/documents/templates`).then(r => r.json())
      .then(r => setTemplates(r.templates || [])).catch(() => {});
  }, []);

  const current = templates.find(t => t.key === tpl);

  const generate = useCallback(async () => {
    if (!notes.trim() && !title.trim()) { setErr('Donne au moins des notes ou un titre.'); return; }
    setBusy(true); setErr(''); setResult(null);
    try {
      const r = await fetch(`${BACKEND}/api/documents/generate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: notes, template: tpl, title, author, use_documents: useDocs, pdf, mode: detailed ? 'detaille' : 'rapide',
          include_header: includeHeader, client, reference, sign, lieu }),
      }).then(r => r.json());
      if (r.detail) setErr(r.detail);
      else setResult(r);
    } catch { setErr('Backend injoignable.'); }
    setBusy(false);
  }, [notes, title, author, tpl, useDocs, pdf, detailed, includeHeader, client, reference, sign, lieu]);

  async function refineSec() {
    const section = refSection || (result?.sections?.[0]);
    if (!result?.file || !section) return;
    setRefining(true); setRefMsg('');
    try {
      const r = await fetch(`${BACKEND}/api/documents/refine`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file: result.file, section, instruction: refInstr }),
      }).then(r => r.json());
      if (r.detail) setRefMsg('⚠️ ' + r.detail);
      else {
        setRefMsg(`✅ Section « ${r.section} » affinée — retélécharge le document`);
        if (r.markdown) setResult(res => ({ ...res, markdown: r.markdown }));
      }
    } catch { setRefMsg('⚠️ Backend injoignable'); }
    setRefining(false);
    setTimeout(() => setRefMsg(''), 5000);
  }

  return (
    <div style={{ height: '100vh', overflowY: 'auto', background: 'var(--bg-primary)', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 900, margin: '0 auto' }}>
        <h1 style={{ margin: 0, fontSize: '1.6rem', color: '#4f8cff' }}>✍️ Rédaction IA</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 14 }}>
          Transforme des notes brutes en document professionnel complet, prêt à rendre au format Word. 100 % local.
        </div>

        {/* En-tête & signature personnalisables (le rédacteur choisit les détails) */}
        <button onClick={() => setShowHeader(s => !s)}
          style={{ marginBottom: 12, padding: '8px 14px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>
          🏢 En-tête & signature {lh?.org ? `· ${lh.org}` : '(à personnaliser)'} {showHeader ? '▲' : '▼'}
        </button>
        {showHeader && (
          <div style={{ padding: '16px 18px', border: '1px solid var(--border)', borderRadius: 12, marginBottom: 16, background: 'rgba(255,255,255,0.02)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>Ces informations apparaîtront en haut de chaque document (et sont mémorisées). Tu choisis ce que tu mets.</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {[['org', 'Société / nom'], ['email', 'Email'], ['address', 'Adresse'], ['phone', 'Téléphone'], ['website', 'Site web'], ['signataire_name', 'Signataire (nom)'], ['signataire_title', 'Signataire (fonction)']].map(([k, label]) => (
                <input key={k} value={lh[k] || ''} onChange={e => setF(k, e.target.value)} placeholder={label}
                  style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 13 }} />
              ))}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
              <label style={{ fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer' }}>
                🖼️ Logo : <input type="file" accept="image/*" onChange={e => uploadLogo(e.target.files?.[0])} style={{ fontSize: 11 }} />
              </label>
              {lh.logo && <span style={{ fontSize: 11, color: '#34d399' }}>✓ logo ajouté</span>}
              <button onClick={saveLetterhead} style={{ marginLeft: 'auto', padding: '7px 16px', borderRadius: 8, border: 'none', background: 'var(--accent-gradient, #4f8cff)', color: '#1a1a1a', fontWeight: 700, fontSize: 12, cursor: 'pointer' }}>💾 Enregistrer l'en-tête</button>
              {savedMsg && <span style={{ fontSize: 12, color: '#34d399' }}>{savedMsg}</span>}
            </div>
          </div>
        )}

        {/* Choix du modèle */}
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 8 }}>1 · Choisis un modèle</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 18 }}>
          {templates.map(t => (
            <button key={t.key} onClick={() => setTpl(t.key)}
              style={{ padding: '10px 14px', borderRadius: 10, cursor: 'pointer', fontSize: 13, textAlign: 'left',
                background: tpl === t.key ? 'rgba(79, 140, 255,0.14)' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${tpl === t.key ? 'rgba(79, 140, 255,0.5)' : 'var(--border)'}`,
                color: tpl === t.key ? '#4f8cff' : 'var(--text-secondary)' }}>
              {t.icon} {t.name}
            </button>
          ))}
        </div>
        {current && (
          <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginBottom: 18 }}>
            Sections générées : {current.sections.join(' · ')}
          </div>
        )}

        {/* Entrées */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Titre du document"
            style={{ flex: 2, minWidth: 220, padding: '10px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 14 }} />
          <input value={author} onChange={e => setAuthor(e.target.value)} placeholder="Auteur (optionnel)"
            style={{ flex: 1, minWidth: 160, padding: '10px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 14 }} />
        </div>
        <div style={{ display: 'flex', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
          <input value={client} onChange={e => setClient(e.target.value)} placeholder="Client (optionnel)"
            style={{ flex: 1, minWidth: 160, padding: '9px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 13 }} />
          <input value={reference} onChange={e => setReference(e.target.value)} placeholder="Référence (optionnel)"
            style={{ flex: 1, minWidth: 140, padding: '9px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 13 }} />
        </div>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', margin: '8px 0' }}>2 · Tes notes brutes</div>
        <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={7}
          placeholder="Colle ici tes notes en vrac (mots-clés, phrases, déroulé…). Marvin structure et rédige le reste."
          style={{ width: '100%', padding: '12px 14px', borderRadius: 12, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 14, resize: 'vertical', boxSizing: 'border-box' }} />

        <div style={{ display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap', margin: '12px 0 18px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
            <input type="checkbox" checked={useDocs} onChange={e => setUseDocs(e.target.checked)} /> Enrichir avec mes documents indexés
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
            <input type="checkbox" checked={pdf} onChange={e => setPdf(e.target.checked)} /> Aussi en PDF
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }} title="Rédige chaque section séparément : plus complet mais plus long">
            <input type="checkbox" checked={detailed} onChange={e => setDetailed(e.target.checked)} /> Mode détaillé (plus long)
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
            <input type="checkbox" checked={includeHeader} onChange={e => setIncludeHeader(e.target.checked)} /> En-tête
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
            <input type="checkbox" checked={sign} onChange={e => setSign(e.target.checked)} /> Signature
          </label>
          {sign && <input value={lieu} onChange={e => setLieu(e.target.value)} placeholder="Lieu (ex : Aix)"
            style={{ width: 120, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 12 }} />}
          <button onClick={generate} disabled={busy}
            style={{ marginLeft: 'auto', padding: '11px 24px', borderRadius: 12, border: 'none', background: 'var(--accent-gradient, #4f8cff)', color: '#1a1a1a', fontWeight: 800, fontSize: 15, cursor: busy ? 'wait' : 'pointer' }}>
            {busy ? '⏳ Rédaction en cours…' : '✨ Générer le document'}
          </button>
        </div>
        {busy && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>Marvin rédige section par section (≈1-2 min pour un document complet)…</div>}
        {err && <div style={{ color: '#f87171', fontSize: 13, marginBottom: 14 }}>⚠️ {err}</div>}

        {/* Résultat */}
        {result && (
          <div style={{ padding: '20px 22px', background: 'rgba(79, 140, 255,0.06)', border: '1px solid rgba(79, 140, 255,0.25)', borderRadius: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#4f8cff' }}>✅ {result.title}</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <a href={`${BACKEND}/api/documents/download?path=${encodeURIComponent(result.file)}`}
                  style={{ padding: '8px 16px', borderRadius: 10, background: 'var(--accent-gradient, #4f8cff)', color: '#1a1a1a', fontWeight: 700, fontSize: 13, textDecoration: 'none' }}>
                  ⬇️ Télécharger Word
                </a>
                {result.pdf && (
                  <a href={`${BACKEND}/api/documents/download?path=${encodeURIComponent(result.pdf)}`}
                    style={{ padding: '8px 16px', borderRadius: 10, border: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: 13, textDecoration: 'none' }}>⬇️ PDF</a>
                )}
              </div>
            </div>
            <pre style={{ fontFamily: 'inherit', fontSize: 13, lineHeight: 1.7, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0, maxHeight: 420, overflowY: 'auto' }}>{result.markdown}</pre>

            {/* Affiner une section */}
            {result.sections?.length > 0 && (
              <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid rgba(79, 140, 255,0.25)' }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#4f8cff', marginBottom: 8 }}>✍️ Affiner une section</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  <select value={refSection} onChange={e => setRefSection(e.target.value)}
                    style={{ padding: '9px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 13, cursor: 'pointer' }}>
                    {result.sections.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <input value={refInstr} onChange={e => setRefInstr(e.target.value)} placeholder="Consigne (ex : développe, ajoute un tableau, raccourcis…)"
                    style={{ flex: 1, minWidth: 200, padding: '9px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 13 }} />
                  <button onClick={refineSec} disabled={refining}
                    style={{ padding: '9px 18px', borderRadius: 10, border: 'none', background: 'rgba(79, 140, 255,0.25)', color: '#dceaff', fontWeight: 700, fontSize: 13, cursor: refining ? 'wait' : 'pointer' }}>
                    {refining ? '⏳ Réécriture…' : '✨ Affiner'}
                  </button>
                </div>
                {refMsg && <div style={{ fontSize: 12, color: refMsg.startsWith('✅') ? '#34d399' : '#f87171', marginTop: 8 }}>{refMsg}</div>}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
