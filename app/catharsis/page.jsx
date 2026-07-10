'use client';

import { useRouter } from 'next/navigation';
import { useState, useCallback, useEffect } from 'react';
import { useToast } from '@/components/ui/Toast';

const BACKEND = (typeof window !== 'undefined' && window.location ? window.location.protocol + '//' + window.location.hostname + ':8005' : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005'));
const CYAN = '#38bdf8';

const ICONS = {
  temp_user: '🗑️', temp_windows: '🗑️', thumbnails: '🖼️', prefetch: '⚡', recent: '📄',
  error_reports: '⚠️', delivery_opt: '🔄', recycle_bin: '♻️', crash_dumps: '💥',
  dx_cache: '🎮', font_cache: '🔤', edge_cache: '🌐', chrome_cache: '🌐', firefox_cache: '🦊',
};
const GROUP_ORDER = ['Windows', 'Navigateurs', 'Système', 'Autres'];

export function CatharsisView() {
  const [scan, setScan] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [sel, setSel] = useState({});
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();
  const flash = (m) => {
    const t = (m || '').trim();
    const type = t.startsWith('❌') ? 'error' : t.startsWith('⚠️') ? 'warning' : t.startsWith('✅') ? 'success' : 'info';
    toast[type](t.replace(/^(✅|❌|⚠️)\s*/, ''));
  };

  const doScan = useCallback(async () => {
    setScanning(true); flash('🔎 Analyse de l\'espace récupérable…');
    try {
      const r = await fetch(`${BACKEND}/api/catharsis/scan`).then(r => r.json());
      setScan(r);
      const s = {}; (r.categories || []).forEach(c => { if (c.bytes > 0) s[c.id] = true; });
      setSel(s);
      flash(`✅ ${r.total_mb} Mo récupérables`);
    } catch { flash('❌ Backend injoignable'); }
    setScanning(false);
  }, []);
  useEffect(() => { doScan(); }, [doScan]);

  async function clean() {
    const cats = Object.keys(sel).filter(k => sel[k]);
    if (cats.length === 0) { flash('Sélectionne au moins une tuile.'); return; }
    const mb = (scan?.categories || []).filter(c => cats.includes(c.id)).reduce((a, c) => a + c.mb, 0);
    if (!confirm(`Nettoyer ${cats.length} catégorie(s) (~${mb.toFixed(0)} Mo) ? Suppression définitive des fichiers temporaires/caches.`)) return;
    setBusy(true); flash('🧹 Nettoyage en cours…');
    try {
      const r = await fetch(`${BACKEND}/api/catharsis/clean`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ categories: cats }) }).then(r => r.json());
      flash(r.success ? `✅ ${r.message}` : `⚠️ ${r.message}`);
      doScan();
    } catch { flash('❌ Backend injoignable'); }
    setBusy(false);
  }

  const cats = scan?.categories || [];
  const selMb = cats.filter(c => sel[c.id]).reduce((a, c) => a + c.mb, 0);
  const groups = {};
  cats.forEach(c => { (groups[c.group] = groups[c.group] || []).push(c); });
  const groupNames = Object.keys(groups).sort((a, b) => GROUP_ORDER.indexOf(a) - GROUP_ORDER.indexOf(b));
  const toggle = (id) => setSel(s => ({ ...s, [id]: !s[id] }));
  const toggleGroup = (gname, on) => setSel(s => { const n = { ...s }; groups[gname].forEach(c => { if (c.bytes > 0) n[c.id] = on; }); return n; });

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'transparent', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 1040, margin: '0 auto' }}>
        <h1 className="holo-text" style={{ margin: 0, fontSize: '1.6rem' }}>🧹 Nettoyage</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
          Purge intelligente façon CCleaner : <strong>analyse d'abord</strong>, puis sélectionne les tuiles à nettoyer. Ne touche que des dossiers temporaires/caches connus. Pilotable aussi depuis le <strong>chat</strong>.
        </div>

        {/* Barre d'action */}
        <div className="living-card" style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', marginBottom: 18, padding: '14px 18px', borderRadius: 14, background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)' }}>
          <button onClick={doScan} disabled={scanning} style={{ padding: '10px 20px', borderRadius: 10, border: `1px solid ${CYAN}`, background: 'rgba(56, 189, 248,0.1)', color: CYAN, fontWeight: 800, cursor: 'pointer', fontSize: 13 }}>{scanning ? '⏳ Analyse…' : '🔎 Analyser'}</button>
          <div style={{ lineHeight: 1.2 }}>
            <div style={{ fontSize: 26, fontWeight: 800, color: CYAN }}>{scan ? scan.total_mb : '—'} <span style={{ fontSize: 14, color: 'var(--text-muted)' }}>Mo récupérables</span></div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{cats.filter(c => c.bytes > 0).length} catégories analysées</div>
          </div>
          <span style={{ flex: 1 }} />
          <button onClick={clean} disabled={busy || selMb <= 0} style={{ padding: '12px 22px', borderRadius: 11, border: 'none', background: CYAN, color: '#06251f', fontWeight: 800, cursor: 'pointer', fontSize: 14, opacity: busy || selMb <= 0 ? 0.55 : 1, boxShadow: selMb > 0 ? '0 0 22px rgba(56, 189, 248,0.3)' : 'none' }}>{busy ? '⏳ Nettoyage…' : `🧹 Nettoyer la sélection (${selMb.toFixed(0)} Mo)`}</button>
        </div>

        {scanning && !scan && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Analyse de l'espace récupérable en cours…</div>}

        {groupNames.map(gname => (
          <div key={gname} style={{ marginBottom: 22 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <h2 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: 'var(--text-secondary)', letterSpacing: '0.04em' }}>{gname}</h2>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{groups[gname].reduce((a, c) => a + c.mb, 0).toFixed(0)} Mo</span>
              <span style={{ flex: 1 }} />
              <button onClick={() => toggleGroup(gname, true)} style={{ fontSize: 10.5, padding: '3px 9px', borderRadius: 7, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer' }}>Tout cocher</button>
              <button onClick={() => toggleGroup(gname, false)} style={{ fontSize: 10.5, padding: '3px 9px', borderRadius: 7, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer' }}>Décocher</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
              {groups[gname].map(c => {
                const on = !!sel[c.id]; const empty = c.bytes <= 0;
                return (
                  <button key={c.id} onClick={() => !empty && toggle(c.id)} disabled={empty}
                    className="living-card"
                    style={{
                      textAlign: 'left', cursor: empty ? 'default' : 'pointer', padding: '13px 14px', borderRadius: 13,
                      background: on ? 'rgba(56, 189, 248,0.08)' : 'rgba(255,255,255,0.02)',
                      border: `1px solid ${on ? 'rgba(56, 189, 248,0.5)' : 'var(--border)'}`,
                      opacity: empty ? 0.4 : 1, color: 'var(--text-primary)', position: 'relative',
                    }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                      <span style={{ fontSize: 22, lineHeight: 1 }}>{ICONS[c.id] || '🧽'}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.25 }}>{c.label}</div>
                        <div style={{ fontSize: 17, fontWeight: 800, marginTop: 4, color: c.mb >= 100 ? '#f0a85a' : (c.mb >= 1 ? CYAN : 'var(--text-muted)'), fontFamily: 'monospace' }}>{c.mb >= 1 ? `${c.mb} Mo` : (empty ? 'vide' : '< 1 Mo')}</div>
                      </div>
                      <span style={{ width: 20, height: 20, borderRadius: 6, flexShrink: 0, border: `1.5px solid ${on ? CYAN : 'var(--border-hover)'}`, background: on ? CYAN : 'transparent', color: '#06251f', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 900 }}>{on ? '✓' : ''}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function RedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/systeme?tab=nettoyage'); }, [router]);
  return null;
}
