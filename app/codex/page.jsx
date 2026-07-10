'use client';

import { useRouter } from 'next/navigation';
import { useState, useEffect, useCallback } from 'react';
import { useToast } from '@/components/ui/Toast';

const BACKEND = (typeof window !== 'undefined' && window.location ? window.location.protocol + '//' + window.location.hostname + ':8005' : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005'));
const GOLD = '#4f8cff';

export function CodexView() {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState('');
  const { toast } = useToast();
  const flash = (m) => {
    const t = (m || '').trim();
    const type = t.startsWith('❌') ? 'error' : t.startsWith('⚠️') ? 'warning' : t.startsWith('✅') ? 'success' : 'info';
    toast[type](t.replace(/^(✅|❌|⚠️)\s*/, ''));
  };

  const load = useCallback(async () => {
    try { setSt(await fetch(`${BACKEND}/api/codex/status`).then(r => r.json())); } catch { flash('❌ Backend injoignable'); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function act(key, url, body, confirmMsg) {
    if (confirmMsg && !confirm(confirmMsg)) return;
    setBusy(key); flash('⏳ Application…');
    try {
      const r = await fetch(`${BACKEND}${url}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }).then(r => r.json());
      flash(r.success ? `✅ ${r.message || 'Fait'}` : `⚠️ ${r.message || 'Échec'}`);
      load();
    } catch { flash('❌ Backend injoignable'); }
    setBusy('');
  }

  const card = { background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 14, padding: '16px 18px', marginBottom: 16 };
  const chip = (active) => ({ padding: '7px 14px', borderRadius: 9, border: `1px solid ${active ? GOLD : 'var(--border)'}`, background: active ? 'rgba(79, 140, 255,0.12)' : 'transparent', color: active ? GOLD : 'var(--text-secondary)', fontWeight: 700, cursor: 'pointer', fontSize: 12.5 });
  const adapters = st?.adapters?.adapters || [];

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'transparent', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 920, margin: '0 auto' }}>
        <h1 className="holo-text" style={{ margin: 0, fontSize: '1.6rem' }}>🎛️ Système</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 18 }}>
          Les commutateurs Windows essentiels, pilotables ici et depuis le chat. Marvin remplace <code>ms-settings:</code>.
        </div>

        {!st && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Lecture des paramètres…</div>}

        {st && (
          <>
            {/* Plan d'alimentation */}
            <div className="living-card" style={card}>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>⚡ Plan d'alimentation</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {[['balanced', 'Équilibré'], ['performance', 'Performances'], ['powersaver', 'Économie']].map(([p, lbl]) => (
                  <button key={p} onClick={() => act('pw', '/api/codex/power', { plan: p })} disabled={busy === 'pw'} style={chip(st.power?.active_plan === p)}>{lbl}</button>
                ))}
              </div>
            </div>

            {/* Mode sombre */}
            <div className="living-card" style={card}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 180 }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>🌗 Apparence</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Mode actuel : <strong>{st.dark?.mode || '…'}</strong></div>
                </div>
                <button onClick={() => act('dk', '/api/codex/dark', { action: 'toggle' })} disabled={busy === 'dk'} style={chip(false)}>🌗 Basculer sombre/clair</button>
              </div>
            </div>

            {/* Pare-feu */}
            <div className="living-card" style={card}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 180 }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>🛡️ Pare-feu Windows</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{(st.firewall?.status || '…').slice(0, 120)}</div>
                </div>
                <button onClick={() => act('fw', '/api/codex/firewall', { action: 'on' })} disabled={busy === 'fw'} style={chip(false)}>Activer</button>
                <button onClick={() => act('fw', '/api/codex/firewall', { action: 'off' }, '⚠️ Désactiver le pare-feu réduit la sécurité. Continuer ?')} disabled={busy === 'fw'} style={{ ...chip(false), borderColor: 'rgba(239,68,68,0.4)', color: '#f87171' }}>Désactiver</button>
              </div>
            </div>

            {/* Hibernation */}
            <div className="living-card" style={card}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 180 }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>💤 Hibernation</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Désactiver libère plusieurs Go (hiberfil.sys).</div>
                </div>
                <button onClick={() => act('hb', '/api/codex/hibernation', { action: 'on' })} disabled={busy === 'hb'} style={chip(false)}>Activer</button>
                <button onClick={() => act('hb', '/api/codex/hibernation', { action: 'off' })} disabled={busy === 'hb'} style={chip(false)}>Désactiver</button>
              </div>
            </div>

            {/* Cartes réseau */}
            <div className="living-card" style={card}>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>🌐 Cartes réseau</div>
              {adapters.length === 0 && <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>Aucune carte détectée.</div>}
              {adapters.map((a, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderTop: i ? '1px solid var(--border)' : 'none' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13 }}>{a.Name} <span style={{ fontSize: 11, color: a.Status === 'Up' ? '#34d399' : 'var(--text-muted)' }}>· {a.Status}</span></div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{a.InterfaceDescription} · {a.LinkSpeed}</div>
                  </div>
                  {a.Status === 'Up'
                    ? <button onClick={() => act('ad' + i, '/api/codex/adapter', { action: 'disable', name: a.Name }, `Désactiver la carte « ${a.Name} » ?`)} disabled={busy === 'ad' + i} style={{ ...chip(false), fontSize: 11 }}>Désactiver</button>
                    : <button onClick={() => act('ad' + i, '/api/codex/adapter', { action: 'enable', name: a.Name })} disabled={busy === 'ad' + i} style={{ ...chip(false), fontSize: 11 }}>Activer</button>}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function RedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/systeme?tab=systeme'); }, [router]);
  return null;
}
