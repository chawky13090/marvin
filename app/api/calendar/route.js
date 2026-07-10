// API REST pour le calendrier
// Proxifie vers le backend Python (Google Calendar via OAuth) avec fallback démo.
import * as demo from '@/lib/services/demo';

const BACKEND = (typeof window!=='undefined'&&window.location?window.location.protocol+'//'+window.location.hostname+':8005':(process.env.NEXT_PUBLIC_BACKEND_URL||'http://127.0.0.1:8005'));

/**
 * Appelle un outil backend et retourne le result, ou null si erreur.
 */
async function callTool(toolName, args = {}) {
  try {
    const res = await fetch(`${BACKEND}/api/tools`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ toolName, args }),
      // timeout via signal
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    if (data?.result?.error) return null;
    return data?.result ?? null;
  } catch {
    return null;
  }
}

/**
 * Convertit un événement Google Calendar en format attendu par le frontend.
 * start : { date } ou { dateTime }
 */
function normalizeGoogleEvent(evt) {
  const startRaw = evt.start?.dateTime || evt.start?.date || '';
  const endRaw   = evt.end?.dateTime   || evt.end?.date   || '';
  return {
    id:          evt.id || String(Math.random()),
    title:       evt.summary || '(Sans titre)',
    start:       startRaw,
    end:         endRaw,
    description: evt.description || '',
    location:    evt.location    || '',
    color:       evt.colorId ? GOOGLE_COLORS[evt.colorId] : undefined,
    allDay:      !evt.start?.dateTime,
  };
}

// Palette des 11 couleurs Google Calendar
const GOOGLE_COLORS = {
  '1': '#7986cb', '2': '#33b679', '3': '#8e24aa', '4': '#e67c73',
  '5': '#f6bf26', '6': '#f4511e', '7': '#039be5', '8': '#616161',
  '9': '#3f51b5', '10': '#0b8043', '11': '#d50000',
};

// ── GET /api/calendar?start=...&end=... ───────────────────────────────────────
export async function GET(req) {
  const { searchParams } = new URL(req.url);
  const startDate = searchParams.get('start');
  const endDate   = searchParams.get('end');
  const checkDate = searchParams.get('check');

  // Mode check disponibilité — délègue au démo (pas de support Google Calendar natif)
  if (checkDate) {
    try {
      const availability = demo.checkDemoAvailability(checkDate);
      return Response.json({ success: true, ...availability });
    } catch (error) {
      return Response.json({ error: error.message }, { status: 500 });
    }
  }

  // Calculer le nombre de jours entre start et end
  let days = 31;
  if (startDate && endDate) {
    const ms = new Date(endDate) - new Date(startDate);
    days = Math.max(1, Math.min(90, Math.round(ms / 86400000) + 1));
  }

  // Tenter Google Calendar via le backend
  const gcResult = await callTool('calendar_list', {
    days,
    max_results: 50,
    time_min: startDate || undefined,
  });

  if (gcResult && Array.isArray(gcResult.events)) {
    // Filtrer par plage si fournie
    let events = gcResult.events.map(normalizeGoogleEvent);
    if (startDate && endDate) {
      const from = new Date(startDate).getTime();
      const to   = new Date(endDate).getTime();
      events = events.filter(e => {
        const t = new Date(e.start).getTime();
        return t >= from && t <= to;
      });
    }
    return Response.json({ success: true, events, mode: 'google' });
  }

  // Fallback démo
  try {
    const events = demo.getDemoEvents(startDate, endDate);
    return Response.json({ success: true, events, mode: 'demo' });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}

// ── POST /api/calendar ────────────────────────────────────────────────────────
export async function POST(req) {
  try {
    const body = await req.json();
    const { title, startDate, endDate, description, location } = body;

    // Tenter création via Google Calendar
    if (title && startDate) {
      const gcResult = await callTool('calendar_create', {
        title,
        start:       startDate,
        end:         endDate || undefined,
        description: description || '',
        location:    location   || '',
      });
      if (gcResult && !gcResult.error) {
        const event = normalizeGoogleEvent(gcResult);
        return Response.json({ success: true, event, mode: 'google' });
      }
    }

    // Fallback démo
    const result = await demo.createDemoEvent(title, startDate, endDate, description, location);
    return Response.json({ ...result, mode: 'demo' });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}

// ── PATCH /api/calendar ───────────────────────────────────────────────────────
export async function PATCH(req) {
  try {
    const { eventId, ...updates } = await req.json();

    // Tenter mise à jour via Google Calendar
    if (eventId) {
      const gcResult = await callTool('calendar_update', {
        event_id:    eventId,
        title:       updates.title       || undefined,
        start:       updates.startDate   || undefined,
        end:         updates.endDate     || undefined,
        description: updates.description || undefined,
        location:    updates.location    || undefined,
      });
      if (gcResult && gcResult.success) {
        const event = normalizeGoogleEvent(gcResult);
        return Response.json({ success: true, event, mode: 'google' });
      }
    }

    // Fallback démo
    const result = await demo.updateDemoEvent(eventId, updates);
    return Response.json({ ...result, mode: 'demo' });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}

// ── DELETE /api/calendar ──────────────────────────────────────────────────────
export async function DELETE(req) {
  try {
    const { eventId } = await req.json();

    // Tenter suppression via Google Calendar (confirmed=true depuis le frontend)
    if (eventId) {
      const gcResult = await callTool('calendar_delete', {
        event_id:  eventId,
        confirmed: true,
      });
      if (gcResult && gcResult.success) {
        return Response.json({ success: true, mode: 'google' });
      }
      if (gcResult && gcResult.error) {
        return Response.json({ error: gcResult.error }, { status: 400 });
      }
    }

    // Fallback démo
    const result = await demo.deleteDemoEvent(eventId);
    return Response.json({ ...result, mode: 'demo' });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}
