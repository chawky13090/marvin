'use client';

import { useRouter } from 'next/navigation';
import { useState, useEffect, useCallback } from 'react';
import { useToast } from '@/components/ui/Toast';
import { CircleGauge } from '@/components/ui/DashboardKit';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

const LV = {
  ok: { icon: '✅', color: '#34d399' },
  warning: { icon: '🟡', color: '#eab308' },
  error: { icon: '🔴', color: '#f87171' },
  info: { icon: 'ℹ️', color: '#60a5fa' },
};
const FIX_LABEL = { prune_docs: 'Nettoyer l\'index', disable_broken_subs: 'Désactiver', clear_logo: 'Retirer le logo' };

export function SanteView() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [fixing, setFixing] = useState('');
  const { toast } = useToast();

  const run = useCallback(async () => {
    setBusy(true);
    try { const r = await fetch(`${BACKEND}/api/doctor`).then(r => r.json()); setData(r); } catch { setData({ error: 'Backend injoignable' }); }
    setBusy(false);
  }, []);
  useEffect(() => { run(); }, [run]);

  async function fix(fixId) {
    setFixing(fixId);
    try {
      const r = await fetch(`${BACKEND}/api/doctor/fix`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fix: fixId }) }).then(r => r.json());
      if (r.success) toast.success(r.message);
      else toast.warning(r.error || 'Échec');
      if (r.diagnostics) setData(r.diagnostics);
    } catch { toast.error('Échec du correctif'); }
    setFixing('');
  }

  const score = data?.score ?? 0;

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'transparent', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 820, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
          <h1 style={{ margin: 0, fontSize: '1.6rem', color: '#34d399' }}>🩺 Santé de Marvin</h1>
          <button onClick={run} disabled={busy} style={{ padding: '9px 16px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>{busy ? '⏳ Diagnostic…' : '🔄 Relancer'}</button>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 18 }}>
          Auto-diagnostic déterministe (sans IA, sans token) : Marvin vérifie son installation et te donne un score. Idéal après une installation sur un nouveau PC.
        </div>

        {data?.error && <div style={{ color: '#f87171', fontSize: 14 }}>⚠️ {data.error}</div>}

        {data && !data.error && (
          <>
            {/* Score */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 22, background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 16, padding: '20px 24px', marginBottom: 18 }}>
              <CircleGauge value={score} label="SANTÉ" size={96} invert suffix="" />
              <div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{data.verdict}</div>
                <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>
                  {data.errors} erreur(s) · {data.warnings} avertissement(s) · {data.checks?.length} vérification(s)
                </div>
              </div>
            </div>

            {/* Modèles à installer */}
            {data.pull_suggestions?.length > 0 && (
              <div style={{ background: 'rgba(234,179,8,0.08)', border: '1px solid rgba(234,179,8,0.3)', borderRadius: 12, padding: '12px 16px', marginBottom: 16, fontSize: 13 }}>
                <strong style={{ color: '#eab308' }}>📥 Modèles à installer</strong> (dans un terminal) :
                {data.pull_suggestions.map((m, i) => (
                  <div key={i} style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 4, color: 'var(--text-secondary)' }}>ollama pull {m}</div>
                ))}
              </div>
            )}

            {/* Checks */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {(data.checks || []).map((c, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 11 }}>
                  <span style={{ fontSize: 16 }}>{(LV[c.level] || LV.info).icon}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{c.label}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{c.message}</div>
                  </div>
                  {c.fix && !c.fix.startsWith('pull:') && (
                    <button onClick={() => fix(c.fix)} disabled={fixing === c.fix}
                      style={{ fontSize: 12, padding: '6px 12px', borderRadius: 8, border: 'none', background: 'rgba(52,211,153,0.2)', color: '#34d399', cursor: 'pointer', fontWeight: 700, whiteSpace: 'nowrap' }}>
                      {fixing === c.fix ? '⏳' : '🔧 ' + (FIX_LABEL[c.fix] || 'Corriger')}
                    </button>
                  )}
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
  useEffect(() => { router.replace('/systeme?tab=sante'); }, [router]);
  return null;
}
