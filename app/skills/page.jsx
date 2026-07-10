'use client';

import { useState, useEffect, useCallback } from 'react';
import { useToast } from '@/components/ui/Toast';

const BACKEND = (typeof window !== 'undefined' && window.location ? window.location.protocol + '//' + window.location.hostname + ':8005' : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005'));

const EMPTY = { name: '', description: '', triggers: '', tools: '', body: '' };

export default function SkillsPage() {
  const [skills, setSkills] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [genDesc, setGenDesc] = useState('');
  const [genBusy, setGenBusy] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [stats, setStats] = useState({});
  const [upBusy, setUpBusy] = useState('');        // nom de la compétence en cours de renforcement
  const [versionsFor, setVersionsFor] = useState(''); // nom dont le panneau versions est ouvert
  const [versions, setVersions] = useState([]);
  const [resFor, setResFor] = useState('');           // nom dont le panneau ressources est ouvert
  const [resources, setResources] = useState([]);
  const [resForm, setResForm] = useState({ filename: '', content: '' });
  const [suggestions, setSuggestions] = useState(null);  // null = pas encore analysé
  const [suggBusy, setSuggBusy] = useState(false);
  const [creatingSugg, setCreatingSugg] = useState('');

  const { toast } = useToast();
  const flash = (m) => {
    const t = (m || '').trim();
    const type = t.startsWith('❌') ? 'error' : t.startsWith('⚠️') ? 'warning' : t.startsWith('✅') ? 'success' : 'info';
    toast[type](t.replace(/^(✅|❌|⚠️)\s*/, ''));
  };
  const load = useCallback(async () => {
    try { const r = await fetch(`${BACKEND}/api/skills`).then(r => r.json()); setSkills(r.skills || []); } catch {}
    try { const s = await fetch(`${BACKEND}/api/skills/stats`).then(r => r.json()); setStats(s.stats || {}); } catch {}
  }, []);
  useEffect(() => { load(); }, [load]);

  async function upgrade(name) {
    setUpBusy(name); flash(`🔧 Marvin renforce « ${name} »…`);
    try {
      const r = await fetch(`${BACKEND}/api/skills/${encodeURIComponent(name)}/upgrade`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Renforcement manuel demandé depuis l’interface.' }),
      }).then(r => r.json());
      if (r.success) { flash(`✅ « ${name} » renforcée (v${r.version})`); load(); if (versionsFor === name) openVersions(name); }
      else flash('⚠️ ' + (r.error || 'Échec du renforcement'));
    } catch { flash('❌ Backend injoignable'); }
    setUpBusy('');
  }

  async function openVersions(name) {
    if (versionsFor === name) { setVersionsFor(''); setVersions([]); return; }
    setVersionsFor(name); setVersions([]);
    try {
      const r = await fetch(`${BACKEND}/api/skills/${encodeURIComponent(name)}/versions`).then(r => r.json());
      setVersions(r.versions || []);
    } catch {}
  }

  async function rollback(name, version_file) {
    if (!confirm(`Restaurer la version archivée de « ${name} » ?\n${version_file}`)) return;
    try {
      const r = await fetch(`${BACKEND}/api/skills/${encodeURIComponent(name)}/rollback`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version_file }),
      }).then(r => r.json());
      if (r.success) { flash(`↩️ « ${name} » restaurée`); load(); openVersions(name); }
      else flash('⚠️ Rollback impossible');
    } catch { flash('❌ Backend injoignable'); }
  }

  async function openResources(name) {
    if (resFor === name) { setResFor(''); setResources([]); return; }
    setResFor(name); setResources([]); setResForm({ filename: '', content: '' });
    try {
      const r = await fetch(`${BACKEND}/api/skills/${encodeURIComponent(name)}/resources`).then(r => r.json());
      setResources(r.resources || []);
    } catch {}
  }

  async function saveResource(name) {
    if (!resForm.filename.trim() || !resForm.content.trim()) { flash('⚠️ Nom de fichier et contenu requis.'); return; }
    try {
      const r = await fetch(`${BACKEND}/api/skills/${encodeURIComponent(name)}/resources`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: resForm.filename.trim(), content: resForm.content }),
      }).then(r => r.json());
      if (r.success) {
        flash(`📦 Ressource « ${r.name} » ajoutée`);
        setResForm({ filename: '', content: '' });
        const lst = await fetch(`${BACKEND}/api/skills/${encodeURIComponent(name)}/resources`).then(r => r.json());
        setResources(lst.resources || []); load();
      } else flash('⚠️ ' + (r.error || 'Échec'));
    } catch { flash('❌ Backend injoignable'); }
  }

  async function delResource(name, filename) {
    if (!confirm(`Supprimer la ressource « ${filename} » ?`)) return;
    try {
      await fetch(`${BACKEND}/api/skills/${encodeURIComponent(name)}/resources/${encodeURIComponent(filename)}`, { method: 'DELETE' });
      flash('🗑️ Ressource supprimée');
      const r = await fetch(`${BACKEND}/api/skills/${encodeURIComponent(name)}/resources`).then(r => r.json());
      setResources(r.resources || []); load();
    } catch {}
  }

  async function analyzeSuggestions() {
    setSuggBusy(true); flash('🔎 Marvin analyse tes demandes récentes…');
    try {
      const r = await fetch(`${BACKEND}/api/skills/suggest`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(r => r.json());
      setSuggestions(r.suggestions || []);
      flash((r.suggestions?.length || 0) > 0 ? `🔎 ${r.suggestions.length} suggestion(s) (analysé ${r.analyzed} demandes)` : `Aucune nouvelle compétence à suggérer (analysé ${r.analyzed} demandes)`);
    } catch { flash('❌ Backend injoignable'); }
    setSuggBusy(false);
  }

  async function createFromSuggestion(s) {
    setCreatingSugg(s.name); flash(`🤖 Marvin rédige « ${s.name} »…`);
    try {
      const r = await fetch(`${BACKEND}/api/skills/generate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: `${s.description}. Exemples de demandes : ${(s.examples || []).join(' ; ')}` }),
      }).then(r => r.json());
      if (r.success) { flash(`✅ Compétence « ${r.skill?.name} » créée`); setSuggestions(prev => (prev || []).filter(x => x.name !== s.name)); load(); }
      else flash('⚠️ ' + (r.error || 'Échec'));
    } catch { flash('❌ Backend injoignable'); }
    setCreatingSugg('');
  }

  async function dismissSuggestion(name) {
    try { await fetch(`${BACKEND}/api/skills/suggest/dismiss`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }); } catch {}
    setSuggestions(prev => (prev || []).filter(x => x.name !== name));
  }

  function edit(s) {
    setForm({ name: s.name, description: s.description, triggers: (s.triggers || []).join(', '), tools: (s.tools || []).join(', '), body: s.body, enabled: s.enabled });
    setEditing(true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  function reset() { setForm(EMPTY); setEditing(false); }

  async function save() {
    if (!form.name.trim()) { flash('⚠️ Donne un nom à la compétence.'); return; }
    setBusy(true);
    try {
      await fetch(`${BACKEND}/api/skills`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name.trim(), description: form.description.trim(), body: form.body,
          tools: form.tools.split(',').map(t => t.trim()).filter(Boolean),
          triggers: (form.triggers || '').split(',').map(t => t.trim()).filter(Boolean),
          enabled: form.enabled !== false,
        }),
      });
      flash('✅ Compétence enregistrée'); reset(); load();
    } catch { flash('❌ Échec'); }
    setBusy(false);
  }

  async function toggle(s) {
    try {
      await fetch(`${BACKEND}/api/skills`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: s.name, description: s.description, body: s.body, tools: s.tools, enabled: !s.enabled }),
      });
      load();
    } catch {}
  }

  async function del(name) {
    try { await fetch(`${BACKEND}/api/skills/${encodeURIComponent(name)}`, { method: 'DELETE' }); flash('🗑️ Supprimée'); load(); } catch {}
  }

  async function generate() {
    if (!genDesc.trim()) return;
    setGenBusy(true); flash('🤖 Marvin rédige la compétence…');
    try {
      const r = await fetch(`${BACKEND}/api/skills/generate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: genDesc.trim() }),
      }).then(r => r.json());
      if (r.success) { flash(`✅ Compétence « ${r.skill?.name} » créée par Marvin`); setGenDesc(''); load(); }
      else flash('⚠️ ' + (r.error || 'Échec de la génération'));
    } catch { flash('❌ Backend injoignable'); }
    setGenBusy(false);
  }

  const inp = { width: '100%', padding: '9px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 13, boxSizing: 'border-box' };
  const ACC = '#2dd4bf';

  return (
    <div style={{ height: '100vh', overflowY: 'auto', background: 'var(--bg-primary)', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 880, margin: '0 auto' }}>
        <h1 style={{ margin: 0, fontSize: '1.6rem', color: ACC }}>🧩 Compétences (Skills)</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
          Apprends à Marvin de nouvelles <strong>méthodes</strong> sans coder : une compétence = une marche à suivre que Marvin applique avec ses outils existants. 🔒 100 % sûr : ce sont des <strong>instructions</strong>, pas du code exécutable.
        </div>

        {/* Guide : comment créer & ajouter une compétence */}
        <button onClick={() => setShowGuide(s => !s)}
          style={{ marginBottom: 12, padding: '9px 14px', borderRadius: 10, border: '1px solid rgba(45,212,191,0.4)', background: 'rgba(45,212,191,0.08)', color: ACC, cursor: 'pointer', fontSize: 13, fontWeight: 700 }}>
          📖 Comment créer une compétence et l'ajouter à Marvin ? {showGuide ? '▲' : '▼'}
        </button>
        {showGuide && (
          <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 14, padding: '18px 20px', marginBottom: 18, fontSize: 13, lineHeight: 1.7, color: 'var(--text-secondary)' }}>
            <p style={{ marginTop: 0 }}><strong style={{ color: 'var(--text-primary)' }}>C'est quoi ?</strong> Une compétence = une <strong>marche à suivre</strong> (des instructions) que Marvin applique avec ses outils existants. Ce n'est <strong>pas du code</strong> → 100 % sûr, et tu peux en créer autant que tu veux sans programmer.</p>

            <p style={{ color: 'var(--text-primary)', fontWeight: 700, marginBottom: 4 }}>3 façons de l'ajouter :</p>
            <ol style={{ marginTop: 0, paddingLeft: 20 }}>
              <li><strong>🤖 Par l'IA (le plus simple)</strong> — décris ce que Marvin doit savoir faire dans « Laisse Marvin la rédiger », il génère la compétence tout seul.</li>
              <li><strong>✏️ À la main</strong> — remplis le formulaire « Créer une compétence » (nom, quand l'utiliser, outils, méthode).</li>
              <li><strong>📁 Par fichier</strong> — dépose un fichier <code>.md</code> dans le dossier <code>data/skills/</code> de Marvin. Il est pris en compte automatiquement (inspectable, partageable, versionnable avec git).</li>
            </ol>

            <p style={{ color: 'var(--text-primary)', fontWeight: 700, marginBottom: 4 }}>Format d'un fichier compétence (SKILL.md) :</p>
            <pre style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px', fontSize: 12, overflowX: 'auto', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{`---
name: depannage-imprimante
description: Quand utiliser cette compétence (1 phrase) — détection par le sens
triggers: [imprimante, ça n'imprime pas, bourrage]   # expressions déclencheuses
tools: [net_ping, pc_run_command, system_search]
related: [pas-internet]                               # compétences à enchaîner
enabled: true
---
## Objectif
Ce que la compétence doit accomplir.
## Prérequis
Infos à récupérer d'abord (ex : IP de l'imprimante).
## Étapes
1. Étape avec l'outil \`net_ping\` ...
2. ...
## Vérification
Comment confirmer que c'est VRAIMENT résolu (refaire un test).
## Pièges à éviter
- Erreur classique à ne pas commettre.`}</pre>

            <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
              <li><strong>description + triggers</strong> : déterminent le <strong>déclenchement automatique</strong> (par le sens <em>et</em> par expressions exactes) → activation très précise.</li>
              <li><strong>Structure agentique</strong> : Objectif → Prérequis → Étapes → <strong>Vérification</strong> → Pièges. Marvin <strong>planifie, agit, vérifie chaque résultat, s'auto-corrige et conclut avec preuve</strong> (pas une simple liste récitée).</li>
              <li><strong>related</strong> : compétences que Marvin peut enchaîner pour les cas complexes.</li>
              <li>🔒 <strong>Sécurité</strong> : ce sont des <em>instructions</em>, pas du code. Les actions sensibles passent toujours par les confirmations habituelles.</li>
            </ul>
          </div>
        )}

        {/* Générer avec l'IA */}
        <div style={{ background: 'rgba(45,212,191,0.06)', border: '1px solid rgba(45,212,191,0.25)', borderRadius: 14, padding: '16px 18px', marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>✨ Laisse Marvin la rédiger</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input value={genDesc} onChange={e => setGenDesc(e.target.value)} placeholder="Décris ce que Marvin doit savoir faire (ex : « préparer un devis client », « diagnostiquer un PC lent »)"
              style={{ ...inp, flex: 1, minWidth: 240 }} onKeyDown={e => { if (e.key === 'Enter') generate(); }} />
            <button onClick={generate} disabled={genBusy || !genDesc.trim()}
              style={{ padding: '9px 18px', borderRadius: 10, border: 'none', background: ACC, color: '#06251f', fontWeight: 800, cursor: genBusy ? 'wait' : 'pointer', fontSize: 13 }}>
              {genBusy ? '⏳ Rédaction…' : '🤖 Générer'}
            </button>
          </div>
        </div>

        {/* Éditeur manuel */}
        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 14, padding: '16px 18px', marginBottom: 22 }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>{editing ? '✏️ Modifier' : '➕ Créer'} une compétence</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Nom (ex : dépannage-réseau)" style={inp} />
            <input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder="Quand l'utiliser (1 phrase) — sert à la détecter automatiquement" style={inp} />
            <input value={form.triggers} onChange={e => setForm(f => ({ ...f, triggers: e.target.value }))} placeholder="Déclencheurs : expressions que tu dirais, séparées par des virgules (ex : pc lent, ça rame)" style={inp} />
            <input value={form.tools} onChange={e => setForm(f => ({ ...f, tools: e.target.value }))} placeholder="Outils utiles, séparés par des virgules (ex : net_ping, pc_run_command)" style={inp} />
            <textarea value={form.body} onChange={e => setForm(f => ({ ...f, body: e.target.value }))} rows={7} placeholder="La méthode : étapes numérotées que Marvin suivra…" style={{ ...inp, resize: 'vertical', fontFamily: 'inherit' }} />
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button onClick={save} disabled={busy} style={{ padding: '9px 20px', borderRadius: 10, border: 'none', background: ACC, color: '#06251f', fontWeight: 800, cursor: 'pointer', fontSize: 13 }}>{busy ? '⏳' : '💾 Enregistrer'}</button>
            {editing && <button onClick={reset} style={{ padding: '9px 16px', borderRadius: 10, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>Annuler</button>}
          </div>
        </div>

        {/* Mining proactif — suggestions de compétences */}
        <div style={{ background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.25)', borderRadius: 14, padding: '16px 18px', marginBottom: 22 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>🔎 Suggestions de compétences</div>
            <span style={{ flex: 1, fontSize: 12, color: 'var(--text-muted)' }}>Marvin analyse tes demandes récurrentes et propose des compétences à créer.</span>
            <button onClick={analyzeSuggestions} disabled={suggBusy}
              style={{ padding: '8px 16px', borderRadius: 10, border: '1px solid rgba(251,191,36,0.5)', background: 'rgba(251,191,36,0.12)', color: '#fbbf24', fontWeight: 700, cursor: suggBusy ? 'wait' : 'pointer', fontSize: 13 }}>
              {suggBusy ? '⏳ Analyse…' : '🔎 Analyser mes conversations'}
            </button>
          </div>
          {suggestions !== null && suggestions.length === 0 && !suggBusy && (
            <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 10 }}>Rien à suggérer pour l'instant — tes tâches récurrentes sont déjà couvertes. 👍</div>
          )}
          {suggestions && suggestions.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
              {suggestions.map(s => (
                <div key={s.name} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 13.5, fontWeight: 700, color: '#fbbf24' }}>💡 {s.name}</span>
                    <span style={{ flex: 1 }} />
                    <button onClick={() => createFromSuggestion(s)} disabled={creatingSugg === s.name}
                      style={{ fontSize: 11, padding: '4px 12px', borderRadius: 8, border: 'none', background: ACC, color: '#06251f', fontWeight: 800, cursor: creatingSugg === s.name ? 'wait' : 'pointer' }}>{creatingSugg === s.name ? '⏳…' : '✨ Créer'}</button>
                    <button onClick={() => dismissSuggestion(s.name)} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer' }}>✕ Ignorer</button>
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 4 }}>{s.description}</div>
                  {s.why && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3, fontStyle: 'italic' }}>↻ {s.why}</div>}
                  {s.examples?.length > 0 && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>« {s.examples.join(' » · « ')} »</div>}
                  {s.tools?.length > 0 && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>🔧 {s.tools.join(', ')}</div>}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Liste */}
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 10 }}>Compétences de Marvin ({skills.length})</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {skills.length === 0 && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Aucune compétence. Génère-en une ci-dessus, ou crée-la à la main.</div>}
          {skills.map(s => (
            <div key={s.name} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 12, padding: '12px 14px', opacity: s.enabled ? 1 : 0.55 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 14, fontWeight: 700, color: ACC }}>🧩 {s.name}</span>
                {(() => {
                  const st = stats[s.name];
                  if (!st) return null;
                  const outc = st.last_outcome === 'fail' ? { c: '#f87171', t: '⚠ échec' }
                    : st.last_outcome === 'upgraded' ? { c: ACC, t: '🔧 renforcée' }
                    : { c: '#34d399', t: '✓ ok' };
                  return (
                    <span title={`${st.uses || 0} usage(s) · ${st.ok || 0} ok · ${st.fail || 0} échec(s)${st.last_error ? '\nDernière erreur : ' + st.last_error : ''}`}
                      style={{ fontSize: 10.5, padding: '2px 7px', borderRadius: 6, border: `1px solid ${outc.c}55`, color: outc.c, background: `${outc.c}14` }}>
                      v{st.version || 1} · {outc.t} · {st.ok || 0}/{(st.ok || 0) + (st.fail || 0)}
                    </span>
                  );
                })()}
                {!s.enabled && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>(désactivée)</span>}
                <span style={{ flex: 1 }} />
                <button onClick={() => upgrade(s.name)} disabled={upBusy === s.name} title="Marvin ré-écrit la compétence pour la rendre plus robuste" style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: '1px solid rgba(45,212,191,0.4)', background: 'rgba(45,212,191,0.08)', color: ACC, cursor: upBusy === s.name ? 'wait' : 'pointer' }}>{upBusy === s.name ? '⏳…' : '🔧 Renforcer'}</button>
                <button onClick={() => openResources(s.name)} title="Fichiers de référence embarqués (modèles, tables de prix, check-lists)" style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: '1px solid var(--border)', background: resFor === s.name ? 'rgba(255,255,255,0.06)' : 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>📦 Ressources{s.resources?.length ? ` (${s.resources.length})` : ''}</button>
                <button onClick={() => openVersions(s.name)} title="Historique des versions" style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: '1px solid var(--border)', background: versionsFor === s.name ? 'rgba(255,255,255,0.06)' : 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>🕘 Versions</button>
                <button onClick={() => toggle(s)} title={s.enabled ? 'Désactiver' : 'Activer'} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>{s.enabled ? '⏸ Désactiver' : '▶ Activer'}</button>
                <button onClick={() => edit(s)} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>✏️ Modifier</button>
                <button onClick={() => del(s.name)} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: '1px solid rgba(239,68,68,0.4)', background: 'transparent', color: '#f87171', cursor: 'pointer' }}>🗑️</button>
              </div>
              <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 4 }}>{s.description}</div>
              {s.triggers?.length > 0 && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>⚡ {s.triggers.join(' · ')}</div>}
              {s.tools?.length > 0 && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>🔧 {s.tools.join(', ')}</div>}
              {stats[s.name]?.golden?.calls?.length > 0 && (
                <div title="Séquence d'outils apprise d'un run réussi — réutilisée comme exemple" style={{ fontSize: 11, color: '#fbbf24', marginTop: 4 }}>
                  🥇 Déroulé appris : {stats[s.name].golden.calls.map(c => c.tool).join(' → ')}
                </div>
              )}
              {versionsFor === s.name && (
                <div style={{ marginTop: 8, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(0,0,0,0.2)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 6 }}>🕘 Versions archivées</div>
                  {versions.length === 0
                    ? <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Aucune version archivée (créée à chaque renforcement).</div>
                    : versions.map(v => (
                      <div key={v} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-muted)', padding: '3px 0' }}>
                        <span style={{ flex: 1, fontFamily: 'monospace' }}>{v.replace(s.name + '.', '').replace('.md', '')}</span>
                        <button onClick={() => rollback(s.name, v)} style={{ fontSize: 10.5, padding: '3px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>↩️ Restaurer</button>
                      </div>
                    ))}
                </div>
              )}
              {resFor === s.name && (
                <div style={{ marginTop: 8, padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(0,0,0,0.2)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 6 }}>📦 Ressources de référence <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>— Marvin les utilise quand cette compétence se déclenche (modèles, tables de prix, check-lists…)</span></div>
                  {resources.length === 0
                    ? <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>Aucune ressource. Ajoute-en une ci-dessous.</div>
                    : resources.map(r => (
                      <div key={r.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-secondary)', padding: '3px 0' }}>
                        <span style={{ flex: 1, fontFamily: 'monospace' }}>📄 {r.name} <span style={{ color: 'var(--text-muted)' }}>({(r.size / 1024).toFixed(1)} Ko)</span></span>
                        <button onClick={() => delResource(s.name, r.name)} style={{ fontSize: 10.5, padding: '3px 9px', borderRadius: 6, border: '1px solid rgba(239,68,68,0.4)', background: 'transparent', color: '#f87171', cursor: 'pointer' }}>🗑️</button>
                      </div>
                    ))}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)' }}>
                    <input value={resForm.filename} onChange={e => setResForm(f => ({ ...f, filename: e.target.value }))} placeholder="Nom du fichier (ex : modele-devis.md, tarifs.md)" style={{ ...inp, fontSize: 12, padding: '6px 10px' }} />
                    <textarea value={resForm.content} onChange={e => setResForm(f => ({ ...f, content: e.target.value }))} rows={4} placeholder="Contenu de référence (modèle, table de prix, check-list…)" style={{ ...inp, fontSize: 12, padding: '6px 10px', resize: 'vertical', fontFamily: 'inherit' }} />
                    <button onClick={() => saveResource(s.name)} style={{ alignSelf: 'flex-start', fontSize: 11.5, padding: '6px 14px', borderRadius: 8, border: 'none', background: ACC, color: '#06251f', fontWeight: 700, cursor: 'pointer' }}>📦 Ajouter la ressource</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
