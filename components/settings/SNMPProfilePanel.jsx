'use client';

import { useCallback, useEffect, useState } from 'react';
import { BACKEND_URL } from '@/lib/backend';

const EMPTY = { name: '', username: '', auth_key: '', priv_key: '', auth_protocol: 'sha256', priv_protocol: 'aes128', context_name: '', port: 161 };

export function SNMPProfilePanel() {
  const [profiles, setProfiles] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [testHosts, setTestHosts] = useState({});
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const response = await fetch(`${BACKEND_URL}/api/snmp-profiles`);
    if (!response.ok) throw new Error(`Profils SNMP HTTP ${response.status}`);
    setProfiles((await response.json()).profiles || []);
  }, []);

  useEffect(() => { load().catch(error => setMessage(error.message)); }, [load]);

  async function create(event) {
    event.preventDefault();
    setBusy(true); setMessage('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/snmp-profiles`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...form, port: Number(form.port) }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `Création HTTP ${response.status}`);
      setForm(EMPTY); await load(); setMessage('Profil SNMPv3 protégé enregistré.');
    } catch (error) { setMessage(error.message); } finally { setBusy(false); }
  }

  async function remove(profile) {
    if (!window.confirm(`Supprimer le profil SNMPv3 « ${profile.name} » ?`)) return;
    const response = await fetch(`${BACKEND_URL}/api/snmp-profiles/${profile.id}`, { method: 'DELETE' });
    const payload = await response.json();
    if (!response.ok) { setMessage(payload.detail || `Suppression HTTP ${response.status}`); return; }
    await load(); setMessage('Profil supprimé.');
  }

  async function test(profile) {
    const host = String(testHosts[profile.id] || '').trim();
    if (!host) { setMessage('Indiquez une IP ou un nom DNS à tester.'); return; }
    setBusy(true); setMessage('Test SNMPv3 en cours…');
    try {
      const response = await fetch(`${BACKEND_URL}/api/snmp-profiles/${profile.id}/test`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ host }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `Test HTTP ${response.status}`);
      setMessage(`SNMPv3 validé sur ${host} : ${payload.values?.sysName || 'réponse reçue'}.`); await load();
    } catch (error) { setMessage(error.message); await load(); } finally { setBusy(false); }
  }

  const field = (key, label, type = 'text') => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>
      {label}
      <input type={type} value={form[key]} autoComplete="off" onChange={event => setForm(current => ({ ...current, [key]: event.target.value }))} style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }} />
    </label>
  );

  return <section style={{ padding: 16, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
    <div style={{ fontWeight: 650 }}>Supervision réseau SNMPv3</div>
    <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-xs)', lineHeight: 1.5 }}>
      Profils de lecture seule pour switches, routeurs, pare-feu et serveurs. Les clés sont chiffrées par DPAPI et ne sont jamais envoyées au modèle. SHA-256 + AES-128 est recommandé.
    </p>
    <form onSubmit={create} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))', gap: 10 }}>
      {field('name', 'Nom du profil')}{field('username', 'Utilisateur SNMPv3')}{field('auth_key', 'Clé d’authentification', 'password')}
      {form.priv_protocol !== 'none' && field('priv_key', 'Clé de confidentialité', 'password')}
      {field('context_name', 'Contexte (optionnel)')}{field('port', 'Port', 'number')}
      <label style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>Authentification<select value={form.auth_protocol} onChange={event => setForm(current => ({ ...current, auth_protocol: event.target.value }))}><option value="sha256">SHA-256</option><option value="sha1">SHA-1 (compatibilité)</option></select></label>
      <label style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>Confidentialité<select value={form.priv_protocol} onChange={event => setForm(current => ({ ...current, priv_protocol: event.target.value }))}><option value="aes128">AES-128</option><option value="none">Sans chiffrement</option></select></label>
      <button className="btn btn-primary" disabled={busy} type="submit">Enregistrer sous DPAPI</button>
    </form>
    {message && <div role="status" style={{ marginTop: 10, color: 'var(--text-secondary)', fontSize: 'var(--font-xs)' }}>{message}</div>}
    <div style={{ display: 'grid', gap: 8, marginTop: 14 }}>
      {profiles.map(profile => <div key={profile.id} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', padding: 10, border: '1px solid var(--border)', borderRadius: 8 }}>
        <strong>{profile.name}</strong><span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{profile.username} · {profile.auth_protocol.toUpperCase()} · {profile.priv_protocol.toUpperCase()} · {profile.last_test_ok == null ? 'non testé' : profile.last_test_ok ? 'validé' : 'échec'}</span>
        <input aria-label={`Hôte de test ${profile.name}`} placeholder="IP ou DNS de test" value={testHosts[profile.id] || ''} onChange={event => setTestHosts(current => ({ ...current, [profile.id]: event.target.value }))} style={{ marginLeft: 'auto', minWidth: 180 }} />
        <button className="btn btn-ghost" type="button" disabled={busy} onClick={() => test(profile)}>Tester</button>
        <button className="btn btn-ghost" type="button" onClick={() => remove(profile)}>Supprimer</button>
      </div>)}
    </div>
  </section>;
}
