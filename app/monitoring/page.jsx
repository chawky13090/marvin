'use client';
import { useState, useEffect, useRef, useMemo } from 'react';
import Link from 'next/link';
import { LoadingRow } from '@/components/ui/Spinner';
import PrettyResult from '@/components/chat/PrettyResult';
import { CircleGauge, BarRow, StatCard, Sparkline, Panel } from '@/components/ui/DashboardKit';
import { useToast } from '@/components/ui/Toast';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

// ── Ligne de processus (bouton Tuer, confirmation avant appel) ─────────────
function ProcessRow({ proc, onKilled }) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  const kill = async () => {
    if (!window.confirm(`Terminer le processus "${proc.name}" (PID ${proc.pid}) ?`)) return;
    setBusy(true);
    try {
      const res = await fetch(`${BACKEND}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_name: 'pc_process_kill', args: { pid: proc.pid }, confirmed: true }),
      });
      const data = await res.json();
      if (data.success ?? data.result?.success) {
        toast.success('Processus terminé', proc.name);
        onKilled?.(proc.pid);
      } else {
        toast.error('Échec', data.error || data.result?.error || 'Impossible de terminer le processus');
      }
    } catch (e) {
      toast.error('Échec', String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '6px 0', fontSize: '12px' }}>
      <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)', width: '48px', flexShrink: 0 }}>{proc.pid}</span>
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>{proc.name}</span>
      <span style={{ fontFamily: 'monospace', color: '#4f8cff', width: '52px', textAlign: 'right' }}>{proc.cpu_percent}%</span>
      <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)', width: '70px', textAlign: 'right' }}>{proc.memory_mb} MB</span>
      <button
        onClick={kill}
        disabled={busy}
        title="Terminer le processus"
        style={{
          padding: '2px 8px', borderRadius: 6, fontSize: 11, cursor: busy ? 'default' : 'pointer',
          border: '1px solid rgba(239,68,68,0.4)', background: 'rgba(239,68,68,0.1)',
          color: '#ef4444', opacity: busy ? 0.5 : 1,
        }}
      >{busy ? '…' : '✕'}</button>
    </div>
  );
}

// ── Ligne d'exécution d'outil (dépliable : args + résultat/erreur) ─────────
function ExecRow({ exec }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const retry = async (e) => {
    e.stopPropagation();
    setRetrying(true);
    try {
      const res = await fetch(`${BACKEND}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_name: exec.tool_name, args: exec.args || {}, confirmed: true }),
      });
      const data = await res.json();
      if (data.success ?? data.result?.success) {
        toast.success('Relancé avec succès', exec.tool_name);
      } else {
        toast.error('Échec au relancement', data.error || data.result?.error || exec.tool_name);
      }
    } catch (e2) {
      toast.error('Échec au relancement', String(e2));
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div style={{
      borderRadius: '8px', background: 'rgba(255,255,255,0.02)',
      border: `1px solid ${open ? 'var(--border-hover)' : 'rgba(255,255,255,0.05)'}`,
      overflow: 'hidden',
    }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: '10px',
          padding: '8px 12px', cursor: 'pointer',
        }}>
        <span style={{
          width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
          background: exec.success ? '#22c55e' : '#ef4444',
          boxShadow: exec.success ? '0 0 5px #22c55e66' : '0 0 5px #ef444466',
        }} />
        <span style={{ fontFamily: 'monospace', fontSize: '12px', color: '#4f8cff', minWidth: '160px' }}>
          {exec.tool_name}
        </span>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)', flex: 1 }}>
          {exec.duration_ms != null ? `${exec.duration_ms}ms` : '—'}
        </span>
        <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
          {exec.created_at ? new Date(exec.created_at + 'Z').toLocaleTimeString('fr-FR') : ''}
        </span>
        {!exec.success && (
          <button
            onClick={retry}
            disabled={retrying}
            title="Relancer cet outil avec les mêmes arguments"
            style={{
              padding: '2px 8px', borderRadius: 6, fontSize: 10, cursor: retrying ? 'default' : 'pointer',
              border: '1px solid rgba(79,140,255,0.4)', background: 'rgba(79,140,255,0.1)',
              color: '#4f8cff', opacity: retrying ? 0.5 : 1, flexShrink: 0,
            }}
          >{retrying ? '…' : '↻ Relancer'}</button>
        )}
        <span style={{ fontSize: '10px', color: 'var(--text-muted)', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}>▸</span>
      </div>
      {open && (
        <div style={{ padding: '0 12px 12px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
          {exec.args && Object.keys(exec.args).length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: 4, letterSpacing: '0.05em' }}>ARGUMENTS</div>
              <div style={{ fontFamily: 'monospace', fontSize: '11px', color: 'var(--text-secondary)', wordBreak: 'break-all' }}>
                {JSON.stringify(exec.args)}
              </div>
            </div>
          )}
          {exec.result && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: 4, letterSpacing: '0.05em' }}>
                {exec.success ? 'RÉSULTAT' : 'ERREUR'}
              </div>
              <div style={{ fontSize: '12px' }}>
                <PrettyResult result={exec.result} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Page principale
// ══════════════════════════════════════════════════════════════════════════════
export default function MonitoringPage() {
  const [metrics, setMetrics] = useState(null);
  const [history, setHistory] = useState({ cpu: [], ram: [] });
  const [toolHistory, setToolHistory] = useState([]);
  const [toolStats, setToolStats] = useState(null);
  const [connected, setConnected] = useState(false);
  const [execFilter, setExecFilter] = useState('all');   // all | success | failed
  const [execSearch, setExecSearch] = useState('');
  const evtRef = useRef(null);
  const MAX_HISTORY = 60; // 2 min de données (1 point / 2s)

  // ── SSE monitoring ────────────────────────────────────────────────────────
  useEffect(() => {
    const es = new EventSource(`${BACKEND}/api/monitor`, { withCredentials: true });
    evtRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.error) return;
        setMetrics(data);
        setHistory(prev => ({
          cpu: [...prev.cpu.slice(-(MAX_HISTORY - 1)), data.cpu_percent],
          ram: [...prev.ram.slice(-(MAX_HISTORY - 1)), data.ram_percent],
        }));
        setConnected(true);
      } catch {}
    };

    return () => es.close();
  }, []);

  // ── Historique d'exécution ────────────────────────────────────────────────
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const [hRes, sRes] = await Promise.all([
          fetch(`${BACKEND}/api/history?limit=100`),
          fetch(`${BACKEND}/api/history/stats`),
        ]);
        if (hRes.ok) setToolHistory(await hRes.json());
        if (sRes.ok) setToolStats(await sRes.json());
      } catch {}
    };
    fetchHistory();
    const iv = setInterval(fetchHistory, 10000);
    return () => clearInterval(iv);
  }, []);

  const filteredHistory = useMemo(() => {
    const q = execSearch.trim().toLowerCase();
    return toolHistory.filter(e => {
      if (execFilter === 'success' && !e.success) return false;
      if (execFilter === 'failed' && e.success) return false;
      if (q && !e.tool_name?.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [toolHistory, execFilter, execSearch]);

  const failRate = toolStats && toolStats.total > 0 ? Math.round((toolStats.failed / toolStats.total) * 100) : 0;

  const pulse = connected ? { animation: 'pulse 2s infinite' } : {};

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}>
      <div style={{ padding: '28px 32px', maxWidth: 1400, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '28px' }}>
          <div style={{
            width: '10px', height: '10px', borderRadius: '50%',
            background: connected ? '#22c55e' : '#6b7280',
            boxShadow: connected ? '0 0 8px #22c55e88' : 'none',
            ...pulse,
          }} />
          <h1 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 700, letterSpacing: '0.04em' }}>
            Monitoring Système
          </h1>
          <span style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
            {connected ? '● Live · mise à jour toutes les 2s' : '○ Déconnecté'}
          </span>
        </div>

        {!metrics ? (
          <LoadingRow label="Connexion au serveur de monitoring…" />
        ) : (
          <>
            {/* ── Jauges CPU + RAM + Réseau + Batterie ── */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
              gap: '16px',
              marginBottom: '20px',
            }}>
              {/* CPU */}
              <div style={{
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.07)',
                borderRadius: '14px',
                padding: '20px 24px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>⚡ CPU</span>
                  <span style={{ fontFamily: 'monospace', fontSize: '11px', color: 'var(--text-muted)' }}>
                    {metrics.cpu_count} cœurs
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
                  <CircleGauge value={metrics.cpu_percent} label="CPU" color="#4f8cff" size={110} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>Historique 2 min</div>
                    <Sparkline data={history.cpu} color="#4f8cff" width={140} />
                  </div>
                </div>
              </div>

              {/* RAM */}
              <div style={{
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.07)',
                borderRadius: '14px',
                padding: '20px 24px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>🧠 RAM</span>
                  <span style={{ fontFamily: 'monospace', fontSize: '11px', color: 'var(--text-muted)' }}>
                    {metrics.ram_total_gb} GB total
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
                  <CircleGauge value={metrics.ram_percent} label="RAM" color="#3b82f6" size={110} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                      Utilisé: <strong style={{ color: 'var(--text-secondary)' }}>{metrics.ram_used_gb} GB</strong>
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                      Libre: <strong style={{ color: 'var(--text-secondary)' }}>
                        {(metrics.ram_total_gb - metrics.ram_used_gb).toFixed(1)} GB
                      </strong>
                    </div>
                    <Sparkline data={history.ram} color="#3b82f6" width={140} />
                  </div>
                </div>
              </div>

              {/* Réseau */}
              <div style={{
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.07)',
                borderRadius: '14px',
                padding: '20px 24px',
              }}>
                <div style={{ marginBottom: '16px' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>🌐 Réseau</span>
                </div>
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                  <StatCard label="Envoyé" value={metrics.net_sent_mb} unit="MB" icon="↑" color="#22c55e" />
                  <StatCard label="Reçu" value={metrics.net_recv_mb} unit="MB" icon="↓" color="#06b6d4" />
                </div>
              </div>

              {/* GPU */}
              {metrics.gpu && metrics.gpu.name && (
                <div style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(255,255,255,0.07)',
                  borderRadius: '14px',
                  padding: '20px 24px',
                }}>
                  <div style={{ fontWeight: 600, fontSize: '0.95rem', marginBottom: '16px' }}>🎮 GPU</div>
                  <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '8px', fontWeight: 600 }}>
                    {metrics.gpu.name}
                  </div>
                  <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                    {metrics.gpu.vram_gb != null && (
                      <StatCard label="VRAM" value={metrics.gpu.vram_gb} unit="GB" icon="▮" color="#8b5cf6" />
                    )}
                    {metrics.gpu.backend && (
                      <StatCard label="Backend" value={metrics.gpu.backend.toUpperCase()} icon="⚙" color="#06b6d4" />
                    )}
                  </div>
                </div>
              )}

              {/* Batterie (laptop uniquement) */}
              {metrics.battery && (
                <div style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(255,255,255,0.07)',
                  borderRadius: '14px',
                  padding: '20px 24px',
                }}>
                  <div style={{ fontWeight: 600, fontSize: '0.95rem', marginBottom: '16px' }}>
                    {metrics.battery.plugged ? '🔌 Batterie (secteur)' : '🔋 Batterie'}
                  </div>
                  <CircleGauge
                    value={metrics.battery.percent}
                    label={metrics.battery.plugged ? 'En charge' : 'Décharge'}
                    color={metrics.battery.percent < 20 ? '#ef4444' : metrics.battery.percent < 50 ? '#f97316' : '#22c55e'}
                  />
                </div>
              )}
            </div>

            {/* ── Alerte disque(s) plein(s) — actionnable ── */}
            {metrics.disks && metrics.disks.some(d => d.percent > 85) && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '12px',
                background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)',
                borderRadius: '12px', padding: '14px 20px', marginBottom: '20px',
              }}>
                <span style={{ fontSize: '18px' }}>⚠️</span>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)', flex: 1 }}>
                  {metrics.disks.filter(d => d.percent > 85).map(d => `${d.device} à ${d.percent}%`).join(', ')} — espace disque presque plein.
                </span>
                <Link href="/systeme?tab=nettoyage" style={{
                  padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600,
                  border: '1px solid rgba(239,68,68,0.4)', background: 'rgba(239,68,68,0.15)',
                  color: '#ef4444', textDecoration: 'none', flexShrink: 0,
                }}>🧹 Nettoyer</Link>
              </div>
            )}

            {/* ── Disques ── */}
            {metrics.disks && metrics.disks.length > 0 && (
              <div style={{
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.07)',
                borderRadius: '14px',
                padding: '20px 24px',
                marginBottom: '20px',
              }}>
                <div style={{ fontWeight: 600, fontSize: '0.95rem', marginBottom: '16px' }}>💾 Disques</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
                  {metrics.disks.map((d, i) => (
                    <div key={i}>
                      <BarRow
                        label={`${d.device} (${d.mountpoint})`}
                        used={d.used_gb}
                        total={d.total_gb}
                        color="#8b5cf6"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Top processus (CPU) ── */}
            {metrics.top_processes && metrics.top_processes.length > 0 && (
              <Panel
                title={<>🧩 Top processus <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(par CPU)</span></>}
                style={{ marginBottom: '20px', maxHeight: 320 }}
              >
                <div style={{ padding: '0 20px 4px', display: 'flex', gap: '10px', fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
                  <span style={{ width: '48px' }}>PID</span>
                  <span style={{ flex: 1 }}>NOM</span>
                  <span style={{ width: '52px', textAlign: 'right' }}>CPU</span>
                  <span style={{ width: '70px', textAlign: 'right' }}>RAM</span>
                  <span style={{ width: '28px' }} />
                </div>
                <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 20px 16px' }}>
                  {metrics.top_processes.map(p => <ProcessRow key={p.pid} proc={p} />)}
                </div>
              </Panel>
            )}

            {/* ── Historique d'exécution des outils — panneaux à défilement indépendant ── */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '16px', alignItems: 'start' }}>
              {/* Liste */}
              <Panel
                title={<>🔧 Dernières exécutions d&apos;outils <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({filteredHistory.length})</span></>}
                style={{ maxHeight: 560 }}
                action={
                  <div style={{ display: 'flex', gap: 6 }}>
                    {[['all', 'Tout'], ['success', '✅'], ['failed', '❌']].map(([v, lbl]) => (
                      <button key={v} onClick={() => setExecFilter(v)}
                        style={{
                          padding: '3px 10px', borderRadius: 6, fontSize: 11, cursor: 'pointer',
                          border: `1px solid ${execFilter === v ? 'var(--accent-primary)' : 'var(--border)'}`,
                          background: execFilter === v ? 'rgba(79, 140, 255,0.12)' : 'transparent',
                          color: execFilter === v ? 'var(--accent-primary)' : 'var(--text-muted)',
                        }}>{lbl}</button>
                    ))}
                  </div>
                }
              >
                <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
                  <input
                    value={execSearch}
                    onChange={e => setExecSearch(e.target.value)}
                    placeholder="Filtrer par nom d'outil…"
                    style={{
                      width: '100%', padding: '7px 10px', borderRadius: 8,
                      border: '1px solid var(--border)', background: 'rgba(255,255,255,0.03)',
                      color: 'var(--text-primary)', fontSize: 12, boxSizing: 'border-box',
                    }}
                  />
                </div>
                <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 20px 20px' }}>
                  {filteredHistory.length === 0 ? (
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', textAlign: 'center', padding: '20px 0' }}>
                      {toolHistory.length === 0 ? "Aucune exécution pour l'instant" : 'Aucun résultat pour ce filtre.'}
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {filteredHistory.map(exec => <ExecRow key={exec.id} exec={exec} />)}
                    </div>
                  )}
                </div>
              </Panel>

              {/* Stats */}
              <Panel title="📊 Statistiques" style={{ maxHeight: 560 }}>
                <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 20px 20px' }}>
                  {toolStats ? (
                    <>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                          <span style={{ color: 'var(--text-muted)' }}>Total</span>
                          <span style={{ fontFamily: 'monospace', color: 'var(--text-secondary)' }}>{toolStats.total}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                          <span style={{ color: 'var(--text-muted)' }}>✅ Succès</span>
                          <span style={{ fontFamily: 'monospace', color: '#22c55e' }}>{toolStats.success}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                          <span style={{ color: 'var(--text-muted)' }}>❌ Échecs</span>
                          <span style={{ fontFamily: 'monospace', color: '#ef4444' }}>{toolStats.failed}</span>
                        </div>
                        <div style={{
                          display: 'flex', justifyContent: 'space-between', fontSize: '12px',
                          marginTop: 4, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)',
                        }}>
                          <span style={{ color: 'var(--text-muted)' }}>Taux d&apos;échec</span>
                          <span style={{
                            fontFamily: 'monospace', fontWeight: 700,
                            color: failRate > 25 ? '#ef4444' : failRate > 10 ? '#f97316' : '#22c55e',
                          }}>{failRate}%</span>
                        </div>
                      </div>
                      {toolStats.by_tool?.length > 0 && (
                        <>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px', letterSpacing: '0.05em' }}>
                            TOP OUTILS
                          </div>
                          {toolStats.by_tool.map((t, i) => (
                            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '5px' }}>
                              <span style={{ fontFamily: 'monospace', color: '#4f8cff', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '160px', whiteSpace: 'nowrap' }}>
                                {t.tool}
                              </span>
                              <span style={{ color: 'var(--text-muted)' }}>×{t.count}</span>
                            </div>
                          ))}
                        </>
                      )}
                    </>
                  ) : (
                    <LoadingRow />
                  )}
                </div>
              </Panel>
            </div>
          </>
        )}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}
