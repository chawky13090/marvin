'use client';

import { useRouter } from 'next/navigation';
import { useState, useEffect, useCallback } from 'react';
import { useToast } from '@/components/ui/Toast';

const BACKEND = (typeof window !== 'undefined' && window.location ? window.location.protocol + '//' + window.location.hostname + ':8005' : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005'));
const GOLD = '#4f8cff';

export function EmporiumView() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);   // null = pas encore cherché
  const [searching, setSearching] = useState(false);
  const [upgrades, setUpgrades] = useState(null);
  const [loadingUp, setLoadingUp] = useState(false);
  const [busy, setBusy] = useState('');           // id en cours d'action
  const [installed, setInstalled] = useState(null);
  const [loadingInst, setLoadingInst] = useState(false);
  const [instFilter, setInstFilter] = useState('');

  const { toast } = useToast();
  const flash = (m) => {
    const t = (m || '').trim();
    const type = t.startsWith('❌') ? 'error' : t.startsWith('⚠️') ? 'warning' : t.startsWith('✅') ? 'success' : 'info';
    toast[type](t.replace(/^(✅|❌|⚠️)\s*/, ''));
  };

  const loadUpgrades = useCallback(async () => {
    setLoadingUp(true);
    try {
      const r = await fetch(`${BACKEND}/api/winget/upgrades`).then(r => r.json());
      setUpgrades(r.upgrades || []);
    } catch { flash('❌ Backend injoignable'); }
    setLoadingUp(false);
  }, []);
  const loadInstalled = useCallback(async () => {
    setLoadingInst(true);
    try {
      const r = await fetch(`${BACKEND}/api/winget/installed`).then(r => r.json());
      setInstalled(r.apps || []);
    } catch { flash('❌ Backend injoignable'); }
    setLoadingInst(false);
  }, []);
  useEffect(() => { loadUpgrades(); loadInstalled(); }, [loadUpgrades, loadInstalled]);

  async function search() {
    if (!query.trim()) return;
    setSearching(true); setResults(null);
    try {
      const r = await fetch(`${BACKEND}/api/winget/search?q=${encodeURIComponent(query.trim())}`).then(r => r.json());
      if (r.error) { flash('⚠️ ' + r.error); setResults([]); }
      else setResults(r.results || []);
    } catch { flash('❌ Backend injoignable'); setResults([]); }
    setSearching(false);
  }

  async function install(pkg) {
    if (!confirm(`Installer « ${pkg.name} » (${pkg.id}) ?`)) return;
    setBusy(pkg.id); flash(`⏳ Installation de ${pkg.name}… (peut prendre quelques minutes)`);
    try {
      const r = await fetch(`${BACKEND}/api/winget/install`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: pkg.id }) }).then(r => r.json());
      flash(r.success ? `✅ ${pkg.name} installé` : `❌ Échec : ${(r.output || r.message || '').slice(0, 200)}`);
    } catch { flash('❌ Backend injoignable'); }
    setBusy('');
  }

  async function upgradeOne(pkg) {
    setBusy(pkg.id); flash(`⏳ Mise à jour de ${pkg.name}…`);
    try {
      const r = await fetch(`${BACKEND}/api/winget/upgrade`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: pkg.id }) }).then(r => r.json());
      flash(r.success ? `✅ ${pkg.name} mis à jour` : `❌ Échec : ${(r.output || r.message || '').slice(0, 200)}`);
      loadUpgrades();
    } catch { flash('❌ Backend injoignable'); }
    setBusy('');
  }

  async function upgradeAll() {
    if (!confirm(`Mettre à jour TOUS les paquets (${upgrades?.length || 0}) ? Cela peut prendre plusieurs minutes.`)) return;
    setBusy('__all__'); flash('⏳ Mise à jour globale en cours… (ne ferme pas la page)');
    try {
      const r = await fetch(`${BACKEND}/api/winget/upgrade`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ all: true }) }).then(r => r.json());
      flash(r.success ? '✅ Mise à jour globale terminée' : `⚠️ Terminé avec des erreurs : ${(r.output || '').slice(0, 200)}`);
      loadUpgrades();
    } catch { flash('❌ Backend injoignable'); }
    setBusy('');
  }

  async function uninstall(id, name) {
    const label = name || id;
    if (!confirm(`⚠️ Désinstaller « ${label} » ? Action sortante.`)) return;
    setBusy(id); flash(`⏳ Désinstallation de ${label}…`);
    try {
      const r = await fetch(`${BACKEND}/api/winget/uninstall`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) }).then(r => r.json());
      flash(r.success ? `✅ ${label} désinstallé` : `❌ Échec : ${(r.output || r.message || '').slice(0, 200)}`);
      if (r.success) loadInstalled();
    } catch { flash('❌ Backend injoignable'); }
    setBusy('');
  }

  const inp = { padding: '9px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 13, boxSizing: 'border-box' };
  const card = { background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 14, padding: '16px 18px', marginBottom: 18 };
  const btnGold = { padding: '7px 14px', borderRadius: 9, border: 'none', background: GOLD, color: '#0a0a0d', fontWeight: 800, cursor: 'pointer', fontSize: 12.5 };

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'transparent', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 960, margin: '0 auto' }}>
        <h1 className="holo-text" style={{ margin: 0, fontSize: '1.6rem' }}>📦 Logiciels</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 18 }}>
          Gestionnaire de paquets universel (<strong>Winget</strong>) : recherche, installation silencieuse, mises à jour et désinstallation. Tout est aussi pilotable depuis le <strong>chat</strong>.
        </div>

        {/* Recherche */}
        <div style={card}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>🔍 Rechercher & installer</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Nom du logiciel (ex : 7zip, vlc, firefox, notepad++)…"
              style={{ ...inp, flex: 1, minWidth: 240 }} onKeyDown={e => { if (e.key === 'Enter') search(); }} />
            <button onClick={search} disabled={searching || !query.trim()} style={{ ...btnGold, padding: '9px 18px' }}>{searching ? '⏳ Recherche…' : '🔍 Rechercher'}</button>
          </div>
          {results && results.length > 0 && (
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {results.map(r => (
                <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 9, background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{r.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>{r.id} · v{r.version || '?'} · {r.source}</div>
                  </div>
                  <button onClick={() => install(r)} disabled={busy === r.id} style={{ ...btnGold, opacity: busy === r.id ? 0.6 : 1 }}>{busy === r.id ? '⏳…' : '⬇️ Installer'}</button>
                  <button onClick={() => uninstall(r.id, r.name)} disabled={busy === r.id} title="Désinstaller (si installé)" style={{ fontSize: 12, padding: '7px 10px', borderRadius: 9, border: '1px solid rgba(239,68,68,0.4)', background: 'transparent', color: '#f87171', cursor: 'pointer' }}>🗑️</button>
                </div>
              ))}
            </div>
          )}
          {results && results.length === 0 && !searching && <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 10 }}>Aucun résultat.</div>}
        </div>

        {/* Mises à jour */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>⬆️ Mises à jour disponibles {upgrades && `(${upgrades.length})`}</div>
            <span style={{ flex: 1 }} />
            <button onClick={loadUpgrades} disabled={loadingUp} style={{ fontSize: 12, padding: '6px 12px', borderRadius: 9, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>{loadingUp ? '⏳…' : '↻ Rafraîchir'}</button>
            {upgrades && upgrades.length > 0 && (
              <button onClick={upgradeAll} disabled={busy === '__all__'} style={btnGold}>{busy === '__all__' ? '⏳ En cours…' : '🚀 Tout mettre à jour'}</button>
            )}
          </div>
          {loadingUp && upgrades === null && <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>Analyse des paquets…</div>}
          {upgrades && upgrades.length === 0 && !loadingUp && <div style={{ fontSize: 12.5, color: '#34d399' }}>✓ Tout est à jour.</div>}
          {upgrades && upgrades.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
              {upgrades.map(u => (
                <div key={u.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 9, background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{u.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>{u.id} · <span style={{ color: 'var(--text-muted)' }}>{u.version}</span> → <span style={{ color: GOLD }}>{u.available}</span></div>
                  </div>
                  <button onClick={() => upgradeOne(u)} disabled={busy === u.id} style={{ ...btnGold, opacity: busy === u.id ? 0.6 : 1 }}>{busy === u.id ? '⏳…' : '⬆️ Mettre à jour'}</button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Logiciels installés (voir + désinstaller) */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>💽 Logiciels installés {installed && `(${installed.length})`}</div>
            <span style={{ flex: 1 }} />
            <input value={instFilter} onChange={e => setInstFilter(e.target.value)} placeholder="Filtrer…" style={{ ...inp, width: 200, padding: '6px 10px' }} />
            <button onClick={loadInstalled} disabled={loadingInst} style={{ fontSize: 12, padding: '6px 12px', borderRadius: 9, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>{loadingInst ? '⏳…' : '↻ Rafraîchir'}</button>
          </div>
          {loadingInst && installed === null && <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>Inventaire des logiciels installés…</div>}
          {installed && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 460, overflowY: 'auto' }}>
              {installed
                .filter(a => !instFilter.trim() || (a.name + ' ' + a.id).toLowerCase().includes(instFilter.toLowerCase()))
                .map((a, i) => (
                  <div key={a.id + '|' + a.name + '|' + i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px', borderRadius: 9, background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.name}</div>
                      <div style={{ fontSize: 10.5, color: 'var(--text-muted)', fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.id} · v{a.version || '?'}</div>
                    </div>
                    <button onClick={() => uninstall(a.id, a.name)} disabled={busy === a.id} title="Désinstaller"
                      style={{ fontSize: 11.5, padding: '6px 10px', borderRadius: 8, border: '1px solid rgba(239,68,68,0.4)', background: 'transparent', color: '#f87171', cursor: 'pointer', flexShrink: 0, opacity: busy === a.id ? 0.6 : 1 }}>{busy === a.id ? '⏳…' : '🗑️ Désinstaller'}</button>
                  </div>
                ))}
              {installed.length === 0 && !loadingInst && <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>Aucun logiciel listé.</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function RedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/systeme?tab=logiciels'); }, [router]);
  return null;
}
