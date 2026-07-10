'use client';

import { useRouter } from 'next/navigation';
import { useState, useEffect, useCallback } from 'react';
import { useToast } from '@/components/ui/Toast';

const BACKEND = (typeof window !== 'undefined' && window.location ? window.location.protocol + '//' + window.location.hostname + ':8005' : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005'));
const GOLD = '#4f8cff';

export function PantheonView() {
  const [tele, setTele] = useState(null);
  const [bloat, setBloat] = useState(null);
  const [sel, setSel] = useState({});
  const [net, setNet] = useState(null);
  const [busy, setBusy] = useState('');
  const { toast } = useToast();
  const flash = (m) => {
    const t = (m || '').trim();
    const type = t.startsWith('❌') ? 'error' : t.startsWith('⚠️') ? 'warning' : t.startsWith('✅') ? 'success' : 'info';
    toast[type](t.replace(/^(✅|❌|⚠️)\s*/, ''));
  };

  const load = useCallback(async () => {
    try { setTele(await fetch(`${BACKEND}/api/pantheon/telemetry`).then(r => r.json())); } catch {}
    try { setBloat(await fetch(`${BACKEND}/api/pantheon/debloat`).then(r => r.json())); } catch {}
    try { setNet(await fetch(`${BACKEND}/api/pantheon/network`).then(r => r.json())); } catch {}
  }, []);
  useEffect(() => { load(); }, [load]);

  async function restorePoint() {
    if (!confirm('Créer un point de restauration système maintenant ? (recommandé avant toute optimisation)')) return;
    setBusy('rp'); flash('⏳ Création du point de restauration… (peut prendre 1 min)');
    try {
      const r = await fetch(`${BACKEND}/api/pantheon/restore-point`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(r => r.json());
      flash(r.success ? '✅ Point de restauration créé' : `⚠️ ${r.message || 'Échec'}`);
    } catch { flash('❌ Backend injoignable'); }
    setBusy('');
  }

  async function toggleTelemetry() {
    const disabling = tele?.allow_telemetry !== '0';
    if (!confirm(`${disabling ? 'Désactiver' : 'Réactiver'} la télémétrie Windows ? Sauvegarde automatique, réversible. (droits admin requis)`)) return;
    setBusy('tele'); flash('⏳ Application…');
    try {
      const r = await fetch(`${BACKEND}/api/pantheon/telemetry`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: disabling ? 'disable' : 'enable' }) }).then(r => r.json());
      flash(r.success ? `✅ ${r.message}` : `⚠️ ${r.message}`);
      load();
    } catch { flash('❌ Backend injoignable'); }
    setBusy('');
  }

  async function removeSelected() {
    const pkgs = Object.keys(sel).filter(k => sel[k]);
    if (pkgs.length === 0) { flash('Sélectionne au moins une application.'); return; }
    if (!confirm(`Désinstaller ${pkgs.length} application(s) ?\n${pkgs.join(', ')}\n(réinstallables via le Store ; droits admin requis)`)) return;
    setBusy('bloat'); flash('⏳ Désinstallation…');
    try {
      const r = await fetch(`${BACKEND}/api/pantheon/debloat/remove`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ packages: pkgs }) }).then(r => r.json());
      flash(r.success ? `✅ ${r.message}` : `⚠️ ${r.message}`);
      setSel({}); load();
    } catch { flash('❌ Backend injoignable'); }
    setBusy('');
  }

  async function applyNetwork() {
    if (!confirm('Appliquer le durcissement réseau léger (cache DNS + auto-tuning TCP) ? (droits admin)')) return;
    setBusy('net'); flash('⏳ Optimisation réseau…');
    try {
      const r = await fetch(`${BACKEND}/api/pantheon/network/apply`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(r => r.json());
      flash(r.success ? `✅ ${r.message}` : `⚠️ ${r.message}`);
      load();
    } catch { flash('❌ Backend injoignable'); }
    setBusy('');
  }

  const card = { background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 14, padding: '16px 18px', marginBottom: 18 };
  const btnGold = { padding: '8px 16px', borderRadius: 9, border: 'none', background: GOLD, color: '#0a0a0d', fontWeight: 800, cursor: 'pointer', fontSize: 12.5 };
  const teleOff = tele?.allow_telemetry === '0';

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'transparent', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 960, margin: '0 auto' }}>
        <h1 className="holo-text" style={{ margin: 0, fontSize: '1.6rem' }}>🚀 Optimisation</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 18 }}>
          Tweaks de performance & confidentialité (télémétrie, bloatware, réseau) façon WinToys / Chris Titus — <strong>chaque modification est sauvegardée et réversible</strong>. Pilotable aussi depuis le chat.
        </div>

        {/* Sécurité d'abord */}
        <div className="living-card" style={{ ...card, borderColor: 'rgba(79, 140, 255,0.3)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 14, fontWeight: 700 }}>🛡️ Filet de sécurité</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3 }}>Crée un point de restauration AVANT toute modification. Recommandé.</div>
            </div>
            <button onClick={restorePoint} disabled={busy === 'rp'} style={btnGold}>{busy === 'rp' ? '⏳…' : '🛡️ Créer un point de restauration'}</button>
          </div>
        </div>

        {/* Télémétrie */}
        <div className="living-card" style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 14, fontWeight: 700 }}>🔕 Télémétrie Windows</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3 }}>
                Service DiagTrack : <strong style={{ color: tele?.diagtrack === 'Running' ? '#f0a85a' : '#34d399' }}>{tele?.diagtrack || '…'}</strong>
                {' · '}AllowTelemetry : <strong style={{ color: teleOff ? '#34d399' : '#f0a85a' }}>{tele?.allow_telemetry ?? '…'}</strong>
                {teleOff ? ' — ✅ désactivée' : ''}
              </div>
            </div>
            <button onClick={toggleTelemetry} disabled={busy === 'tele'} style={teleOff ? { ...btnGold, background: 'transparent', color: 'var(--text-secondary)', border: '1px solid var(--border)' } : btnGold}>
              {busy === 'tele' ? '⏳…' : (teleOff ? '↩️ Réactiver' : '🔕 Désactiver la télémétrie')}
            </button>
          </div>
        </div>

        {/* Debloat */}
        <div className="living-card" style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>🧹 Débloatage (applications d'usine) {bloat && `· ${bloat.count}`}</div>
            <span style={{ flex: 1 }} />
            {bloat?.removable?.length > 0 && (
              <button onClick={removeSelected} disabled={busy === 'bloat'} style={btnGold}>{busy === 'bloat' ? '⏳…' : `🗑️ Désinstaller la sélection (${Object.values(sel).filter(Boolean).length})`}</button>
            )}
          </div>
          {!bloat && <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>Analyse…</div>}
          {bloat?.removable?.length === 0 && <div style={{ fontSize: 12.5, color: '#34d399' }}>✓ Aucun bloatware connu détecté.</div>}
          {bloat?.removable?.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 6 }}>
              {bloat.removable.map(p => (
                <label key={p} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, padding: '6px 8px', borderRadius: 8, background: sel[p] ? 'rgba(79, 140, 255,0.08)' : 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', cursor: 'pointer' }}>
                  <input type="checkbox" checked={!!sel[p]} onChange={e => setSel(s => ({ ...s, [p]: e.target.checked }))} />
                  <span style={{ fontFamily: 'monospace' }}>{p.replace('Microsoft.', '')}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Réseau */}
        <div className="living-card" style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 14, fontWeight: 700 }}>🌐 Réseau</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3, fontFamily: 'monospace', whiteSpace: 'pre-wrap', maxHeight: 60, overflow: 'hidden' }}>{(net?.output || '…').split('\n').slice(0, 2).join(' · ')}</div>
            </div>
            <button onClick={applyNetwork} disabled={busy === 'net'} style={btnGold}>{busy === 'net' ? '⏳…' : '🚀 Optimiser le réseau'}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function RedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/systeme?tab=optimisation'); }, [router]);
  return null;
}
