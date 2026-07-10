'use client';
import { useState, useEffect, useCallback } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';

const DAYS_FR   = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
const MONTHS_FR = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'];

const BACKEND = (typeof window!=='undefined'&&window.location?window.location.protocol+'//'+window.location.hostname+':8005':(process.env.NEXT_PUBLIC_BACKEND_URL||'http://127.0.0.1:8005'));
const pad = (n) => String(n).padStart(2, '0');

export default function CalendarPage() {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [events,      setEvents]      = useState([]);
  const [googleMode,  setGoogleMode]  = useState(false);   // Google connecté en plus du local ?
  const [selectedDate, setSelectedDate] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [quickAdd, setQuickAdd] = useState('');
  const [quickBusy, setQuickBusy] = useState(false);
  const [form, setForm] = useState({ title: '', start: '', end: '', description: '', location: '', reminder: '' });
  const [notification, setNotification] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  // Agendas connectés (abonnements iCal)
  const [subs, setSubs] = useState([]);
  const [showSubs, setShowSubs] = useState(false);
  const [subForm, setSubForm] = useState({ name: '', url: '', color: '#10b981' });
  const [subBusy, setSubBusy] = useState(false);
  // Google Agenda complet via compte de service (permanent)
  const [gStatus, setGStatus] = useState(null);
  const [gBusy, setGBusy] = useState(false);
  const [gMsg, setGMsg] = useState('');
  const [calId, setCalId] = useState('');
  const loadGoogleStatus = useCallback(async () => {
    try { const r = await fetch(`${BACKEND}/api/oauth/google/status`).then(r => r.json()); setGStatus(r); if (r.calendar_id) setCalId(r.calendar_id); } catch {}
  }, []);
  useEffect(() => { if (showSubs) loadGoogleStatus(); }, [showSubs, loadGoogleStatus]);
  async function uploadServiceAccount(file) {
    if (!file) return;
    setGBusy(true); setGMsg('⏳ Envoi de la clé…');
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch(`${BACKEND}/api/oauth/google/service-account`, { method: 'POST', body: fd }).then(r => r.json());
      if (r.detail) setGMsg('❌ ' + r.detail);
      else setGMsg(`✅ Clé acceptée. Partage ton agenda avec : ${r.client_email}`);
    } catch { setGMsg('❌ Échec de l\'envoi'); }
    setGBusy(false); loadGoogleStatus();
  }
  async function saveCalendarId() {
    if (!calId.trim()) return;
    setGBusy(true); setGMsg('');
    try {
      await fetch(`${BACKEND}/api/google/calendar-id`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ calendar_id: calId.trim() }) });
      setGMsg('✅ Agenda cible enregistré'); await loadGoogleStatus();
    } catch { setGMsg('❌ Échec'); }
    setGBusy(false);
  }
  async function syncGoogleNow() {
    setGBusy(true); setGMsg('⏳ Synchronisation…');
    try {
      const r = await fetch(`${BACKEND}/api/tools`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ toolName: 'calendar_sync', args: {} }) }).then(r => r.json());
      const res = r.result || {};
      setGMsg(res.error ? '❌ ' + res.error : `✅ ${res.message || 'Agenda synchronisé'}`);
      fetchEvents();
    } catch { setGMsg('❌ Échec de la synchro'); }
    setGBusy(false);
  }

  const year  = currentDate.getFullYear();
  const month = currentDate.getMonth();

  const notify = (msg, type = 'success') => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 3500);
  };

  // Normalise un événement backend (local OU agenda connecté) → format de la grille
  const normLocal = (e) => ({
    id: e.id,
    title: e.title,
    start: (e.start_at || '').replace(' ', 'T'),
    end: e.end_at ? e.end_at.replace(' ', 'T') : null,
    location: e.location || '',
    description: e.description || '',
    allDay: !!e.all_day,
    reminderMinutes: e.reminder_minutes,
    color: e.color || (e.source && e.source !== 'local' ? '#10b981' : '#4f8cff'),
    source: e.source || 'local',
    external: !!(e.source && e.source !== 'local'),   // agenda connecté (lecture seule)
  });

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    const startStr = `${year}-${pad(month + 1)}-01 00:00`;
    const endStr   = `${year}-${pad(month + 1)}-${pad(new Date(year, month + 1, 0).getDate())} 23:59`;
    let merged = [];
    // 1) Agenda local (source de vérité)
    try {
      const res = await fetch(`${BACKEND}/api/events?start=${encodeURIComponent(startStr)}&end=${encodeURIComponent(endStr)}`);
      const data = await res.json();
      merged = (data.events || []).map(normLocal);
    } catch {
      notify('⚠️ Backend injoignable — agenda local indisponible', 'error');
    }
    // 2) Google Calendar (lecture seule, fusion si connecté)
    try {
      const gres = await fetch(`/api/calendar?start=${new Date(year, month, 1).toISOString()}&end=${new Date(year, month + 1, 0, 23, 59, 59).toISOString()}`);
      const gdata = await gres.json();
      if (gdata.mode === 'google' && Array.isArray(gdata.events)) {
        setGoogleMode(true);
        merged = merged.concat(gdata.events.map(e => ({ ...e, source: 'google', color: e.color || '#34a853' })));
      } else {
        setGoogleMode(false);
      }
    } catch {
      setGoogleMode(false);
    }
    setEvents(merged);
    setLoading(false);
  }, [year, month]);

  useEffect(() => { fetchEvents(); }, [fetchEvents]);

  // ── Agendas connectés ────────────────────────────────────────────────────────
  const loadSubs = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND}/api/calendar/subscriptions`).then(r => r.json());
      setSubs(r.subscriptions || []);
    } catch { /* backend off */ }
  }, []);
  useEffect(() => { loadSubs(); }, [loadSubs]);

  async function addSubscription(e) {
    e.preventDefault();
    if (!subForm.url.trim()) return;
    setSubBusy(true);
    try {
      const res = await fetch(`${BACKEND}/api/calendar/subscriptions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(subForm),
      });
      const data = await res.json();
      if (data.success) {
        notify(`📅 ${data.message || 'Agenda connecté'}`);
        setSubForm({ name: '', url: '', color: '#10b981' });
        await loadSubs(); fetchEvents();
      } else {
        notify('❌ ' + (data.detail || data.error || 'Échec'), 'error');
      }
    } catch { notify('❌ Backend injoignable', 'error'); }
    setSubBusy(false);
  }

  async function removeSubscription(id) {
    setSubBusy(true);
    try {
      await fetch(`${BACKEND}/api/calendar/subscriptions/${id}`, { method: 'DELETE' });
      notify('🗑️ Agenda déconnecté');
      await loadSubs(); fetchEvents();
    } catch { notify('❌ Échec', 'error'); }
    setSubBusy(false);
  }

  async function syncSubscriptions() {
    setSubBusy(true);
    try {
      const r = await fetch(`${BACKEND}/api/calendar/subscriptions/sync`, { method: 'POST' }).then(r => r.json());
      notify(`🔄 ${r.message || 'Synchronisé'}`);
      await loadSubs(); fetchEvents();
    } catch { notify('❌ Échec de synchro', 'error'); }
    setSubBusy(false);
  }

  function prevMonth() { setCurrentDate(new Date(year, month - 1, 1)); }
  function nextMonth() { setCurrentDate(new Date(year, month + 1, 1)); }
  function goToday()  { setCurrentDate(new Date()); setSelectedDate(new Date().getDate()); }

  const firstDay    = new Date(year, month, 1);
  const lastDay     = new Date(year, month + 1, 0);
  const startOffset = (firstDay.getDay() + 6) % 7;
  const totalDays   = lastDay.getDate();

  const days = [];
  for (let i = 0; i < startOffset; i++) days.push(null);
  for (let i = 1; i <= totalDays; i++) days.push(i);

  const today    = new Date();
  const isToday  = (d) => d === today.getDate() && month === today.getMonth() && year === today.getFullYear();

  function getEventsForDay(day) {
    if (!day) return [];
    const dateStr = new Date(year, month, day).toDateString();
    return events.filter(e => { const dt = new Date(e.start); return !isNaN(dt) && dt.toDateString() === dateStr; });
  }

  const selectedEvents = selectedDate ? getEventsForDay(selectedDate) : [];

  // ── Ajout rapide en langage naturel ────────────────────────────────────────
  async function handleQuickAdd(e) {
    e.preventDefault();
    if (!quickAdd.trim()) return;
    setQuickBusy(true);
    try {
      const res = await fetch(`${BACKEND}/api/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ natural: quickAdd.trim() }),
      });
      const data = await res.json();
      if (data.success) {
        notify(`📅 ${data.message || 'Événement créé'}`);
        setQuickAdd('');
        const d = new Date((data.event?.start_at || '').replace(' ', 'T'));
        if (!isNaN(d)) { setCurrentDate(new Date(d.getFullYear(), d.getMonth(), 1)); setSelectedDate(d.getDate()); }
        fetchEvents();
      } else {
        notify('❌ ' + (data.detail || data.error || 'Date non comprise'), 'error');
      }
    } catch {
      notify('❌ Backend injoignable', 'error');
    }
    setQuickBusy(false);
  }

  // ── Création structurée ─────────────────────────────────────────────────────
  function openCreate() {
    const base = selectedDate ? new Date(year, month, selectedDate) : new Date();
    const local = `${base.getFullYear()}-${pad(base.getMonth()+1)}-${pad(base.getDate())}T09:00`;
    setForm({ title: '', start: local, end: '', description: '', location: '', reminder: '' });
    setShowCreate(true);
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!form.title.trim() || !form.start) return;
    setCreating(true);
    try {
      const res  = await fetch(`${BACKEND}/api/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title:       form.title,
          start_at:    form.start,
          end_at:      form.end || '',
          description: form.description,
          location:    form.location,
          reminder_minutes: form.reminder ? Number(form.reminder) : null,
        }),
      });
      const data = await res.json();
      if (data.success) {
        notify('✅ Événement créé dans votre agenda');
        setShowCreate(false);
        fetchEvents();
      } else {
        notify('❌ Erreur : ' + (data.detail || data.error || 'inconnue'), 'error');
      }
    } catch {
      notify('❌ Impossible de créer l\'événement', 'error');
    }
    setCreating(false);
  }

  // ── Suppression ──────────────────────────────────────────────────────────────
  async function handleDelete(evt) {
    setConfirmDelete(null);
    setDeleting(evt.id);
    try {
      let ok = false;
      if (evt.source === 'google') {
        const res = await fetch('/api/calendar', {
          method: 'DELETE', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ eventId: evt.id }),
        });
        ok = (await res.json()).success;
      } else {
        const res = await fetch(`${BACKEND}/api/events/${evt.id}`, { method: 'DELETE' });
        ok = (await res.json()).success;
      }
      if (ok) { notify('🗑️ Événement supprimé'); fetchEvents(); }
      else notify('❌ Suppression impossible', 'error');
    } catch {
      notify('❌ Impossible de supprimer l\'événement', 'error');
    }
    setDeleting(null);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', position: 'relative' }}>

      {notification && (
        <div style={{
          position: 'fixed', top: 24, right: 24, zIndex: 1000,
          padding: '12px 20px', borderRadius: 'var(--radius-md)',
          background: notification.type === 'error' ? 'var(--bg-danger, #d93025)' : 'var(--bg-success, #1e7e34)',
          color: '#fff', fontWeight: 600, fontSize: 'var(--font-sm)',
          boxShadow: '0 4px 24px rgba(0,0,0,0.3)', animation: 'slideUp 0.3s ease',
        }}>{notification.msg}</div>
      )}

      {/* Header */}
      <div className="page-header">
        <h1>📅 Agenda</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{
            fontSize: 'var(--font-xs)', fontWeight: 600, padding: '3px 10px', borderRadius: 'var(--radius-sm)',
            background: 'rgba(79, 140, 255,0.13)', color: '#4f8cff', border: '1px solid rgba(79, 140, 255,0.3)',
          }}>Local{subs.length ? ` + ${subs.length} connecté${subs.length > 1 ? 's' : ''}` : ''}{googleMode ? ' + Google' : ''}</span>
          <button className="btn btn-ghost" onClick={() => setShowSubs(true)} title="Connecter Google, Outlook, Apple… via iCal">
            🔗 Agendas connectés{subs.length ? ` (${subs.length})` : ''}
          </button>
          <button className="btn btn-ghost" onClick={goToday}>Aujourd&apos;hui</button>
          <button className="btn btn-primary" onClick={openCreate}>+ Créer</button>
        </div>
      </div>

      {/* Barre d'ajout rapide en langage naturel */}
      <form onSubmit={handleQuickAdd} style={{ display: 'flex', gap: 8, padding: '12px 24px', borderBottom: '1px solid var(--border)' }}>
        <input
          className="input"
          style={{ flex: 1 }}
          placeholder="✨ Ajout rapide : « rdv dentiste mardi 14h », « réunion équipe demain 10h-11h »…"
          value={quickAdd}
          onChange={e => setQuickAdd(e.target.value)}
        />
        <button type="submit" className="btn btn-primary" disabled={quickBusy || !quickAdd.trim()}>
          {quickBusy ? '⏳ Analyse…' : '➕ Ajouter'}
        </button>
      </form>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* Grille calendrier */}
        <div style={{ flex: 1, padding: '24px', overflow: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
            <button className="btn btn-ghost" onClick={prevMonth}>◀ Précédent</button>
            <h2 style={{
              fontSize: 'var(--font-xl)', fontWeight: 700,
              background: 'var(--accent-gradient)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            }}>{MONTHS_FR[month]} {year}</h2>
            <button className="btn btn-ghost" onClick={nextMonth}>Suivant ▶</button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '4px', marginBottom: '8px' }}>
            {DAYS_FR.map(d => (
              <div key={d} style={{ textAlign: 'center', padding: '8px', fontSize: 'var(--font-sm)', fontWeight: 600, color: 'var(--text-secondary)' }}>{d}</div>
            ))}
          </div>

          {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '60px' }}><LoadingRow /></div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '4px' }}>
              {days.map((day, idx) => {
                const dayEvents = getEventsForDay(day);
                const isTodayDay = isToday(day);
                const isSelected = day === selectedDate;
                return (
                  <div key={idx} onClick={() => day && setSelectedDate(day)}
                    style={{
                      minHeight: '80px', padding: '8px', borderRadius: 'var(--radius-md)',
                      background: isSelected ? 'var(--bg-glass-active)' : isTodayDay ? 'var(--bg-glass)' : 'transparent',
                      border: isTodayDay ? '1px solid var(--accent-primary)' : '1px solid var(--border)',
                      cursor: day ? 'pointer' : 'default', transition: 'all 0.15s ease', position: 'relative',
                    }}
                    onMouseEnter={e => { if (day) e.currentTarget.style.background = 'var(--bg-glass-hover)'; }}
                    onMouseLeave={e => { if (day) e.currentTarget.style.background = isSelected ? 'var(--bg-glass-active)' : isTodayDay ? 'var(--bg-glass)' : 'transparent'; }}
                  >
                    {day && (
                      <>
                        <span style={{ fontSize: 'var(--font-sm)', fontWeight: isTodayDay ? 700 : 400, color: isTodayDay ? 'var(--accent-primary)' : 'var(--text-primary)' }}>{day}</span>
                        <div style={{ marginTop: '4px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                          {dayEvents.slice(0, 2).map((evt, i) => (
                            <div key={evt.id || i} style={{
                              fontSize: '10px', padding: '2px 6px', borderRadius: '4px',
                              background: `${evt.color || '#4f8cff'}30`, color: evt.color || '#4f8cff',
                              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontWeight: 500,
                            }}>{evt.allDay ? '🗓 ' : ''}{evt.reminderMinutes ? '🔔 ' : ''}{evt.title}</div>
                          ))}
                          {dayEvents.length > 2 && (
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>+{dayEvents.length - 2} de plus</span>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Panel latéral */}
        <div style={{ width: '320px', borderLeft: '1px solid var(--border)', padding: '20px', overflowY: 'auto', background: 'var(--bg-secondary)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h3 style={{ fontSize: 'var(--font-md)', fontWeight: 700 }}>
              {selectedDate ? new Date(year, month, selectedDate).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' }) : 'Sélectionnez une date'}
            </h3>
            {selectedDate && (
              <button className="btn btn-ghost" style={{ fontSize: '11px', padding: '4px 8px' }} onClick={openCreate} title="Créer un événement ce jour">+ Ajouter</button>
            )}
          </div>

          {selectedDate && selectedEvents.length === 0 && (
            <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--font-sm)' }}>Aucun événement</p>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {selectedEvents.map((evt, i) => (
              <div key={evt.id || i} className="card" style={{ borderLeft: `3px solid ${evt.color || '#4f8cff'}`, animation: `slideUp 0.3s ease ${i * 0.1}s both`, position: 'relative' }}>
                {evt.external ? (
                  <span title="Agenda connecté (lecture seule)" style={{ position: 'absolute', top: '8px', right: '8px', fontSize: '11px', opacity: 0.6 }}>🔗</span>
                ) : (
                  <button onClick={() => setConfirmDelete(evt)} disabled={deleting === evt.id} title="Supprimer cet événement"
                    style={{ position: 'absolute', top: '8px', right: '8px', background: 'transparent', border: 'none', cursor: 'pointer', fontSize: '14px', opacity: 0.4, padding: '2px 4px', borderRadius: '4px', transition: 'opacity 0.15s' }}
                    onMouseEnter={e => e.currentTarget.style.opacity = '1'} onMouseLeave={e => e.currentTarget.style.opacity = '0.4'}
                  >{deleting === evt.id ? '⏳' : '🗑️'}</button>
                )}

                <div style={{ fontWeight: 600, fontSize: 'var(--font-sm)', marginBottom: '6px', paddingRight: '28px' }}>
                  {evt.allDay ? '🗓 ' : ''}{evt.title}
                  {evt.source === 'google' && <span style={{ fontSize: '9px', color: '#34a853', marginLeft: 6 }}>Google</span>}
                </div>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  {evt.allDay ? <span>🗓 Toute la journée</span> : (
                    <span>🕐 {new Date(evt.start).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
                      {evt.end && ` — ${new Date(evt.end).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`}</span>
                  )}
                  {evt.reminderMinutes ? <span>🔔 Rappel {evt.reminderMinutes} min avant</span> : null}
                  {evt.location    && <span>📍 {evt.location}</span>}
                  {evt.description && <span style={{ marginTop: '4px', whiteSpace: 'pre-wrap' }}>{evt.description}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Modal confirmation suppression */}
      {confirmDelete && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 300, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setConfirmDelete(null)}>
          <div className="card" style={{ width: '380px', padding: '28px', animation: 'slideUp 0.2s ease', textAlign: 'center' }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: '40px', marginBottom: '12px' }}>🗑️</div>
            <h3 style={{ fontSize: 'var(--font-lg)', fontWeight: 700, marginBottom: '10px' }}>Supprimer cet événement ?</h3>
            <p style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', marginBottom: '20px' }}>
              <strong>{confirmDelete.title}</strong><br />Cette action est irréversible.
            </p>
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
              <button className="btn btn-ghost" onClick={() => setConfirmDelete(null)}>Annuler</button>
              <button className="btn btn-danger" onClick={() => handleDelete(confirmDelete)} style={{ background: 'var(--bg-danger, #d93025)', color: '#fff', border: 'none' }}>🗑️ Supprimer</button>
            </div>
          </div>
        </div>
      )}

      {/* Modal création structurée */}
      {showCreate && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowCreate(false)}>
          <div className="card" style={{ width: '460px', padding: '28px', animation: 'slideUp 0.25s ease' }} onClick={e => e.stopPropagation()}>
            <h3 style={{ fontSize: 'var(--font-lg)', fontWeight: 700, marginBottom: '20px' }}>📅 Créer un événement</h3>
            <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Titre *</label>
                <input className="input" style={{ width: '100%' }} placeholder="Réunion d'équipe…" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} required autoFocus />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div>
                  <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Début *</label>
                  <input type="datetime-local" className="input" style={{ width: '100%' }} value={form.start} onChange={e => setForm(f => ({ ...f, start: e.target.value }))} required />
                </div>
                <div>
                  <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Fin</label>
                  <input type="datetime-local" className="input" style={{ width: '100%' }} value={form.end} onChange={e => setForm(f => ({ ...f, end: e.target.value }))} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div>
                  <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Lieu</label>
                  <input className="input" style={{ width: '100%' }} placeholder="Paris, en ligne…" value={form.location} onChange={e => setForm(f => ({ ...f, location: e.target.value }))} />
                </div>
                <div>
                  <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>🔔 Rappel (min avant)</label>
                  <select className="input" style={{ width: '100%' }} value={form.reminder} onChange={e => setForm(f => ({ ...f, reminder: e.target.value }))}>
                    <option value="">Aucun</option>
                    <option value="10">10 minutes</option>
                    <option value="30">30 minutes</option>
                    <option value="60">1 heure</option>
                    <option value="1440">1 jour</option>
                  </select>
                </div>
              </div>
              <div>
                <label style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Description</label>
                <textarea className="input" style={{ width: '100%', height: '70px', resize: 'vertical' }} placeholder="Notes, ordre du jour…" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
              </div>
              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '4px' }}>
                <button type="button" className="btn btn-ghost" onClick={() => setShowCreate(false)}>Annuler</button>
                <button type="submit" className="btn btn-primary" disabled={creating}>{creating ? 'Création…' : '✅ Créer'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal agendas connectés (iCal) */}
      {showSubs && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 250, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowSubs(false)}>
          <div className="card" style={{ width: '560px', maxHeight: '86vh', overflowY: 'auto', padding: '26px', animation: 'slideUp 0.25s ease' }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <h3 style={{ fontSize: 'var(--font-lg)', fontWeight: 700, margin: 0 }}>🔗 Agendas connectés</h3>
              {subs.length > 0 && (
                <button className="btn btn-ghost" style={{ fontSize: 12, padding: '4px 10px' }} disabled={subBusy} onClick={syncSubscriptions}>
                  {subBusy ? '⏳' : '🔄'} Synchroniser
                </button>
              )}
            </div>
            <p style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', marginBottom: 16, lineHeight: 1.6 }}>
              Connecte Google, Outlook, Apple… via leur lien <strong>iCal</strong>. Marvin voit alors tous tes événements (lecture seule) dans l'agenda et le briefing.<br />
              <span style={{ color: 'var(--text-muted)' }}>Google : Paramètres de l'agenda → « Intégrer l'agenda » → <em>Adresse secrète au format iCal</em>. Outlook : Paramètres → Calendrier → Calendriers partagés → Publier → ICS.</span>
            </p>

            {/* Liste */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 18 }}>
              {subs.length === 0 && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Aucun agenda connecté pour l'instant.</div>}
              {subs.map(s => (
                <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: 10 }}>
                  <span style={{ width: 12, height: 12, borderRadius: '50%', background: s.color || '#10b981', flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{s.name || 'Agenda'}</div>
                    <div style={{ fontSize: 11, color: s.last_error ? '#f87171' : 'var(--text-muted)' }}>
                      {s.last_error ? `⚠️ ${s.last_error}` : `${s.count ?? 0} événements · synchro ${s.last_sync || '—'}`}
                    </div>
                  </div>
                  <button onClick={() => removeSubscription(s.id)} disabled={subBusy} title="Déconnecter"
                    style={{ background: 'transparent', border: '1px solid rgba(239,68,68,0.4)', color: '#f87171', borderRadius: 8, padding: '4px 10px', fontSize: 12, cursor: 'pointer' }}>
                    Déconnecter
                  </button>
                </div>
              ))}
            </div>

            {/* Ajout */}
            <form onSubmit={addSubscription} style={{ display: 'flex', flexDirection: 'column', gap: 10, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#4f8cff' }}>➕ Ajouter un agenda</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <input className="input" style={{ flex: 1 }} placeholder="Nom (ex : Perso, Boulot)" value={subForm.name} onChange={e => setSubForm(f => ({ ...f, name: e.target.value }))} />
                <input type="color" value={subForm.color} onChange={e => setSubForm(f => ({ ...f, color: e.target.value }))} title="Couleur" style={{ width: 44, height: 38, border: '1px solid var(--border)', borderRadius: 8, background: 'transparent', cursor: 'pointer' }} />
              </div>
              <input className="input" style={{ width: '100%' }} placeholder="Lien iCal : https://…/basic.ics  (ou webcal://…)" value={subForm.url} onChange={e => setSubForm(f => ({ ...f, url: e.target.value }))} required />
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button type="button" className="btn btn-ghost" onClick={() => setShowSubs(false)}>Fermer</button>
                <button type="submit" className="btn btn-primary" disabled={subBusy || !subForm.url.trim()}>
                  {subBusy ? 'Connexion…' : '🔗 Connecter'}
                </button>
              </div>
            </form>

            {/* Google Agenda COMPLET via compte de service (permanent, lecture + écriture) */}
            <div style={{ marginTop: 16, padding: '14px 16px', background: 'rgba(96,165,250,0.07)', border: '1px solid rgba(96,165,250,0.25)', borderRadius: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: '#60a5fa' }}>🗓️ Google Agenda complet (créer / modifier)</span>
                {gStatus?.connected && <span style={{ fontSize: 11, color: '#34d399', fontWeight: 700 }}>✓ connecté ({gStatus.email})</span>}
                {gStatus && !gStatus.connected && <span style={{ fontSize: 11, color: '#f59e0b' }}>non connecté</span>}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: 10 }}>
                Méthode <strong>permanente</strong> (sans expiration) via un <strong>compte de service</strong> Google. 3 étapes :
              </div>
              <ol style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.7, margin: 0, paddingLeft: 18 }}>
                <li>Console Google → compte de service → <strong>Clés</strong> → Ajouter une clé → <strong>JSON</strong> → télécharge.
                  <div style={{ marginTop: 4 }}>
                    <label className="btn btn-ghost" style={{ fontSize: 12, padding: '5px 12px', cursor: 'pointer', display: 'inline-block' }}>
                      📎 Importer la clé JSON
                      <input type="file" accept=".json,application/json" style={{ display: 'none' }} disabled={gBusy} onChange={e => uploadServiceAccount(e.target.files?.[0])} />
                    </label>
                    {gStatus?.sa_email && <span style={{ fontSize: 11, color: '#34d399', marginLeft: 8 }}>✓ clé : {gStatus.sa_email}</span>}
                  </div>
                </li>
                <li style={{ marginTop: 8 }}>Dans <strong>Google Agenda</strong> → Paramètres → ton agenda → « Partager avec des personnes » → ajoute
                  {gStatus?.sa_email
                    ? <code style={{ background: 'rgba(255,255,255,0.08)', padding: '1px 5px', borderRadius: 4, margin: '0 4px' }}>{gStatus.sa_email}</code>
                    : ' l\'email du compte de service '}
                  avec le droit <strong>« Apporter des modifications aux événements »</strong>.</li>
                <li style={{ marginTop: 8 }}>Indique ton agenda (ton adresse email) :
                  <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                    <input className="input" style={{ flex: 1, fontSize: 12 }} placeholder="ton.email@gmail.com" value={calId} onChange={e => setCalId(e.target.value)} />
                    <button className="btn btn-primary" style={{ fontSize: 12 }} disabled={gBusy || !calId.trim()} onClick={saveCalendarId}>Valider</button>
                  </div>
                </li>
              </ol>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
                <button className="btn btn-ghost" style={{ fontSize: 12 }} disabled={gBusy} onClick={syncGoogleNow}>🔄 Synchroniser maintenant</button>
                {gMsg && <span style={{ fontSize: 11, color: gMsg.startsWith('✅') || gMsg.startsWith('⏳') ? '#34d399' : '#f87171' }}>{gMsg}</span>}
              </div>
              {gStatus?.error && <div style={{ fontSize: 11, color: '#f59e0b', marginTop: 6 }}>⚠️ {gStatus.error}</div>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
