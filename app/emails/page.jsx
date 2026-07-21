'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

// ── Helpers ──────────────────────────────────────────────────────────────────
function formatDate(raw) {
  if (!raw) return '';
  try {
    const d = new Date(raw);
    const now = new Date();
    const diff = now - d;
    if (diff < 86400000 && d.getDate() === now.getDate())
      return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    if (diff < 7 * 86400000)
      return d.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short' });
    return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: '2-digit' });
  } catch { return raw.slice(0, 16); }
}

function senderName(from) {
  if (!from) return '?';
  const m = from.match(/^"?([^"<]+)"?\s*</);
  return m ? m[1].trim() : from.split('@')[0];
}

function senderInitials(from) {
  const n = senderName(from);
  const parts = n.split(/\s+/);
  return (parts[0]?.[0] || '') + (parts[1]?.[0] || parts[0]?.[1] || '');
}

const AVATAR_COLORS = ['#4f8cff','#3b82f6','#22c55e','#8b5cf6','#ec4899','#06b6d4','#f97316'];
function avatarColor(from) {
  let h = 0;
  for (const c of (from || '')) h = (h * 31 + c.charCodeAt(0)) & 0xFFFFFF;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

// ══════════════════════════════════════════════════════════════════════════════
// Configuration email
// ══════════════════════════════════════════════════════════════════════════════
function SetupPanel({ onConfigured, onCancel, title }) {
  const [providers, setProviders] = useState({});
  const [form, setForm] = useState({ provider: 'gmail', imap_host: 'imap.gmail.com', imap_port: 993, smtp_host: 'smtp.gmail.com', smtp_port: 587, username: '', password: '' });
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    fetch(`${BACKEND}/api/email/providers`).then(r => r.json()).then(setProviders).catch(() => {});
  }, []);

  const selectProvider = (id) => {
    const p = providers[id];
    if (!p) return;
    setForm(f => ({ ...f, provider: id, imap_host: p.imap_host, imap_port: p.imap_port, smtp_host: p.smtp_host, smtp_port: p.smtp_port }));
    setTestResult(null);
  };

  const handleTest = async () => {
    setTesting(true); setTestResult(null);
    const r = await fetch(`${BACKEND}/api/email/test`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    });
    setTestResult(await r.json());
    setTesting(false);
  };

  const handleSave = async () => {
    setSaving(true);
    await fetch(`${BACKEND}/api/email/accounts`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    });
    setSaving(false);
    onConfigured(form.username);
  };

  const connectGmailOAuth = async () => {
    const r = await fetch(`${BACKEND}/api/email/oauth/google/start?account_hint=${encodeURIComponent(form.username || '')}`);
    const data = await r.json();
    if (!r.ok || !data.auth_url) {
      setTestResult({ success: false, errors: [data.detail || 'Connexion OAuth impossible'] });
      return;
    }
    window.location.assign(data.auth_url);
  };

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const inp = (k, label, opts = {}) => (
    <div>
      <label style={lbl}>{label}</label>
      <input type={opts.pw ? 'password' : opts.num ? 'number' : 'text'}
        value={form[k]} onChange={e => set(k, opts.num ? Number(e.target.value) : e.target.value)}
        placeholder={opts.ph} style={iSt} />
    </div>
  );

  return (
    <div style={{ maxWidth: '560px', margin: '40px auto', padding: '28px 32px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(79, 140, 255,0.25)', borderRadius: '16px' }}>
      <h2 style={{ margin: '0 0 6px', fontSize: '1.1rem', color: '#4f8cff' }}>📧 {title || 'Configurer votre boîte mail'}</h2>
      <p style={{ margin: '0 0 20px', fontSize: '12px', color: 'var(--text-muted)' }}>Connexion IMAP/SMTP — vos identifiants sont stockés localement. Vous pouvez connecter plusieurs boîtes.</p>

      {form.provider === 'gmail' && (
        <div style={{ marginBottom: '18px', padding: '14px', borderRadius: '10px', background: 'rgba(66,133,244,0.09)', border: '1px solid rgba(66,133,244,0.35)' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#8ab4ff', marginBottom: '5px' }}>Connexion Google recommandée</div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px' }}>OAuth2 permet à Marvin d'utiliser Gmail sans mot de passe d'application. Chaque boîte est autorisée séparément.</div>
          <button onClick={connectGmailOAuth} type="button"
            style={{ padding: '9px 14px', borderRadius: '8px', border: 0, background: '#4285f4', color: 'white', cursor: 'pointer', fontWeight: 700, fontSize: '12px' }}>
            🔐 Connecter cette boîte avec Google
          </button>
          <div style={{ fontSize: '10px', color: '#f59e0b', marginTop: '8px' }}>URI OAuth à autoriser dans Google Cloud : http://localhost:8005/api/oauth/google/callback/email</div>
        </div>
      )}

      {/* Fournisseur */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '20px' }}>
        {Object.entries(providers).map(([id, p]) => (
          <button key={id} onClick={() => selectProvider(id)}
            style={{ padding: '7px 14px', borderRadius: '9px', border: 'none', cursor: 'pointer', fontSize: '12px', fontWeight: 600,
              background: form.provider === id ? '#4f8cff20' : 'rgba(255,255,255,0.05)',
              color: form.provider === id ? '#4f8cff' : 'var(--text-muted)',
              borderBottom: form.provider === id ? '2px solid #4f8cff' : '2px solid transparent',
            }}>
            {p.name}
          </button>
        ))}
      </div>

      {/* Note fournisseur */}
      {providers[form.provider]?.note && (
        <div style={{ padding: '10px 14px', background: 'rgba(79, 140, 255,0.08)', borderRadius: '8px', border: '1px solid rgba(79, 140, 255,0.2)', fontSize: '12px', color: '#4f8cff', marginBottom: '16px' }}>
          💡 {providers[form.provider].note}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        {inp('username', 'Adresse email *', { ph: 'vous@gmail.com' })}
        {inp('password', 'Mot de passe / App password *', { pw: true, ph: '••••••••••••' })}
        {inp('imap_host', 'Serveur IMAP', { ph: 'imap.gmail.com' })}
        {inp('imap_port', 'Port IMAP', { num: true })}
        {inp('smtp_host', 'Serveur SMTP', { ph: 'smtp.gmail.com' })}
        {inp('smtp_port', 'Port SMTP', { num: true })}
      </div>

      {testResult && (
        <div style={{ marginTop: '14px', padding: '10px 14px', borderRadius: '8px', fontSize: '12px',
          background: testResult.success ? '#22c55e15' : '#ef444415',
          border: `1px solid ${testResult.success ? '#22c55e40' : '#ef444440'}`,
          color: testResult.success ? '#4ade80' : '#f87171' }}>
          {testResult.success ? '✅ Connexion réussie — IMAP et SMTP opérationnels' : `❌ ${testResult.errors?.join(' | ')}`}
        </div>
      )}

      <div style={{ display: 'flex', gap: '10px', marginTop: '18px' }}>
        {onCancel && (
          <button onClick={onCancel}
            style={{ padding: '10px 14px', borderRadius: '9px', border: '1px solid var(--border)',
              background: 'rgba(255,255,255,0.04)', color: 'var(--text-muted)', cursor: 'pointer', fontWeight: 600, fontSize: '13px' }}>
            Annuler
          </button>
        )}
        <button onClick={handleTest} disabled={testing || !form.username}
          style={{ flex: 1, padding: '10px', borderRadius: '9px', border: '1px solid #3b82f650',
            background: '#3b82f620', color: '#60a5fa', cursor: 'pointer', fontWeight: 600, fontSize: '13px' }}>
          {testing ? '⏳ Test…' : '🧪 Tester la connexion'}
        </button>
        <button onClick={handleSave} disabled={saving || !form.username || !form.password}
          style={{ flex: 2, padding: '10px', borderRadius: '9px', border: 'none',
            background: (form.username && form.password) ? 'linear-gradient(135deg,#4f8cffcc,#4f8cff88)' : 'rgba(255,255,255,0.05)',
            color: (form.username && form.password) ? 'white' : 'var(--text-muted)',
            cursor: 'pointer', fontWeight: 700, fontSize: '13px' }}>
          {saving ? '⏳…' : (onCancel ? '✓ Ajouter cette boîte' : '✓ Sauvegarder et continuer')}
        </button>
      </div>
    </div>
  );
}

const lbl = { display: 'block', fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '4px' };
const iSt = { width: '100%', padding: '8px 12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-primary)', fontSize: '13px', outline: 'none', boxSizing: 'border-box' };

// ══════════════════════════════════════════════════════════════════════════════
// Fenêtre de composition
// ══════════════════════════════════════════════════════════════════════════════
function ComposeModal({ onClose, replyTo = null, account = null, prefill = null, onRegenerate = null }) {
  const [regenerating, setRegenerating] = useState(false);
  const [form, setForm] = useState({
    to: prefill?.to || replyTo?.from_addr || '',
    subject: prefill?.subject || (replyTo ? `Re: ${replyTo.subject}` : ''),
    body: prefill?.body || (replyTo ? `\n\n---\nDe: ${replyTo.from}\nDate: ${replyTo.date}\n\n${(replyTo.body || '').split('\n').map(l => '> ' + l).join('\n')}` : ''),
    cc: '',
  });
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [templates, setTemplates] = useState([]);

  // Si l'IA régénère un nouveau brouillon, on met à jour le corps
  useEffect(() => {
    if (prefill?.body) setForm(f => ({ ...f, body: prefill.body, to: prefill.to || f.to, subject: prefill.subject || f.subject }));
  }, [prefill?.body]);

  // Charger les modèles + ajouter la signature de la boîte (sauf si brouillon IA déjà rempli)
  useEffect(() => {
    fetch(`${BACKEND}/api/email/templates`).then(r => r.json()).then(d => setTemplates(d.templates || [])).catch(() => {});
    if (!prefill && account) {
      fetch(`${BACKEND}/api/email/signatures`).then(r => r.json()).then(d => {
        const sig = (d.signatures || {})[account];
        if (sig) setForm(f => (f.body.includes(sig) ? f : { ...f, body: f.body + (f.body ? '\n\n' : '') + sig }));
      }).catch(() => {});
    }
  }, []);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const insertTemplate = (name) => {
    const t = templates.find(x => x.name === name);
    if (t) setForm(f => ({ ...f, body: (f.body ? f.body + '\n\n' : '') + t.body }));
  };

  const handleSend = async () => {
    if (!form.to || !form.subject) { setError('Destinataire et objet requis.'); return; }
    setSending(true); setError('');
    try {
      const r = await fetch(`${BACKEND}/api/email/send${account ? `?account=${encodeURIComponent(account)}` : ''}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!r.ok) throw new Error(await r.text());
      setSent(true);
      setTimeout(onClose, 1500);
    } catch (e) { setError(e.message); }
    setSending(false);
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{ width: '620px', maxWidth: '95vw', background: '#111', border: '1px solid rgba(79, 140, 255,0.3)', borderRadius: '16px 16px 0 0', padding: '20px 24px 28px', boxShadow: '0 -10px 40px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
          <span style={{ fontWeight: 700, color: prefill ? '#c084fc' : '#4f8cff', fontSize: '0.95rem' }}>
            {prefill ? '✨ Réponse rédigée par l\'IA' : replyTo ? '↩ Répondre' : '✏️ Nouveau message'}
            {account && <span style={{ fontWeight: 400, color: 'var(--text-muted)', fontSize: '0.78rem', marginLeft: 8 }}>· depuis {account}</span>}
            {prefill && onRegenerate && (
              <button onClick={async () => { setRegenerating(true); await onRegenerate(''); setRegenerating(false); }} disabled={regenerating}
                style={{ marginLeft: 10, padding: '3px 9px', fontSize: '11px', background: 'rgba(168,85,247,0.15)', border: '1px solid rgba(168,85,247,0.4)', borderRadius: '7px', color: '#c084fc', cursor: regenerating ? 'wait' : 'pointer', fontWeight: 600 }}>
                {regenerating ? '⏳…' : '🔄 Régénérer'}
              </button>
            )}
          </span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '18px' }}>×</button>
        </div>

        {['to', 'cc', 'subject'].map(k => (
          <div key={k} style={{ marginBottom: '10px' }}>
            <label style={lbl}>{k === 'to' ? 'À *' : k === 'cc' ? 'Cc' : 'Objet *'}</label>
            <input value={form[k]} onChange={e => set(k, e.target.value)} style={iSt}
              placeholder={k === 'to' ? 'destinataire@email.com' : k === 'cc' ? 'optionnel' : 'Objet du message'} />
          </div>
        ))}

        <div style={{ marginBottom: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <label style={lbl}>Message</label>
            {templates.length > 0 && (
              <select onChange={e => { if (e.target.value) { insertTemplate(e.target.value); e.target.value = ''; } }} defaultValue=""
                title="Insérer un modèle de réponse"
                style={{ padding: '3px 8px', fontSize: '11px', borderRadius: '7px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', color: 'var(--text-muted)', cursor: 'pointer' }}>
                <option value="">📋 Insérer un modèle…</option>
                {templates.map(t => <option key={t.name} value={t.name}>{t.name}</option>)}
              </select>
            )}
          </div>
          <textarea value={form.body} onChange={e => set('body', e.target.value)} rows={10}
            style={{ ...iSt, resize: 'vertical', lineHeight: 1.6 }} />
        </div>

        {error && <div style={{ color: '#f87171', fontSize: '12px', marginBottom: '10px' }}>⚠️ {error}</div>}
        {sent && <div style={{ color: '#4ade80', fontSize: '12px', marginBottom: '10px' }}>✅ Email envoyé !</div>}

        <div style={{ display: 'flex', gap: '10px' }}>
          <button onClick={handleSend} disabled={sending || sent}
            style={{ flex: 1, padding: '10px', background: 'linear-gradient(135deg,#4f8cffcc,#4f8cff88)', color: 'white', border: 'none', borderRadius: '10px', cursor: 'pointer', fontWeight: 700, fontSize: '13px' }}>
            {sending ? '⏳ Envoi…' : sent ? '✅ Envoyé !' : '📤 Envoyer'}
          </button>
          <button onClick={onClose} style={{ padding: '10px 20px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', borderRadius: '10px', color: 'var(--text-muted)', cursor: 'pointer' }}>
            Annuler
          </button>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Assistant email automatique — 3 modes
// ══════════════════════════════════════════════════════════════════════════════
function MultiValueInput({ values = [], onChange, placeholder, style }) {
  const [draft, setDraft] = useState('');

  const addValues = (raw) => {
    const additions = raw.split(/[,;\n]+/).map(x => x.trim()).filter(Boolean);
    if (!additions.length) return;
    const known = new Set(values.map(x => x.toLowerCase()));
    onChange([...values, ...additions.filter(x => {
      const key = x.toLowerCase();
      if (known.has(key)) return false;
      known.add(key);
      return true;
    })]);
    setDraft('');
  };

  const remove = (item) => onChange(values.filter(x => x !== item));

  return (
    <div style={{ ...style, padding: '6px 8px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px' }}>
      {values.map(item => (
        <span key={item} style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', padding: '4px 7px', borderRadius: '7px', background: 'rgba(79,140,255,0.14)', border: '1px solid rgba(79,140,255,0.38)', color: '#8ab4ff', fontSize: '11px' }}>
          {item}
          <button type="button" onClick={() => remove(item)} aria-label={`Supprimer ${item}`}
            style={{ padding: 0, border: 0, background: 'transparent', color: '#8ab4ff', cursor: 'pointer', fontSize: '13px', lineHeight: 1 }}>×</button>
        </span>
      ))}
      <input value={draft} onChange={e => setDraft(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ',' || e.key === ';') {
            e.preventDefault();
            addValues(draft);
          } else if (e.key === 'Backspace' && !draft && values.length) {
            remove(values[values.length - 1]);
          }
        }}
        onBlur={() => addValues(draft)}
        onPaste={e => {
          const text = e.clipboardData.getData('text');
          if (/[,;\n]/.test(text)) {
            e.preventDefault();
            addValues(text);
          }
        }}
        placeholder={values.length ? 'Ajouter…' : placeholder}
        style={{ flex: '1 1 180px', minWidth: '150px', padding: '3px 2px', background: 'transparent', border: 0, outline: 'none', color: 'var(--text-primary)', fontSize: '12.5px' }} />
    </div>
  );
}

function AutomationModal({ accounts, onClose, onOpenDraft }) {
  const [cfg, setCfg] = useState({ mode: 'manuel', accounts: [], instructions: '', tone: 'professionnel, clair et courtois', signature: '', only_from: [], never_from: [], skip_keywords: [], max_per_run: 5, send_delay_min: 5, scheduler_enabled: false, interval_min: 5, profiles: {} });
  const [loaded, setLoaded] = useState(false);
  const [initialScheduler, setInitialScheduler] = useState(false);
  const [profileAccount, setProfileAccount] = useState('');
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [outbox, setOutbox] = useState([]);

  const reloadDrafts = () => fetch(`${BACKEND}/api/email/automation/drafts`).then(r => r.json()).then(d => setDrafts(d.drafts || [])).catch(() => {});
  const reloadOutbox = () => fetch(`${BACKEND}/api/email/automation/outbox`).then(r => r.json()).then(d => setOutbox(d.outbox || [])).catch(() => {});
  useEffect(() => {
    fetch(`${BACKEND}/api/email/automation`).then(r => r.json()).then(c => {
      setCfg(p => ({ ...p, ...c, accounts: c.accounts || [], profiles: c.profiles || {}, only_from: c.only_from || [], never_from: c.never_from || [], skip_keywords: c.skip_keywords || [] }));
      setInitialScheduler(Boolean(c.scheduler_enabled));
      setLoaded(true);
    }).catch(() => setLoaded(true));
    reloadDrafts();
    reloadOutbox();
  }, []);

  const set = (k, v) => setCfg(c => ({ ...c, [k]: v }));
  const active = profileAccount ? { ...cfg, ...(cfg.profiles?.[profileAccount] || {}) } : cfg;
  const setRule = (key, value) => {
    if (!profileAccount) { set(key, value); return; }
    setCfg(current => ({
      ...current,
      profiles: { ...(current.profiles || {}), [profileAccount]: { ...(current.profiles?.[profileAccount] || {}), [key]: value } },
    }));
  };

  const save = async () => {
    let schedulerConfirmed = false;
    if (cfg.scheduler_enabled && !initialScheduler) {
      schedulerConfirmed = confirm(`Activer l'exécution automatique toutes les ${cfg.interval_min} minutes ?\n\nEn mode autonome, Marvin pourra envoyer sans nouvelle validation, uniquement selon les listes autorisées.`);
      if (!schedulerConfirmed) return false;
    }
    setSaving(true);
    const response = await fetch(`${BACKEND}/api/email/automation`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...cfg, scheduler_confirmed: schedulerConfirmed }) });
    setSaving(false);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      setResult({ error: data.detail || 'Enregistrement impossible' });
      return false;
    }
    setInitialScheduler(Boolean(cfg.scheduler_enabled));
    return true;
  };
  const run = async (dry) => {
    const hasAutonomous = cfg.mode === 'autonome' || Object.values(cfg.profiles || {}).some(p => p.mode === 'autonome');
    if (hasAutonomous && !dry && !confirm('Mode AUTONOME : Marvin va RÉPONDRE ET ENVOYER automatiquement aux emails non lus correspondant à ton cadrage. Continuer ?')) return;
    if (!await save()) return;
    setRunning(true); setResult(null);
    try {
      const r = await fetch(`${BACKEND}/api/email/automation/run?dry_run=${dry ? 'true' : 'false'}`, { method: 'POST' });
      const d = await r.json();
      setResult(d.detail ? { error: d.detail } : d);
      reloadDrafts();
      reloadOutbox();
    } catch (e) { setResult({ error: e.message }); }
    setRunning(false);
  };

  const MODES = [
    { id: 'manuel', label: '🅜 Manuel', desc: 'Rien d\'automatique. Tu rédiges via les boutons IA.' },
    { id: 'brouillon', label: '🅑 Brouillons auto', desc: 'Marvin prépare les réponses. Tu valides avant tout envoi.' },
    { id: 'differe', label: '⏱️ Envoi différé', desc: 'Marvin prépare puis attend. Tu peux annuler avant l\'heure d\'envoi.' },
    { id: 'autonome', label: '🅐 Autonome', desc: 'Marvin répond ET ENVOIE seul, selon ton cadrage. ⚠️ Puissant.' },
  ];
  const lbl = { display: 'block', fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600, margin: '12px 0 4px' };
  const inp = { width: '100%', padding: '8px 10px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-primary)', fontSize: '12.5px', outline: 'none', boxSizing: 'border-box' };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{ width: '680px', maxWidth: '96vw', maxHeight: '90vh', overflowY: 'auto', background: '#111', border: '1px solid rgba(79, 140, 255,0.3)', borderRadius: '16px', padding: '22px 26px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
          <span style={{ fontWeight: 700, color: '#4f8cff', fontSize: '1rem' }}>⚙️ Réponses automatiques</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '20px' }}>×</button>
        </div>
        <p style={{ margin: '0 0 14px', fontSize: '11.5px', color: 'var(--text-muted)' }}>Choisis quand et comment Marvin répond à ta place. Les réponses sont en français, soignées et sans faute. Tu actives/désactives quand tu veux.</p>

        <label style={lbl}>Profil à configurer</label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '12px' }}>
          <button onClick={() => setProfileAccount('')} style={{ padding: '6px 10px', borderRadius: '8px', cursor: 'pointer', border: `1px solid ${!profileAccount ? '#4f8cff80' : 'var(--border)'}`, background: !profileAccount ? '#4f8cff20' : 'transparent', color: !profileAccount ? '#8ab4ff' : 'var(--text-muted)', fontSize: '11px' }}>🌐 Réglages par défaut</button>
          {accounts.map(account => <button key={account.username} onClick={() => setProfileAccount(account.username)}
            style={{ padding: '6px 10px', borderRadius: '8px', cursor: 'pointer', border: `1px solid ${profileAccount === account.username ? '#4f8cff80' : 'var(--border)'}`, background: profileAccount === account.username ? '#4f8cff20' : 'transparent', color: profileAccount === account.username ? '#8ab4ff' : 'var(--text-muted)', fontSize: '11px' }}>📧 {account.username}</button>)}
        </div>
        {profileAccount && <div style={{ fontSize: '10px', color: '#8ab4ff', margin: '-6px 0 10px' }}>Ces valeurs remplacent les réglages par défaut uniquement pour {profileAccount}.</div>}

        {/* Modes */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
          {MODES.map(m => (
            <button key={m.id} onClick={() => setRule('mode', m.id)}
              style={{ textAlign: 'left', padding: '10px 12px', borderRadius: '10px', cursor: 'pointer',
                background: active.mode === m.id ? 'rgba(79, 140, 255,0.14)' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${active.mode === m.id ? 'rgba(79, 140, 255,0.5)' : 'var(--border)'}` }}>
              <div style={{ fontWeight: 700, fontSize: '13px', color: active.mode === m.id ? '#4f8cff' : 'var(--text-primary)' }}>{m.label}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>{m.desc}</div>
            </button>
          ))}
        </div>

        {active.mode !== 'manuel' && (
          <>
            <label style={lbl}>Consignes générales (comment répondre)</label>
            <textarea value={active.instructions || ''} onChange={e => setRule('instructions', e.target.value)} rows={3}
              placeholder="Ex : Réponds poliment. Pour les demandes de devis, propose un rendez-vous. Indique que je reviens vers eux sous 24h."
              style={{ ...inp, resize: 'vertical' }} />

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div><label style={lbl}>Ton</label><input value={active.tone || ''} onChange={e => setRule('tone', e.target.value)} style={inp} /></div>
              <div><label style={lbl}>Maximum pour cette boîte / passage</label><input type="number" value={active.max_per_run || 5} onChange={e => setRule('max_per_run', Number(e.target.value))} style={inp} /></div>
            </div>

            {active.mode === 'differe' && <div><label style={lbl}>Délai avant envoi (minutes)</label><input type="number" min="1" max="1440" value={active.send_delay_min || 5} onChange={e => setRule('send_delay_min', Number(e.target.value))} style={inp} /></div>}

            <label style={lbl}>Signature (optionnel)</label>
            <textarea value={active.signature || ''} onChange={e => setRule('signature', e.target.value)} rows={2} placeholder={'Vide = signature enregistrée pour cette boîte'} style={{ ...inp, resize: 'vertical' }} />

            {['autonome', 'differe'].includes(active.mode) && (
              <>
                <label style={lbl}>✅ Répondre UNIQUEMENT à ces expéditeurs/domaines (fortement conseillé)</label>
                <MultiValueInput values={active.only_from || []} onChange={v => setRule('only_from', v)} placeholder="client@x.com ou @monentreprise.fr" style={inp} />
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: 4 }}>Tape une adresse ou un domaine, puis appuie sur Entrée ou virgule. Tu peux aussi coller une liste.</div>
                <div style={{ fontSize: '10px', color: '#f59e0b', marginTop: 4 }}>⚠️ Une liste vide bloque volontairement tout envoi automatique.</div>
              </>
            )}
            <label style={lbl}>🚫 Ne JAMAIS répondre à (mots/expéditeurs) — en plus des exclusions auto (no-reply, banque…)</label>
            <MultiValueInput values={active.never_from || []} onChange={v => setRule('never_from', v)} placeholder="spam@, promo ou @pub.com" style={inp} />

            {accounts.length > 0 && (
              <>
                <label style={lbl}>Boîtes activées — sélection explicite obligatoire</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {accounts.map(a => {
                    const on = cfg.accounts.includes(a.username);
                    return <button key={a.id} onClick={() => set('accounts', on ? cfg.accounts.filter(x => x !== a.username) : [...cfg.accounts, a.username])}
                      style={{ padding: '5px 10px', borderRadius: '7px', fontSize: '11px', cursor: 'pointer', border: `1px solid ${on ? 'rgba(79, 140, 255,0.5)' : 'var(--border)'}`, background: on ? 'rgba(79, 140, 255,0.14)' : 'transparent', color: on ? '#4f8cff' : 'var(--text-muted)' }}>{a.username}</button>;
                  })}
                </div>
              </>
            )}

            {!profileAccount && (
              <div style={{ marginTop: '14px', padding: '12px', borderRadius: '10px', border: `1px solid ${cfg.scheduler_enabled ? '#22c55e55' : 'var(--border)'}`, background: cfg.scheduler_enabled ? '#22c55e10' : 'rgba(255,255,255,0.025)' }}>
                <button type="button" onClick={() => set('scheduler_enabled', !cfg.scheduler_enabled)}
                  style={{ width: '100%', textAlign: 'left', border: 0, background: 'transparent', color: cfg.scheduler_enabled ? '#4ade80' : 'var(--text-primary)', cursor: 'pointer', fontWeight: 700, fontSize: '12px' }}>
                  {cfg.scheduler_enabled ? '✅' : '⬜'} Exécuter automatiquement en arrière-plan
                </button>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Toutes les</span>
                  <input type="number" min="2" max="1440" value={cfg.interval_min} onChange={e => set('interval_min', Number(e.target.value))} style={{ ...inp, width: '80px' }} />
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>minutes</span>
                </div>
                <div style={{ fontSize: '10px', color: '#f59e0b', marginTop: '7px' }}>L'activation demande une confirmation séparée. Elle reste désactivée après migration.</div>
              </div>
            )}

            <div style={{ display: 'flex', gap: '8px', marginTop: '18px', flexWrap: 'wrap' }}>
              <button onClick={save} disabled={saving} style={{ padding: '9px 14px', borderRadius: '9px', border: '1px solid var(--border)', background: 'rgba(255,255,255,0.05)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}>{saving ? '⏳…' : '💾 Enregistrer'}</button>
              <button onClick={() => run(true)} disabled={running} style={{ padding: '9px 14px', borderRadius: '9px', border: '1px solid #3b82f650', background: '#3b82f620', color: '#60a5fa', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}>{running ? '⏳…' : '🧪 Tester (simulation)'}</button>
              <button onClick={() => run(false)} disabled={running} style={{ padding: '9px 14px', borderRadius: '9px', border: 'none', background: active.mode === 'autonome' ? 'linear-gradient(135deg,#a855f7,#7c3aed)' : 'linear-gradient(135deg,#4f8cffcc,#4f8cff88)', color: 'white', cursor: 'pointer', fontSize: '12px', fontWeight: 700 }}>
                {running ? '⏳ Traitement…' : active.mode === 'autonome' ? '🚀 Lancer (envoi auto)' : active.mode === 'differe' ? '⏱️ Programmer les réponses' : '📝 Préparer les brouillons'}</button>
            </div>
          </>
        )}

        {/* Résultat du run */}
        {result && (
          <div style={{ marginTop: '14px', padding: '12px 14px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: '10px', fontSize: '12px' }}>
            {result.error ? <span style={{ color: '#f87171' }}>⚠️ {result.error}</span> : (
              <>
                <div style={{ fontWeight: 700, color: '#4f8cff', marginBottom: 6 }}>{result.message}</div>
                {(result.results || []).map((r, i) => (
                  <div key={i} style={{ color: 'var(--text-muted)', padding: '2px 0' }}>
                    {r.action === 'envoyé' ? '✅' : r.action?.startsWith('brouillon') ? '📝' : r.action === 'ignoré' ? '⏭️' : '⚠️'} {r.subject || r.from || ''} <span style={{ opacity: 0.7 }}>— {r.action}{r.reason ? ` (${r.reason})` : ''}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        )}

        {/* Brouillons en attente (mode brouillon) */}
        {drafts.length > 0 && (
          <div style={{ marginTop: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>📝 Brouillons en attente ({drafts.length})</span>
              <button onClick={() => fetch(`${BACKEND}/api/email/automation/drafts/clear`, { method: 'POST' }).then(reloadDrafts)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '11px' }}>Tout effacer</button>
            </div>
            {drafts.map((d, i) => (
              <div key={i} onClick={() => { onOpenDraft({ to: d.to, subject: d.subject, body: d.body, account: d.account }); onClose(); }}
                style={{ padding: '8px 10px', marginBottom: '4px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: '8px', cursor: 'pointer' }}>
                <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>↩ {d.subject}</div>
                <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>à {d.to} · depuis {d.account} — cliquer pour relire et envoyer</div>
              </div>
            ))}
          </div>
        )}

        {outbox.length > 0 && (
          <div style={{ marginTop: '16px' }}>
            <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '6px' }}>⏱️ Envois différés annulables ({outbox.length})</div>
            {outbox.map(item => (
              <div key={item.id} style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'center', padding: '8px 10px', marginBottom: '4px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: '8px' }}>
                <div><div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>{item.subject}</div><div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>à {item.to} · envoi prévu {new Date(item.send_after).toLocaleString('fr-FR')}</div></div>
                <button onClick={() => fetch(`${BACKEND}/api/email/automation/outbox/${encodeURIComponent(item.id)}`, { method: 'DELETE' }).then(reloadOutbox)} style={{ padding: '5px 8px', borderRadius: '7px', border: '1px solid #ef444455', background: '#ef444412', color: '#f87171', cursor: 'pointer', fontSize: '10.5px' }}>Annuler</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Préférences email : signatures par boîte + modèles de réponse
// ══════════════════════════════════════════════════════════════════════════════
function PrefsModal({ accounts, onClose }) {
  const [sigs, setSigs] = useState({});
  const [templates, setTemplates] = useState([]);
  const [newT, setNewT] = useState({ name: '', body: '' });
  const reloadT = () => fetch(`${BACKEND}/api/email/templates`).then(r => r.json()).then(d => setTemplates(d.templates || [])).catch(() => {});
  useEffect(() => {
    fetch(`${BACKEND}/api/email/signatures`).then(r => r.json()).then(d => setSigs(d.signatures || {})).catch(() => {});
    reloadT();
  }, []);
  const saveSig = async (acc, val) => {
    await fetch(`${BACKEND}/api/email/signatures`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account: acc, signature: val }) });
  };
  const addTemplate = async () => {
    if (!newT.name.trim() || !newT.body.trim()) return;
    await fetch(`${BACKEND}/api/email/templates`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newT) });
    setNewT({ name: '', body: '' }); reloadT();
  };
  const delTemplate = async (name) => {
    await fetch(`${BACKEND}/api/email/templates/${encodeURIComponent(name)}`, { method: 'DELETE' }); reloadT();
  };
  const ist = { width: '100%', padding: '8px 10px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-primary)', fontSize: '12.5px', outline: 'none', boxSizing: 'border-box' };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{ width: '660px', maxWidth: '96vw', maxHeight: '90vh', overflowY: 'auto', background: '#111', border: '1px solid rgba(79, 140, 255,0.3)', borderRadius: '16px', padding: '22px 26px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <span style={{ fontWeight: 700, color: '#4f8cff', fontSize: '1rem' }}>📋 Modèles & signatures</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '20px' }}>×</button>
        </div>

        <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>✍️ Signature par boîte (ajoutée automatiquement à la rédaction)</div>
        {accounts.map(a => (
          <div key={a.id} style={{ marginBottom: '10px' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '3px' }}>{a.username}</div>
            <textarea defaultValue={sigs[a.username] || ''} onBlur={e => saveSig(a.username, e.target.value)} rows={2}
              placeholder={'Cordialement,\nVotre nom'} style={{ ...ist, resize: 'vertical' }} />
          </div>
        ))}

        <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)', margin: '18px 0 8px' }}>📋 Modèles de réponse réutilisables</div>
        {templates.map(t => (
          <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 10px', marginBottom: '4px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: '8px' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>{t.name}</div>
              <div style={{ fontSize: '10.5px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.body}</div>
            </div>
            <button onClick={() => delTemplate(t.name)} title="Supprimer ce modèle"
              style={{ padding: '4px 8px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.28)', borderRadius: '7px', color: '#f87171', cursor: 'pointer', fontSize: '12px' }}>🗑️</button>
          </div>
        ))}
        <div style={{ marginTop: '8px', padding: '10px', background: 'rgba(255,255,255,0.03)', border: '1px dashed var(--border)', borderRadius: '8px' }}>
          <input value={newT.name} onChange={e => setNewT(t => ({ ...t, name: e.target.value }))} placeholder="Nom du modèle (ex : Accusé de réception)" style={{ ...ist, marginBottom: '6px' }} />
          <textarea value={newT.body} onChange={e => setNewT(t => ({ ...t, body: e.target.value }))} rows={3} placeholder="Texte du modèle…" style={{ ...ist, resize: 'vertical', marginBottom: '6px' }} />
          <button onClick={addTemplate} style={{ padding: '7px 14px', borderRadius: '8px', border: 'none', background: 'linear-gradient(135deg,#4f8cffcc,#4f8cff88)', color: 'white', cursor: 'pointer', fontWeight: 700, fontSize: '12px' }}>➕ Ajouter le modèle</button>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Surveillance intelligente : alertes des mails importants (notifications bureau)
// ══════════════════════════════════════════════════════════════════════════════
function WatchModal({ accounts, folders = ['INBOX'], onClose }) {
  const [cfg, setCfg] = useState({ enabled: false, interval_min: 5, accounts: [], max_notify: 5 });
  const [alerts, setAlerts] = useState([]);
  const [running, setRunning] = useState(false);
  const [rules, setRules] = useState([]);
  const [newR, setNewR] = useState({ name: '', from_contains: '', subject_contains: '', action: 'move', folder: '', account: '' });
  const [applyingRules, setApplyingRules] = useState(false);
  const reload = () => fetch(`${BACKEND}/api/email/watch/alerts`).then(r => r.json()).then(d => setAlerts(d.alerts || [])).catch(() => {});
  const loadRules = () => fetch(`${BACKEND}/api/email/rules`).then(r => r.json()).then(d => setRules(d.rules || [])).catch(() => {});
  const saveRules = async (next) => { setRules(next); await fetch(`${BACKEND}/api/email/rules`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rules: next }) }); };
  const addRule = () => {
    if (!newR.name.trim() || (!newR.from_contains.trim() && !newR.subject_contains.trim())) { alert('Donne un nom et au moins un critère (expéditeur ou objet).'); return; }
    saveRules([...rules, { ...newR, enabled: true }]);
    setNewR({ name: '', from_contains: '', subject_contains: '', action: 'move', folder: '', account: '' });
  };
  const applyRules = async () => {
    setApplyingRules(true);
    try { const r = await fetch(`${BACKEND}/api/email/rules/run`, { method: 'POST' }); const d = await r.json(); alert(d.message || d.detail || 'Règles appliquées.'); }
    catch (e) { alert('Erreur : ' + e.message); }
    setApplyingRules(false);
  };
  useEffect(() => {
    fetch(`${BACKEND}/api/email/watch`).then(r => r.json()).then(c => setCfg(p => ({ ...p, ...c, accounts: c.accounts || [] }))).catch(() => {});
    reload(); loadRules();
  }, []);
  const save = async (next) => { const c = next || cfg; setCfg(c); await fetch(`${BACKEND}/api/email/watch`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(c) }); };
  const runNow = async () => {
    await save(); setRunning(true);
    try { const r = await fetch(`${BACKEND}/api/email/watch/run`, { method: 'POST' }); const d = await r.json(); alert(d.message || d.detail || 'Vérification terminée.'); reload(); }
    catch (e) { alert('Erreur : ' + e.message); }
    setRunning(false);
  };
  const ist = { padding: '7px 9px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-primary)', fontSize: '12.5px', outline: 'none' };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{ width: '600px', maxWidth: '96vw', maxHeight: '88vh', overflowY: 'auto', background: '#111', border: '1px solid rgba(96,165,250,0.35)', borderRadius: '16px', padding: '22px 26px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
          <span style={{ fontWeight: 700, color: '#60a5fa', fontSize: '1rem' }}>🔔 Surveillance des mails importants</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '20px' }}>×</button>
        </div>
        <p style={{ margin: '0 0 14px', fontSize: '11.5px', color: 'var(--text-muted)' }}>Marvin vérifie tes nouveaux emails en arrière-plan, repère les <strong>importants par IA</strong> (vs pub/newsletter) et t'envoie une <strong>notification Windows</strong>.</p>

        <label style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', background: cfg.enabled ? 'rgba(96,165,250,0.12)' : 'rgba(255,255,255,0.03)', border: `1px solid ${cfg.enabled ? 'rgba(96,165,250,0.45)' : 'var(--border)'}`, borderRadius: '10px', cursor: 'pointer' }}>
          <input type="checkbox" checked={cfg.enabled} onChange={e => save({ ...cfg, enabled: e.target.checked })} />
          <span style={{ fontWeight: 700, fontSize: '13px', color: cfg.enabled ? '#60a5fa' : 'var(--text-primary)' }}>Surveillance {cfg.enabled ? 'ACTIVE' : 'désactivée'}</span>
        </label>

        <div style={{ display: 'flex', gap: '12px', marginTop: '12px' }}>
          <div><div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: 3 }}>Fréquence (min)</div>
            <input type="number" min="2" value={cfg.interval_min} onChange={e => setCfg(c => ({ ...c, interval_min: Number(e.target.value) }))} onBlur={() => save()} style={{ ...ist, width: 90 }} /></div>
          <div><div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: 3 }}>Max notifs / passage</div>
            <input type="number" min="1" value={cfg.max_notify} onChange={e => setCfg(c => ({ ...c, max_notify: Number(e.target.value) }))} onBlur={() => save()} style={{ ...ist, width: 90 }} /></div>
        </div>

        {accounts.length > 0 && (
          <div style={{ marginTop: '12px' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: 4 }}>Boîtes surveillées (aucune = toutes)</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {accounts.map(a => { const on = (cfg.accounts || []).includes(a.username); return (
                <button key={a.id} onClick={() => save({ ...cfg, accounts: on ? cfg.accounts.filter(x => x !== a.username) : [...(cfg.accounts || []), a.username] })}
                  style={{ padding: '5px 10px', borderRadius: 7, fontSize: 11, cursor: 'pointer', border: `1px solid ${on ? 'rgba(96,165,250,0.5)' : 'var(--border)'}`, background: on ? 'rgba(96,165,250,0.14)' : 'transparent', color: on ? '#60a5fa' : 'var(--text-muted)' }}>{a.username}</button>); })}
            </div>
          </div>
        )}

        <button onClick={runNow} disabled={running} style={{ marginTop: 16, padding: '9px 16px', borderRadius: 9, border: 'none', background: 'linear-gradient(135deg,#60a5fa,#3b82f6)', color: 'white', cursor: running ? 'wait' : 'pointer', fontWeight: 700, fontSize: 12 }}>
          {running ? '⏳ Analyse…' : '🔍 Vérifier maintenant'}</button>

        {/* ── Règles de classement automatique ── */}
        <div style={{ borderTop: '1px solid var(--border)', margin: '18px 0 0', paddingTop: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>🗂️ Règles de classement automatique ({rules.length})</span>
            <button onClick={applyRules} disabled={applyingRules} style={{ padding: '4px 10px', fontSize: 11, borderRadius: 7, border: '1px solid rgba(96,165,250,0.4)', background: 'rgba(96,165,250,0.12)', color: '#60a5fa', cursor: applyingRules ? 'wait' : 'pointer', fontWeight: 600 }}>{applyingRules ? '⏳…' : '▶ Appliquer maintenant'}</button>
          </div>
          <p style={{ margin: '0 0 8px', fontSize: 10.5, color: 'var(--text-muted)' }}>Si l'expéditeur OU l'objet contient le texte → action. Appliquées aussi automatiquement quand la surveillance est active.</p>
          {rules.map((r, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 9px', marginBottom: 4, background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: 8 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text-primary)' }}>{r.name}</div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  {r.from_contains ? `de~"${r.from_contains}" ` : ''}{r.subject_contains ? `objet~"${r.subject_contains}" ` : ''}→ {r.action === 'move' ? `📁 ${r.folder}` : r.action === 'mark_read' ? 'lu' : 'non lu'}
                </div>
              </div>
              <button onClick={() => saveRules(rules.filter((_, j) => j !== i))} style={{ padding: '3px 7px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 6, color: '#f87171', cursor: 'pointer', fontSize: 11 }}>🗑️</button>
            </div>
          ))}
          <div style={{ padding: '9px', marginTop: 6, background: 'rgba(255,255,255,0.03)', border: '1px dashed var(--border)', borderRadius: 8 }}>
            <input value={newR.name} onChange={e => setNewR(r => ({ ...r, name: e.target.value }))} placeholder="Nom de la règle (ex : Newsletters)" style={{ ...ist, width: '100%', marginBottom: 6 }} />
            <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
              <input value={newR.from_contains} onChange={e => setNewR(r => ({ ...r, from_contains: e.target.value }))} placeholder="Expéditeur contient…" style={{ ...ist, flex: 1 }} />
              <input value={newR.subject_contains} onChange={e => setNewR(r => ({ ...r, subject_contains: e.target.value }))} placeholder="Objet contient…" style={{ ...ist, flex: 1 }} />
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <select value={newR.action} onChange={e => setNewR(r => ({ ...r, action: e.target.value }))} style={{ ...ist }}>
                <option value="move">📁 Déplacer vers</option>
                <option value="mark_read">Marquer lu</option>
                <option value="mark_unread">Marquer non lu</option>
              </select>
              {newR.action === 'move' && (
                <select value={newR.folder} onChange={e => setNewR(r => ({ ...r, folder: e.target.value }))} style={{ ...ist, flex: 1 }}>
                  <option value="">— dossier —</option>
                  {folders.filter(f => f !== 'INBOX').map(f => <option key={f} value={f}>{f.replace(/\[Gmail\]\//, '')}</option>)}
                </select>
              )}
              <button onClick={addRule} style={{ padding: '7px 12px', borderRadius: 8, border: 'none', background: 'linear-gradient(135deg,#4f8cffcc,#4f8cff88)', color: 'white', cursor: 'pointer', fontWeight: 700, fontSize: 12 }}>➕</button>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '18px 0 6px' }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>🔴 Alertes récentes ({alerts.length})</span>
          {alerts.length > 0 && <button onClick={() => fetch(`${BACKEND}/api/email/watch/alerts/clear`, { method: 'POST' }).then(reload)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 11 }}>Effacer</button>}
        </div>
        {alerts.length === 0 ? <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Aucune alerte pour l'instant.</div> :
          alerts.map((al, i) => (
            <div key={i} style={{ padding: '7px 10px', marginBottom: 4, background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{al.subject || '(sans objet)'}</div>
              <div style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{al.from} · {al.account} · {(al.at || '').replace('T', ' ')}</div>
            </div>
          ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Page principale
// ══════════════════════════════════════════════════════════════════════════════
export default function EmailsPage() {
  const [configured, setConfigured] = useState(null); // null=loading, false=not set, true=set
  const [emails, setEmails] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [loadingInbox, setLoadingInbox] = useState(false);
  const [loadingEmail, setLoadingEmail] = useState(false);
  const [folders, setFolders] = useState(['INBOX']);
  const [activeFolder, setActiveFolder] = useState('INBOX');
  const [searchQ, setSearchQ] = useState('');
  const [compose, setCompose] = useState(false);
  const [replyTo, setReplyTo] = useState(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [accounts, setAccounts] = useState([]);
  const [activeAccount, setActiveAccount] = useState(null); // username de la boîte active
  const [addingAccount, setAddingAccount] = useState(false);
  const [aiDrafting, setAiDrafting] = useState(false);
  const [aiDraft, setAiDraft] = useState(null); // {to, subject, body} -> ouvre la compose pré-remplie
  const [aiSummary, setAiSummary] = useState(null); // résumé IA de l'email ouvert
  const [summarizing, setSummarizing] = useState(false);
  const [digest, setDigest] = useState(null);       // briefing IA de la boîte
  const [digestLoading, setDigestLoading] = useState(false);
  const [showAutomation, setShowAutomation] = useState(false);
  const [showPrefs, setShowPrefs] = useState(false);
  const [showWatch, setShowWatch] = useState(false);
  const LIMIT = 25;

  // Suffixe de requête pour cibler la boîte active
  const acct = (sep) => activeAccount ? `${sep}account=${encodeURIComponent(activeAccount)}` : '';

  // Charger la liste des comptes (multi-boîtes)
  const loadAccounts = useCallback(() => {
    fetch(`${BACKEND}/api/email/accounts`)
      .then(r => r.json())
      .then(d => {
        const list = d.accounts || [];
        setAccounts(list);
        setConfigured(list.length > 0);
        setActiveAccount(prev => (prev && list.some(a => a.username === prev)) ? prev : (d.default || null));
      })
      .catch(() => setConfigured(false));
  }, []);
  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  const removeAccount = useCallback(async (username) => {
    if (!confirm(`Supprimer la boîte « ${username} » de Marvin ?\n\n(Cela retire seulement la connexion ici — ton compte mail et tes messages ne sont pas touchés. Tu pourras la reconnecter quand tu veux.)`)) return;
    try {
      const r = await fetch(`${BACKEND}/api/email/accounts/${encodeURIComponent(username)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error('Le backend n\'a pas répondu');
    } catch (e) {
      alert('Suppression impossible : ' + e.message + '\n(Le backend est-il lancé ?)');
      return;
    }
    if (activeAccount === username) { setActiveAccount(null); setSelectedId(null); setSelectedEmail(null); setSearchQ(''); }
    loadAccounts();
  }, [activeAccount, loadAccounts]);

  // Charger les dossiers (de la boîte active ; en mode unifié on reste sur INBOX)
  useEffect(() => {
    if (!configured) return;
    if (activeAccount === '__all__') { setFolders(['INBOX']); setActiveFolder('INBOX'); return; }
    fetch(`${BACKEND}/api/email/folders${acct('?')}`)
      .then(r => r.json())
      .then(d => { if (d.folders?.length > 0) setFolders(d.folders.slice(0, 12)); })
      .catch(() => {});
  }, [configured, activeAccount]);

  // Charger l'inbox
  const loadInbox = useCallback(async (reset = true) => {
    if (!configured) return;
    setLoadingInbox(true);
    const off = reset ? 0 : offset;
    if (reset) { setOffset(0); setEmails([]); }
    try {
      const url = searchQ.trim()
        ? `${BACKEND}/api/email/search?q=${encodeURIComponent(searchQ)}&folder=${encodeURIComponent(activeFolder)}${acct('&')}`
        : `${BACKEND}/api/email/inbox?folder=${encodeURIComponent(activeFolder)}&limit=${LIMIT}&offset=${off}${acct('&')}`;
      const r = await fetch(url);
      const data = await r.json();
      const list = data.emails || data.results || [];
      setEmails(reset ? list : prev => [...prev, ...list]);
      setHasMore(list.length === LIMIT);
      if (!reset) setOffset(off + LIMIT);
    } catch {}
    setLoadingInbox(false);
  }, [configured, activeFolder, searchQ, offset, activeAccount]);

  useEffect(() => { if (configured) loadInbox(true); }, [configured, activeFolder, activeAccount]);

  // Lire un email
  const openEmail = useCallback(async (id) => {
    setSelectedId(id);
    setSelectedEmail(null);
    setAiSummary(null);
    setLoadingEmail(true);
    // En mode unifié, lire depuis la boîte d'origine de l'email
    const em = emails.find(e => e.id === id);
    const ra = em?._account || (activeAccount === '__all__' ? '' : (activeAccount || ''));
    try {
      const r = await fetch(`${BACKEND}/api/email/read/${id}?folder=${encodeURIComponent(activeFolder)}${ra ? `&account=${encodeURIComponent(ra)}` : ''}`);
      const data = await r.json();
      setSelectedEmail({ ...data, _account: ra || data._account });
      // Marquer comme lu localement
      setEmails(prev => prev.map(e => e.id === id ? { ...e, read: true } : e));
    } catch {}
    setLoadingEmail(false);
  }, [activeFolder, activeAccount, emails]);

  const handleDelete = useCallback(async (id) => {
    if (!confirm('Supprimer cet email ?')) return;
    await fetch(`${BACKEND}/api/email/${id}?folder=${encodeURIComponent(activeFolder)}${acct('&')}`, { method: 'DELETE' });
    setEmails(prev => prev.filter(e => e.id !== id));
    if (selectedId === id) { setSelectedId(null); setSelectedEmail(null); }
  }, [activeFolder, selectedId, activeAccount]);

  const emailAcct = () => (selectedEmail?._account || (activeAccount === '__all__' ? '' : activeAccount)) || '';

  // 📩 Marquer l'email ouvert comme non lu
  const markUnread = useCallback(async () => {
    if (!selectedId) return;
    const a = emailAcct();
    try {
      await fetch(`${BACKEND}/api/email/mark?uid=${encodeURIComponent(selectedId)}&seen=false&folder=${encodeURIComponent(activeFolder)}${a ? `&account=${encodeURIComponent(a)}` : ''}`, { method: 'POST' });
      setEmails(prev => prev.map(e => e.id === selectedId ? { ...e, read: false } : e));
    } catch (e) { alert('Erreur : ' + e.message); }
  }, [selectedId, selectedEmail, activeFolder, activeAccount]);

  // 📁 Déplacer / archiver l'email ouvert vers un dossier
  const moveEmail = useCallback(async (dest) => {
    if (!selectedId || !dest) return;
    const a = emailAcct();
    try {
      const r = await fetch(`${BACKEND}/api/email/move?uid=${encodeURIComponent(selectedId)}&dest=${encodeURIComponent(dest)}&folder=${encodeURIComponent(activeFolder)}${a ? `&account=${encodeURIComponent(a)}` : ''}`, { method: 'POST' });
      if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || 'échec'); }
      setEmails(prev => prev.filter(e => e.id !== selectedId));
      setSelectedId(null); setSelectedEmail(null);
    } catch (e) { alert('Déplacement impossible : ' + e.message); }
  }, [selectedId, selectedEmail, activeFolder, activeAccount]);

  // ✨ Générer une réponse par IA puis ouvrir la fenêtre de composition pré-remplie
  const aiReply = useCallback(async (instruction = '') => {
    if (!selectedEmail) return;
    setAiDrafting(true);
    try {
      const r = await fetch(`${BACKEND}/api/email/draft-reply`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          body: selectedEmail.body || '', subject: selectedEmail.subject || '',
          from: selectedEmail.from || '', instruction,
          account: (selectedEmail._account || (activeAccount === '__all__' ? '' : activeAccount)) || '',
        }),
      });
      const d = await r.json();
      if (d.draft) {
        const to = selectedEmail.from_addr || selectedEmail.from?.match(/<([^>]+)>/)?.[1] || selectedEmail.from || '';
        setAiDraft({ to, subject: d.subject || `Re: ${selectedEmail.subject || ''}`, body: d.draft });
      } else {
        alert(d.detail || d.error || "L'IA n'a pas pu générer de réponse.");
      }
    } catch (e) { alert('Erreur : ' + e.message); }
    setAiDrafting(false);
  }, [selectedEmail, activeAccount]);

  // 📝 Résumer l'email ouvert par IA
  const summarizeEmail = useCallback(async () => {
    if (!selectedEmail) return;
    setSummarizing(true); setAiSummary(null);
    try {
      const r = await fetch(`${BACKEND}/api/email/summarize`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          body: selectedEmail.body || '', subject: selectedEmail.subject || '',
          from: selectedEmail.from || '',
          account: (selectedEmail._account || (activeAccount === '__all__' ? '' : activeAccount)) || '',
        }),
      });
      const d = await r.json();
      setAiSummary(d.summary || d.detail || d.error || 'Résumé indisponible.');
    } catch (e) { setAiSummary('Erreur : ' + e.message); }
    setSummarizing(false);
  }, [selectedEmail, activeAccount]);

  // 🧠 Briefing IA de la boîte (priorise les emails récents)
  const loadDigest = useCallback(async () => {
    setDigestLoading(true); setDigest('');
    try {
      const a = activeAccount || '';
      const r = await fetch(`${BACKEND}/api/email/digest?limit=15${a ? `&account=${encodeURIComponent(a)}` : ''}`);
      const d = await r.json();
      setDigest(d.digest || d.detail || d.error || 'Briefing indisponible.');
    } catch (e) { setDigest('Erreur : ' + e.message); }
    setDigestLoading(false);
  }, [activeAccount]);

  // ✅ Transformer l'email ouvert en tâche
  const [taskCreating, setTaskCreating] = useState(false);
  const emailToTask = useCallback(async () => {
    if (!selectedEmail) return;
    setTaskCreating(true);
    try {
      const r = await fetch(`${BACKEND}/api/email/to-task`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          body: selectedEmail.body || '', subject: selectedEmail.subject || '', from: selectedEmail.from || '',
          account: (selectedEmail._account || (activeAccount === '__all__' ? '' : activeAccount)) || '',
        }),
      });
      const d = await r.json();
      alert(d.message || d.detail || d.error || 'Tâche créée.');
    } catch (e) { alert('Erreur : ' + e.message); }
    setTaskCreating(false);
  }, [selectedEmail, activeAccount]);

  // 📎 Pièces jointes : URL de téléchargement + résumé IA
  const [attSummary, setAttSummary] = useState(null); // {name, summary}
  const [attLoading, setAttLoading] = useState('');
  const attAccount = () => (selectedEmail?._account || (activeAccount === '__all__' ? '' : activeAccount)) || '';
  const attUrl = (name) => `${BACKEND}/api/email/attachment?uid=${encodeURIComponent(selectedId)}&name=${encodeURIComponent(name)}${attAccount() ? `&account=${encodeURIComponent(attAccount())}` : ''}`;
  const SUMMARIZABLE = /\.(pdf|docx|txt|csv|md|log|json)$/i;
  const summarizeAttachment = useCallback(async (name) => {
    setAttLoading(name); setAttSummary(null);
    try {
      const a = attAccount();
      const url = `${BACKEND}/api/email/attachment/summary?uid=${encodeURIComponent(selectedId)}&name=${encodeURIComponent(name)}${a ? `&account=${encodeURIComponent(a)}` : ''}`;
      const r = await fetch(url);
      const d = await r.json();
      setAttSummary({ name, summary: d.summary || d.detail || d.error || 'Résumé indisponible.' });
    } catch (e) { setAttSummary({ name, summary: 'Erreur : ' + e.message }); }
    setAttLoading('');
  }, [selectedEmail, selectedId, activeAccount]);

  if (configured === null) {
    return <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}><LoadingRow /></div>;
  }

  if (!configured && !addingAccount) {
    return <SetupPanel onConfigured={(u) => { setActiveAccount(u || null); loadAccounts(); }} />;
  }

  return (
    <div style={{ display: 'flex', height: '100vh', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}>

      {/* ── Overlay : ajouter une boîte mail ── */}
      {addingAccount && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 60, background: 'rgba(0,0,0,0.7)', overflowY: 'auto', padding: '20px 0' }}>
          <SetupPanel
            title="Ajouter une boîte mail"
            onConfigured={(u) => { setActiveAccount(u || null); setSelectedId(null); setSelectedEmail(null); setAddingAccount(false); loadAccounts(); }}
            onCancel={() => setAddingAccount(false)}
          />
        </div>
      )}

      {/* ── Colonne gauche : dossiers ── */}
      <div style={{ width: '180px', flexShrink: 0, borderRight: '1px solid rgba(255,255,255,0.07)', display: 'flex', flexDirection: 'column', background: '#0d0d0d', padding: '16px 10px' }}>
        <div style={{ marginBottom: '14px', display: 'flex', gap: '6px', flexDirection: 'column' }}>
          <button onClick={() => setCompose(true)}
            style={{ width: '100%', padding: '9px', background: 'linear-gradient(135deg,#4f8cffcc,#4f8cff88)', border: 'none', borderRadius: '10px', color: 'white', cursor: 'pointer', fontWeight: 700, fontSize: '12px' }}>
            ✏️ Nouveau message
          </button>
          <button onClick={() => setShowAutomation(true)}
            title="Configurer les réponses automatiques (3 modes)"
            style={{ width: '100%', padding: '7px', background: 'rgba(168,85,247,0.1)', border: '1px solid rgba(168,85,247,0.3)', borderRadius: '9px', color: '#c084fc', cursor: 'pointer', fontWeight: 600, fontSize: '11px' }}>
            ⚙️ Réponses auto
          </button>
          <button onClick={() => setShowPrefs(true)}
            title="Modèles de réponse & signatures"
            style={{ width: '100%', padding: '7px', background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)', borderRadius: '9px', color: 'var(--text-muted)', cursor: 'pointer', fontWeight: 600, fontSize: '11px' }}>
            📋 Modèles & signatures
          </button>
          <button onClick={() => setShowWatch(true)}
            title="Surveillance des mails importants (notifications)"
            style={{ width: '100%', padding: '7px', background: 'rgba(96,165,250,0.1)', border: '1px solid rgba(96,165,250,0.3)', borderRadius: '9px', color: '#60a5fa', cursor: 'pointer', fontWeight: 600, fontSize: '11px' }}>
            🔔 Surveillance
          </button>
        </div>

        {/* ── Boîtes mail (multi-comptes) ── */}
        <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.06em', marginBottom: '6px', padding: '0 6px' }}>BOÎTES MAIL</div>
        {accounts.length > 1 && (
          <button onClick={() => { setActiveAccount('__all__'); setSelectedId(null); setSelectedEmail(null); setSearchQ(''); setActiveFolder('INBOX'); }}
            style={{ width: '100%', padding: '7px 8px', textAlign: 'left', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '11px', marginBottom: '2px', fontWeight: activeAccount === '__all__' ? 700 : 600,
              background: activeAccount === '__all__' ? 'rgba(96,165,250,0.16)' : 'rgba(96,165,250,0.06)',
              color: activeAccount === '__all__' ? '#60a5fa' : 'var(--text-muted)' }}>
            📬 Toutes les boîtes
          </button>
        )}
        {accounts.map(a => (
          <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: '3px', marginBottom: '2px' }}>
            <button onClick={() => { setActiveAccount(a.username); setSelectedId(null); setSelectedEmail(null); setSearchQ(''); }}
              title={`${a.username} · ${a.auth_type === 'oauth2' ? 'OAuth2 Google' : 'mot de passe d\'application'}`}
              style={{ flex: 1, minWidth: 0, padding: '7px 8px', textAlign: 'left', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '11px',
                background: activeAccount === a.username ? 'rgba(79, 140, 255,0.14)' : 'transparent',
                color: activeAccount === a.username ? '#4f8cff' : 'var(--text-muted)',
                fontWeight: activeAccount === a.username ? 700 : 400,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {a.provider === 'gmail' ? '📧' : a.provider === 'outlook' ? '📨' : '✉️'} {a.username} {a.auth_type === 'oauth2' ? '🔐' : ''}
            </button>
            <button onClick={() => removeAccount(a.username)} title={`Supprimer la boîte ${a.username}`}
              style={{ padding: '5px 8px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.28)', borderRadius: '7px', color: '#f87171', cursor: 'pointer', fontSize: '12px', lineHeight: 1, flexShrink: 0 }}>🗑️</button>
          </div>
        ))}
        <button onClick={() => setAddingAccount(true)}
          style={{ width: '100%', padding: '6px', margin: '4px 0 14px', background: 'rgba(79, 140, 255,0.08)', border: '1px dashed rgba(79, 140, 255,0.35)', borderRadius: '8px', color: '#4f8cff', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}>
          ＋ Ajouter une boîte
        </button>

        <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.06em', marginBottom: '6px', padding: '0 6px' }}>DOSSIERS</div>
        {folders.map(f => (
          <button key={f} onClick={() => { setActiveFolder(f); setSelectedId(null); setSelectedEmail(null); }}
            style={{ width: '100%', padding: '7px 10px', textAlign: 'left', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '12px', marginBottom: '2px',
              background: activeFolder === f ? 'rgba(79, 140, 255,0.12)' : 'transparent',
              color: activeFolder === f ? '#4f8cff' : 'var(--text-muted)',
              fontWeight: activeFolder === f ? 700 : 400,
            }}>
            {f === 'INBOX' ? '📥 INBOX' : f === 'Sent' || f === 'Sent Items' ? '📤 Envoyés' : f === 'Trash' || f === 'Deleted' ? '🗑️ Corbeille' : `📁 ${f.replace(/\[Gmail\]\//,'')}`}
          </button>
        ))}
      </div>

      {/* ── Colonne centrale : liste emails ── */}
      <div style={{ width: '320px', flexShrink: 0, borderRight: '1px solid rgba(255,255,255,0.07)', display: 'flex', flexDirection: 'column' }}>
        {/* Barre recherche */}
        <div style={{ padding: '10px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <form onSubmit={e => { e.preventDefault(); loadInbox(true); }} style={{ display: 'flex', gap: '6px' }}>
            <input value={searchQ} onChange={e => setSearchQ(e.target.value)}
              placeholder="Rechercher…"
              style={{ flex: 1, padding: '7px 12px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-primary)', fontSize: '12px', outline: 'none' }} />
            <button type="submit" style={{ padding: '7px 12px', background: 'rgba(79, 140, 255,0.15)', border: '1px solid rgba(79, 140, 255,0.3)', borderRadius: '8px', color: '#4f8cff', cursor: 'pointer', fontSize: '12px' }}>🔍</button>
            <button type="button" onClick={() => { setSearchQ(''); loadInbox(true); }} disabled={loadingInbox}
              title="Rafraîchir (vérifier les nouveaux messages)"
              style={{ padding: '7px 10px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-muted)', cursor: loadingInbox ? 'wait' : 'pointer', fontSize: '12px' }}>{loadingInbox ? '⏳' : '🔄'}</button>
            {searchQ && <button type="button" onClick={() => { setSearchQ(''); loadInbox(true); }}
              style={{ padding: '7px 10px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '12px' }}>✕</button>}
          </form>
          <button onClick={loadDigest} disabled={digestLoading}
            title="Marvin lit vos emails récents et vous fait un point priorisé (urgent / à traiter / info)."
            style={{ width: '100%', marginTop: '8px', padding: '8px', background: 'rgba(168,85,247,0.12)', border: '1px solid rgba(168,85,247,0.35)', borderRadius: '8px', color: '#c084fc', cursor: digestLoading ? 'wait' : 'pointer', fontSize: '12px', fontWeight: 600 }}>
            {digestLoading ? '⏳ Analyse…' : '🧠 Briefing IA de ma boîte'}
          </button>
        </div>

        {/* Emails */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loadingInbox && emails.length === 0 ? (
            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {[1,2,3,4,5].map(i => <div key={i} style={{ height: '68px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px' }} />)}
            </div>
          ) : emails.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>Aucun email</div>
          ) : (
            <>
              {emails.map(email => {
                const ac = avatarColor(email.from);
                const isActive = selectedId === email.id;
                return (
                  <div key={email.id} onClick={() => openEmail(email.id)}
                    style={{ padding: '12px 14px', borderBottom: '1px solid rgba(255,255,255,0.04)', cursor: 'pointer',
                      background: isActive ? 'rgba(79, 140, 255,0.08)' : 'transparent',
                      borderLeft: `3px solid ${isActive ? '#4f8cff' : 'transparent'}`,
                      transition: 'all 0.15s',
                    }}
                    onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; }}
                    onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '5px' }}>
                      <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: ac, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px', fontWeight: 700, color: 'white', flexShrink: 0, textTransform: 'uppercase' }}>
                        {senderInitials(email.from)}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '12px', fontWeight: email.read ? 400 : 700, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {senderName(email.from)}
                        </div>
                      </div>
                      <span style={{ fontSize: '10px', color: 'var(--text-muted)', flexShrink: 0 }}>{formatDate(email.date)}</span>
                      {!email.read && <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#4f8cff', flexShrink: 0 }} />}
                    </div>
                    <div style={{ fontSize: '12px', fontWeight: email.read ? 400 : 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginLeft: '42px' }}>
                      {email.subject || '(Sans objet)'}
                    </div>
                    {activeAccount === '__all__' && email._account && (
                      <div style={{ marginLeft: '42px', marginTop: '3px' }}>
                        <span style={{ fontSize: '9px', padding: '1px 7px', borderRadius: '6px', background: 'rgba(96,165,250,0.12)', color: '#60a5fa', fontWeight: 600 }}>
                          📬 {email._account}
                        </span>
                      </div>
                    )}
                  </div>
                );
              })}
              {hasMore && (
                <div style={{ padding: '12px', textAlign: 'center' }}>
                  <button onClick={() => loadInbox(false)} disabled={loadingInbox}
                    style={{ padding: '7px 20px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '12px' }}>
                    {loadingInbox ? '⏳…' : 'Charger plus'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Colonne droite : lecture email ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {!selectedId ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: '12px', color: 'var(--text-muted)' }}>
            <div style={{ fontSize: '3rem' }}>📨</div>
            <div style={{ fontSize: '0.9rem' }}>Sélectionnez un email à lire</div>
          </div>
        ) : loadingEmail ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><LoadingRow /></div>
        ) : selectedEmail ? (
          <>
            {/* Toolbar */}
            <div style={{ padding: '12px 20px', borderBottom: '1px solid rgba(255,255,255,0.07)', display: 'flex', gap: '8px', alignItems: 'center', background: 'rgba(0,0,0,0.2)' }}>
              <button onClick={() => setReplyTo({ ...selectedEmail, from_addr: selectedEmail.from?.match(/<([^>]+)>/)?.[1] || selectedEmail.from })}
                style={tbBtn('#4f8cff')}>↩ Répondre</button>
              <button onClick={() => aiReply('')} disabled={aiDrafting}
                title="Marvin lit l'email et rédige la meilleure réponse en français (sans fautes). Vous pourrez la relire avant d'envoyer."
                style={{ ...tbBtn('#a855f7'), opacity: aiDrafting ? 0.6 : 1, cursor: aiDrafting ? 'wait' : 'pointer' }}>
                {aiDrafting ? '⏳ Rédaction…' : '✨ Répondre avec l\'IA'}</button>
              <button onClick={summarizeEmail} disabled={summarizing}
                title="Résumé IA de l'email : synthèse, points clés, action attendue."
                style={{ ...tbBtn('#10b981'), opacity: summarizing ? 0.6 : 1, cursor: summarizing ? 'wait' : 'pointer' }}>
                {summarizing ? '⏳ Résumé…' : '📝 Résumer'}</button>
              <button onClick={emailToTask} disabled={taskCreating}
                title="Créer une tâche depuis cet email (l'IA extrait l'action et l'échéance)."
                style={{ ...tbBtn('#eab308'), opacity: taskCreating ? 0.6 : 1, cursor: taskCreating ? 'wait' : 'pointer' }}>
                {taskCreating ? '⏳…' : '✅ Créer une tâche'}</button>
              <button onClick={() => setCompose(true)} style={tbBtn('#3b82f6')}>✏️ Nouveau</button>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px', alignItems: 'center' }}>
                <button onClick={markUnread} style={tbBtn('#64748b')} title="Marquer comme non lu">📩 Non lu</button>
                <select onChange={e => { if (e.target.value) { moveEmail(e.target.value); e.target.value = ''; } }} defaultValue=""
                  title="Déplacer vers un dossier (= archiver)"
                  style={{ padding: '6px 8px', borderRadius: '8px', background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: '12px', cursor: 'pointer' }}>
                  <option value="">📁 Déplacer…</option>
                  {folders.filter(f => f !== activeFolder).map(f => (
                    <option key={f} value={f}>{f.replace(/\[Gmail\]\//, '')}</option>
                  ))}
                </select>
                <button onClick={() => handleDelete(selectedEmail.id)} style={tbBtn('#ef4444')}>🗑️ Supprimer</button>
              </div>
            </div>

            {/* En-tête email */}
            <div style={{ padding: '20px 24px', borderBottom: '1px solid rgba(255,255,255,0.07)', flexShrink: 0 }}>
              <h2 style={{ margin: '0 0 14px', fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.4 }}>
                {selectedEmail.subject || '(Sans objet)'}
              </h2>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ width: '40px', height: '40px', borderRadius: '50%', background: avatarColor(selectedEmail.from), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', fontWeight: 700, color: 'white', flexShrink: 0, textTransform: 'uppercase' }}>
                  {senderInitials(selectedEmail.from)}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '13px' }}>{senderName(selectedEmail.from)}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{selectedEmail.from}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                    À : {selectedEmail.to}{selectedEmail.cc ? ` · Cc : ${selectedEmail.cc}` : ''}
                  </div>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textAlign: 'right', flexShrink: 0 }}>
                  {selectedEmail.date && new Date(selectedEmail.date).toLocaleString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
              {selectedEmail.attachments?.length > 0 && (
                <div style={{ marginTop: '12px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {selectedEmail.attachments.map((a, i) => (
                    <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 8px 4px 10px', borderRadius: '8px', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', fontSize: '11px', color: 'var(--text-muted)' }}>
                      <a href={attUrl(a.name)} target="_blank" rel="noopener noreferrer" title="Télécharger"
                        style={{ color: 'var(--text-secondary)', textDecoration: 'none' }}>
                        📎 {a.name} ({(a.size / 1024).toFixed(0)} Ko)
                      </a>
                      {SUMMARIZABLE.test(a.name) && (
                        <button onClick={() => summarizeAttachment(a.name)} disabled={attLoading === a.name}
                          title="Résumer cette pièce jointe par IA"
                          style={{ padding: '2px 7px', fontSize: '10px', borderRadius: '6px', border: '1px solid rgba(16,185,129,0.4)', background: 'rgba(16,185,129,0.12)', color: '#34d399', cursor: attLoading === a.name ? 'wait' : 'pointer', fontWeight: 600 }}>
                          {attLoading === a.name ? '⏳' : '📝 Résumer'}
                        </button>
                      )}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Corps de l'email */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
              {/* Résumé IA (si généré) */}
              {(summarizing || aiSummary) && (
                <div style={{ marginBottom: '18px', padding: '14px 16px', background: 'rgba(16,185,129,0.07)', border: '1px solid rgba(16,185,129,0.28)', borderRadius: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 700, color: '#34d399' }}>📝 Résumé IA</span>
                    {aiSummary && <button onClick={() => setAiSummary(null)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '14px' }}>×</button>}
                  </div>
                  <pre style={{ fontFamily: 'inherit', fontSize: '12.5px', lineHeight: 1.6, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', margin: 0, wordBreak: 'break-word' }}>
                    {summarizing ? '⏳ Analyse de l\'email en cours…' : aiSummary}
                  </pre>
                </div>
              )}
              <pre style={{ fontFamily: 'inherit', fontSize: '13px', lineHeight: 1.75, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', margin: 0, wordBreak: 'break-word' }}>
                {selectedEmail.body || '(Aucun contenu texte)'}
              </pre>
            </div>
          </>
        ) : null}
      </div>

      {/* Modales */}
      {compose && <ComposeModal account={activeAccount === '__all__' ? null : activeAccount} onClose={() => setCompose(false)} />}
      {replyTo && <ComposeModal account={replyTo._account || (activeAccount === '__all__' ? null : activeAccount)} replyTo={replyTo} onClose={() => setReplyTo(null)} />}
      {aiDraft && <ComposeModal account={aiDraft.account || selectedEmail?._account || (activeAccount === '__all__' ? null : activeAccount)} prefill={aiDraft} onRegenerate={aiDraft.account ? null : aiReply} onClose={() => setAiDraft(null)} />}
      {showAutomation && <AutomationModal accounts={accounts} onOpenDraft={(d) => setAiDraft(d)} onClose={() => setShowAutomation(false)} />}
      {showPrefs && <PrefsModal accounts={accounts} onClose={() => setShowPrefs(false)} />}
      {showWatch && <WatchModal accounts={accounts} folders={folders} onClose={() => setShowWatch(false)} />}

      {/* Résumé d'une pièce jointe */}
      {attSummary && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
          onClick={e => e.target === e.currentTarget && setAttSummary(null)}>
          <div style={{ width: '600px', maxWidth: '95vw', maxHeight: '85vh', overflowY: 'auto', background: '#111', border: '1px solid rgba(16,185,129,0.35)', borderRadius: '16px', padding: '22px 26px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ fontWeight: 700, color: '#34d399', fontSize: '0.95rem' }}>📎 Résumé · {attSummary.name}</span>
              <button onClick={() => setAttSummary(null)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '20px' }}>×</button>
            </div>
            <pre style={{ fontFamily: 'inherit', fontSize: '13px', lineHeight: 1.7, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', margin: 0, wordBreak: 'break-word' }}>{attSummary.summary}</pre>
          </div>
        </div>
      )}

      {/* Briefing IA de la boîte */}
      {digest !== null && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
          onClick={e => e.target === e.currentTarget && setDigest(null)}>
          <div style={{ width: '640px', maxWidth: '95vw', maxHeight: '85vh', overflowY: 'auto', background: '#111', border: '1px solid rgba(168,85,247,0.35)', borderRadius: '16px', padding: '22px 26px', boxShadow: '0 10px 50px rgba(0,0,0,0.6)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <span style={{ fontWeight: 700, color: '#c084fc', fontSize: '1rem' }}>
                🧠 Briefing IA {activeAccount === '__all__' ? '· toutes les boîtes' : activeAccount ? `· ${activeAccount}` : ''}
              </span>
              <button onClick={() => setDigest(null)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '20px' }}>×</button>
            </div>
            {digestLoading
              ? <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '20px 0', textAlign: 'center' }}>⏳ Marvin analyse et priorise vos emails…</div>
              : <pre style={{ fontFamily: 'inherit', fontSize: '13px', lineHeight: 1.7, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', margin: 0, wordBreak: 'break-word' }}>{digest}</pre>}
          </div>
        </div>
      )}
    </div>
  );
}

function tbBtn(color) {
  return { padding: '6px 14px', background: `${color}15`, border: `1px solid ${color}40`, borderRadius: '8px', color: color, cursor: 'pointer', fontSize: '12px', fontWeight: 600 };
}
