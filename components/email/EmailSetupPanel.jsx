'use client';
import { useEffect, useState } from 'react';
import { BACKEND_URL as BACKEND } from '@/lib/backend';
import { inputStyle as iSt, labelStyle as lbl } from './emailStyles';
export function SetupPanel({ onConfigured, onCancel, title }) {
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
