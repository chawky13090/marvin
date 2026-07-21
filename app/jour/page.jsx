'use client';

import { useState, useEffect, useCallback } from 'react';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

const PRIO = { high: { c: '#f87171', l: '🔴 Haute' }, medium: { c: '#eab308', l: '🟡 Moyenne' }, low: { c: '#60a5fa', l: '🔵 Basse' } };

function Stat({ icon, value, label, color }) {
  return (
    <div style={{ flex: 1, minWidth: 120, padding: '16px 18px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: 14 }}>
      <div style={{ fontSize: 26, fontWeight: 800, color: color || 'var(--text-primary)' }}>{icon} {value}</div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
    </div>
  );
}

export default function JourPage() {
  const [data, setData] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, a] = await Promise.all([
        fetch(`${BACKEND}/api/briefing`).then(r => r.json()),
        fetch(`${BACKEND}/api/email/watch/alerts`).then(r => r.json()).catch(() => ({ alerts: [] })),
      ]);
      setData(b.detail ? { error: b.detail } : b);
      setAlerts(a.alerts || []);
    } catch (e) {
      setData({ error: e.message + ' (le backend est-il lancé ?)' });
    }
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  // ── Marvin proactif : briefing matin + bilan du soir + anticipation ───────────
  const [pcfg, setPcfg] = useState(null);     // morning_briefing
  const [ecfg, setEcfg] = useState(null);     // evening_recap
  const [acfg, setAcfg] = useState(null);     // anticipation
  const [qcfg, setQcfg] = useState(null);     // quiet_hours (v2.150 — "heures calmes")
  const [showSettings, setShowSettings] = useState(false);
  const [testMsg, setTestMsg] = useState('');
  useEffect(() => {
    fetch(`${BACKEND}/api/proactive`).then(r => r.json())
      .then(r => {
        setPcfg(r.morning_briefing || { enabled: false, time: '08:00', voice: false });
        setEcfg(r.evening_recap || { enabled: false, time: '18:30', voice: false });
        setAcfg(r.anticipation || { enabled: false, interval_min: 30, overdue_tasks: true, upcoming_events: true, upcoming_events_min: 30 });
        setQcfg(r.quiet_hours || { enabled: false, start: '22:00', end: '07:00' });
      })
      .catch(() => {});
  }, []);
  async function saveBlock(key, next, setter) {
    setter(next);
    try { await fetch(`${BACKEND}/api/proactive`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [key]: next }) }); } catch {}
  }
  const saveProactive = (next) => saveBlock('morning_briefing', next, setPcfg);
  const saveEvening = (next) => saveBlock('evening_recap', next, setEcfg);
  const saveAnticip = (next) => saveBlock('anticipation', next, setAcfg);
  const saveQuiet = (next) => saveBlock('quiet_hours', next, setQcfg);
  async function testProactive(kind = 'morning') {
    setTestMsg('⏳ Génération…');
    try {
      const r = await fetch(`${BACKEND}/api/proactive/run?kind=${kind}`, { method: 'POST' }).then(r => r.json());
      const msg = kind === 'anticipation' ? `${r.count || 0} alerte(s) envoyée(s)` : (r.summary || 'Notification envoyée');
      setTestMsg('✅ ' + msg);
    } catch { setTestMsg('❌ Échec'); }
    setTimeout(() => setTestMsg(''), 6000);
  }

  // ── Telegram (alertes sur le téléphone) ──────────────────────────────────────
  const [tg, setTg] = useState(null);
  const [tgForm, setTgForm] = useState({ bot_token: '', chat_id: '' });
  const [tgMsg, setTgMsg] = useState('');
  useEffect(() => {
    fetch(`${BACKEND}/api/telegram`).then(r => r.json())
      .then(r => { setTg(r); setTgForm(f => ({ ...f, chat_id: r.chat_id || '' })); }).catch(() => {});
  }, []);
  async function saveTelegram(patch) {
    const body = { ...patch };
    try {
      await fetch(`${BACKEND}/api/telegram`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const r = await fetch(`${BACKEND}/api/telegram`).then(r => r.json()); setTg(r);
    } catch {}
  }
  async function testTelegram() {
    setTgMsg('⏳ Envoi…');
    try { const r = await fetch(`${BACKEND}/api/telegram/test`, { method: 'POST' }).then(r => r.json()); setTgMsg(r.error ? '❌ ' + r.error : '✅ Message envoyé sur Telegram !'); }
    catch { setTgMsg('❌ Échec'); }
    setTimeout(() => setTgMsg(''), 7000);
  }

  const tasks = data?.tasks || [];

  // Auto-configuration + modes de performance selon le matériel
  const [ac, setAc] = useState(null);
  const [modeBusy, setModeBusy] = useState(false);
  useEffect(() => { fetch(`${BACKEND}/api/auto-config`).then(r => r.json()).then(setAc).catch(() => {}); }, []);
  async function reanalyze() { try { const r = await fetch(`${BACKEND}/api/auto-config`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(r => r.json()); setAc(r); } catch {} }
  async function setMode(m) {
    setModeBusy(true);
    try { const r = await fetch(`${BACKEND}/api/auto-config`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: m }) }).then(r => r.json()); setAc(r); } catch {}
    setModeBusy(false);
  }

  // Journal d'audit (transparence : ce que Marvin a fait, surtout en autonome)
  const [audit, setAudit] = useState(null);
  const [showAudit, setShowAudit] = useState(false);
  useEffect(() => { if (showAudit) fetch(`${BACKEND}/api/audit?limit=25`).then(r => r.json()).then(setAudit).catch(() => {}); }, [showAudit]);
  const SRC = { chat: '💬', ui: '🖱️', proactif: '🔔', cron: '⏰', agent: '🤖' };

  return (
    <div style={{ height: '100vh', overflowY: 'auto', background: 'var(--bg-primary)', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 880, margin: '0 auto' }}>
        {/* En-tête */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 10 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '1.6rem', color: '#4f8cff' }}>🌅 Mon jour</h1>
            {data?.date && <div style={{ fontSize: 13, color: 'var(--text-muted)', textTransform: 'capitalize' }}>{data.date}</div>}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {(() => { const anyOn = pcfg?.enabled || ecfg?.enabled || acfg?.enabled; return (
            <button onClick={() => setShowSettings(s => !s)} title="Marvin proactif : briefing, bilan du soir, anticipation"
              style={{ padding: '9px 14px', borderRadius: 10, border: '1px solid var(--border)', background: anyOn ? 'rgba(52,211,153,0.14)' : 'rgba(255,255,255,0.04)', color: anyOn ? '#34d399' : 'var(--text-secondary)', cursor: 'pointer', fontWeight: 700, fontSize: 13 }}>
              {anyOn ? '⏰ Proactif ●' : '⏰ Proactif'}
            </button> ); })()}
            <button onClick={load} disabled={loading}
              style={{ padding: '9px 16px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(79, 140, 255,0.12)', color: '#4f8cff', cursor: loading ? 'wait' : 'pointer', fontWeight: 700, fontSize: 13 }}>
              {loading ? '⏳ Analyse…' : '🔄 Actualiser'}
            </button>
          </div>
        </div>

        {/* Panneau briefing automatique */}
        {showSettings && pcfg && (
          <div style={{ padding: '16px 18px', background: 'rgba(52,211,153,0.05)', border: '1px solid rgba(52,211,153,0.25)', borderRadius: 14, marginBottom: 18 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#34d399', marginBottom: 10 }}>⏰ Briefing automatique du matin</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, alignItems: 'center' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                <input type="checkbox" checked={!!pcfg.enabled} onChange={e => saveProactive({ ...pcfg, enabled: e.target.checked })} />
                Activer
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                Heure
                <input type="time" value={pcfg.time || '08:00'} onChange={e => saveProactive({ ...pcfg, time: e.target.value })}
                  style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 8, padding: '5px 8px' }} />
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                <input type="checkbox" checked={!!pcfg.voice} onChange={e => saveProactive({ ...pcfg, voice: e.target.checked })} />
                🔊 Le lire à voix haute
              </label>
              <button onClick={testProactive} style={{ marginLeft: 'auto', padding: '7px 14px', borderRadius: 9, border: '1px solid var(--border)', background: 'rgba(79, 140, 255,0.12)', color: '#4f8cff', cursor: 'pointer', fontSize: 12, fontWeight: 700 }}>
                ▶ Tester maintenant
              </button>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10 }}>
              Chaque jour à l'heure choisie, Marvin t'enverra une notification avec ton briefing{pcfg.voice ? ' et te le lira à voix haute' : ''}. {testMsg && <strong style={{ color: '#34d399' }}>{testMsg}</strong>}
            </div>

            {/* Bilan du soir */}
            {ecfg && (
              <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#a78bfa', marginBottom: 10 }}>🌙 Bilan du soir</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={!!ecfg.enabled} onChange={e => saveEvening({ ...ecfg, enabled: e.target.checked })} /> Activer
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                    Heure
                    <input type="time" value={ecfg.time || '18:30'} onChange={e => saveEvening({ ...ecfg, time: e.target.value })}
                      style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 8, padding: '5px 8px' }} />
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={!!ecfg.voice} onChange={e => saveEvening({ ...ecfg, voice: e.target.checked })} /> 🔊 Lire à voix haute
                  </label>
                  <button onClick={() => testProactive('evening')} style={{ marginLeft: 'auto', padding: '7px 14px', borderRadius: 9, border: '1px solid var(--border)', background: 'rgba(167,139,250,0.12)', color: '#a78bfa', cursor: 'pointer', fontSize: 12, fontWeight: 700 }}>▶ Tester</button>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>Le soir : tâches encore en attente, RDV de demain, mails non lus.</div>
              </div>
            )}

            {/* Anticipation */}
            {acfg && (
              <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#f59e0b', marginBottom: 10 }}>🔔 Anticipation (Marvin te prévient avant que ça coince)</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={!!acfg.enabled} onChange={e => saveAnticip({ ...acfg, enabled: e.target.checked })} /> Activer
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                    Vérifie toutes les
                    <input type="number" min="5" max="240" value={acfg.interval_min || 30} onChange={e => saveAnticip({ ...acfg, interval_min: Number(e.target.value) })}
                      style={{ width: 60, background: 'rgba(255,255,255,0.05)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 8, padding: '5px 8px' }} /> min
                  </label>
                  <button onClick={() => testProactive('anticipation')} style={{ marginLeft: 'auto', padding: '7px 14px', borderRadius: 9, border: '1px solid var(--border)', background: 'rgba(245,158,11,0.12)', color: '#f59e0b', cursor: 'pointer', fontSize: 12, fontWeight: 700 }}>▶ Tester</button>
                </div>
                <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 10 }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
                    <input type="checkbox" checked={acfg.overdue_tasks !== false} onChange={e => saveAnticip({ ...acfg, overdue_tasks: e.target.checked })} /> ⏰ Tâches en retard
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
                    <input type="checkbox" checked={acfg.upcoming_events !== false} onChange={e => saveAnticip({ ...acfg, upcoming_events: e.target.checked })} /> 📅 RDV imminent (≤ {acfg.upcoming_events_min || 30} min)
                  </label>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>Notifications (et Telegram si activé) dédupliquées : un même item ne te prévient qu'une fois par jour.</div>
              </div>
            )}

            {/* Heures calmes (v2.150) */}
            {qcfg && (
              <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8', marginBottom: 10 }}>🌙 Heures calmes</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={!!qcfg.enabled} onChange={e => saveQuiet({ ...qcfg, enabled: e.target.checked })} /> Activer
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                    De
                    <input type="time" value={qcfg.start || '22:00'} onChange={e => saveQuiet({ ...qcfg, start: e.target.value })}
                      style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 8, padding: '5px 8px' }} />
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                    à
                    <input type="time" value={qcfg.end || '07:00'} onChange={e => saveQuiet({ ...qcfg, end: e.target.value })}
                      style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 8, padding: '5px 8px' }} />
                  </label>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>Aucune notification proactive (briefing, bilan, anticipation) sur cette plage horaire — les demandes que tu fais toi-même dans le chat ne sont jamais bloquées.</div>
              </div>
            )}

            {/* Telegram */}
            {tg && (
              <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: '#60a5fa' }}>📲 Alertes sur Telegram</span>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
                    <input type="checkbox" checked={!!tg.enabled} onChange={e => saveTelegram({ enabled: e.target.checked })} disabled={!tg.has_token} />
                    Activer
                  </label>
                  {tg.has_token && <button onClick={testTelegram} className="btn btn-ghost" style={{ fontSize: 11, padding: '4px 10px', marginLeft: 'auto' }}>Tester l'envoi</button>}
                </div>
                {!tg.has_token && (
                  <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <input placeholder="Jeton du bot (BotFather)" value={tgForm.bot_token} onChange={e => setTgForm(f => ({ ...f, bot_token: e.target.value }))}
                      style={{ padding: '7px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 12 }} />
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input placeholder="Ton chat_id (via @userinfobot)" value={tgForm.chat_id} onChange={e => setTgForm(f => ({ ...f, chat_id: e.target.value }))}
                        style={{ flex: 1, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 12 }} />
                      <button onClick={() => saveTelegram({ bot_token: tgForm.bot_token, chat_id: tgForm.chat_id, enabled: true })} className="btn btn-primary" style={{ fontSize: 12 }}>Connecter</button>
                    </div>
                  </div>
                )}
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
                  Reçois tes mails importants et ton briefing sur ton téléphone. {tg.has_token ? `Connecté (chat ${tg.chat_id}).` : 'Crée un bot avec @BotFather, colle le jeton + ton chat_id.'} {tgMsg && <strong style={{ color: '#60a5fa' }}>{tgMsg}</strong>}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Statistiques */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
          <Stat icon="📋" value={data?.tasks_pending ?? '—'} label="Tâches en attente" />
          <Stat icon="🔴" value={data?.tasks_urgent ?? '—'} label="Tâches urgentes" color="#f87171" />
          <Stat icon="📧" value={data?.unread ?? '—'} label="Emails non lus" color="#60a5fa" />
          <Stat icon="🔔" value={alerts.length} label="Alertes importantes" color="#c084fc" />
        </div>

        {/* Auto-configuration des modèles selon le matériel */}
        {ac?.hardware && (
          <div style={{ padding: '12px 16px', background: 'rgba(96,165,250,0.05)', border: '1px solid rgba(96,165,250,0.2)', borderRadius: 12, marginBottom: 18, fontSize: 12.5, color: 'var(--text-secondary)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <span><strong style={{ color: '#60a5fa' }}>🧩 Auto-config</strong> · {ac.hardware.gpu} · {ac.hardware.vram_gb > 0 ? `${ac.hardware.vram_gb} Go VRAM` : `CPU (${ac.hardware.ram_gb} Go RAM)`}</span>
              <button onClick={reanalyze} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)', cursor: 'pointer' }}>🔄 Ré-analyser</button>
            </div>
            <div style={{ marginTop: 6, color: 'var(--text-muted)' }}>
              Modèles choisis : agent <b style={{ color: 'var(--text-secondary)' }}>{ac.applied?.agent}</b> · chat <b style={{ color: 'var(--text-secondary)' }}>{ac.applied?.chat}</b> · analyse <b style={{ color: 'var(--text-secondary)' }}>{ac.applied?.analysis}</b>
              {ac.recommended_to_install?.length > 0 && <span style={{ color: '#eab308' }}> · 💡 pour mieux : {ac.recommended_to_install.join(', ')}</span>}
            </div>

            {/* Modes de performance */}
            {ac.modes?.length > 0 && (
              <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
                <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginBottom: 7 }}>
                  Mode de performance {ac.is_override ? '(forcé)' : `(auto : ${ac.auto_mode})`} {modeBusy && '⏳'}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  <button onClick={() => setMode('auto')} disabled={modeBusy} title="Choisir automatiquement selon la machine"
                    style={{ fontSize: 11.5, padding: '5px 11px', borderRadius: 20, cursor: 'pointer',
                      background: !ac.is_override ? 'rgba(96,165,250,0.25)' : 'rgba(255,255,255,0.04)',
                      border: `1px solid ${!ac.is_override ? 'rgba(96,165,250,0.6)' : 'var(--border)'}`,
                      color: !ac.is_override ? '#93c5fd' : 'var(--text-secondary)', fontWeight: !ac.is_override ? 700 : 400 }}>
                    🤖 Auto
                  </button>
                  {ac.modes.map(m => {
                    const active = ac.is_override && ac.mode === m.key;
                    return (
                      <button key={m.key} onClick={() => setMode(m.key)} disabled={modeBusy} title={m.desc}
                        style={{ fontSize: 11.5, padding: '5px 11px', borderRadius: 20, cursor: 'pointer',
                          background: active ? 'rgba(96,165,250,0.25)' : 'rgba(255,255,255,0.04)',
                          border: `1px solid ${active ? 'rgba(96,165,250,0.6)' : 'var(--border)'}`,
                          color: active ? '#93c5fd' : 'var(--text-secondary)', fontWeight: active ? 700 : 400 }}>
                        {m.label}
                      </button>
                    );
                  })}
                </div>
                {ac.mode_desc && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 7 }}>{ac.mode_desc}</div>}
                {ac.levers && (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.6 }}>
                    Réglages : {ac.levers.max_tools} outils/message · transcription {ac.levers.whisper} · apprentissage {ac.levers.learn === 'dedicated' ? 'dédié' : 'économe'} · docs {ac.levers.doc}
                    <br />
                    Vidéo locale {ac.levers.video_gen ? <span style={{ color: '#34d399' }}>activée ✓</span> : <span>désactivée</span>} · tâches de fond {ac.levers.bg_scale <= 0.6 ? 'réactives' : ac.levers.bg_scale >= 2 ? 'espacées' : 'normales'} · parallélisme ×{ac.levers.concurrency}
                    {ac.levers.web_depth != null && <><br />Recherche web {ac.levers.web_depth} page(s) · RAG {ac.levers.rag_k} extraits · OCR {ac.levers.ocr_max_pages} pages · mémoire {ac.levers.history_depth} messages</>}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Journal d'activité de Marvin (audit / transparence) */}
        <div style={{ marginBottom: 18 }}>
          <button onClick={() => setShowAudit(s => !s)}
            style={{ padding: '8px 14px', borderRadius: 10, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>
            🔎 Activité de Marvin {showAudit ? '▲' : '▼'}
          </button>
          {showAudit && (
            <div style={{ marginTop: 10, padding: '14px 16px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 12 }}>
              {audit?.stats && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>{audit.stats.total} action(s) · {audit.stats.errors} erreur(s) · sources : {Object.entries(audit.stats.by_source || {}).map(([k, v]) => `${SRC[k] || k} ${v}`).join('  ')}</div>}
              {(!audit?.actions || audit.actions.length === 0)
                ? <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Aucune action enregistrée pour l'instant.</div>
                : <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 280, overflowY: 'auto' }}>
                    {audit.actions.map((a, i) => (
                      <div key={i} style={{ fontSize: 12, display: 'flex', gap: 8, alignItems: 'baseline' }}>
                        <span title={a.source}>{SRC[a.source] || '•'}</span>
                        <span style={{ color: a.ok === false ? '#f87171' : a.ok === null ? '#eab308' : '#34d399' }}>{a.ok === false ? '✗' : a.ok === null ? '⏳' : '✓'}</span>
                        <strong style={{ color: 'var(--text-secondary)' }}>{a.tool}</strong>
                        <span style={{ color: 'var(--text-muted)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.message || a.error || ''}</span>
                        <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{(a.ts || '').slice(11, 16)}</span>
                      </div>
                    ))}
                  </div>}
            </div>
          )}
        </div>

        {/* Briefing IA */}
        <div style={{ padding: '20px 24px', background: 'rgba(79, 140, 255,0.06)', border: '1px solid rgba(79, 140, 255,0.25)', borderRadius: 16, marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#4f8cff', marginBottom: 10 }}>✨ Votre briefing</div>
          {loading
            ? <div style={{ color: 'var(--text-muted)', fontSize: 14 }}>⏳ Marvin analyse vos emails et vos tâches…</div>
            : data?.error
              ? <div style={{ color: '#f87171', fontSize: 13 }}>⚠️ {data.error}</div>
              : <pre style={{ fontFamily: 'inherit', fontSize: 14, lineHeight: 1.75, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', margin: 0, wordBreak: 'break-word' }}>{data?.briefing}</pre>}
        </div>

        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          {/* Tâches */}
          <div style={{ flex: 1, minWidth: 300 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <h3 style={{ margin: 0, fontSize: '1rem' }}>✅ Tâches en attente</h3>
              <a href="/tasks" style={{ fontSize: 12, color: '#4f8cff', textDecoration: 'none' }}>Tout voir →</a>
            </div>
            {tasks.length === 0
              ? <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Aucune tâche en attente. 🎉</div>
              : tasks.map(t => (
                <div key={t.id} style={{ padding: '9px 12px', marginBottom: 6, background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: 10 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{t.title}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                    <span style={{ color: (PRIO[t.priority] || PRIO.medium).c }}>{(PRIO[t.priority] || PRIO.medium).l}</span>
                    {t.due_date ? ` · échéance ${t.due_date}` : ''}
                  </div>
                </div>
              ))}
          </div>

          {/* Alertes importantes */}
          <div style={{ flex: 1, minWidth: 300 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <h3 style={{ margin: 0, fontSize: '1rem' }}>🔔 Mails importants</h3>
              <a href="/emails" style={{ fontSize: 12, color: '#60a5fa', textDecoration: 'none' }}>Ouvrir →</a>
            </div>
            {alerts.length === 0
              ? <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Aucune alerte. Activez la 🔔 Surveillance dans Emails.</div>
              : alerts.slice(0, 8).map((al, i) => (
                <div key={i} style={{ padding: '9px 12px', marginBottom: 6, background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 10 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{al.subject || '(sans objet)'}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{al.from}</div>
                </div>
              ))}
          </div>
        </div>
      </div>
    </div>
  );
}
