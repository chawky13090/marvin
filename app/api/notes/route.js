import { NextResponse } from 'next/server';
import { BACKEND_URL as BACKEND } from '@/lib/backend';

// v2.107 — proxy pur vers le backend Python (voir app/api/conversations/route.js pour le
// contexte : même fichier data/secretary.db lu/écrit en double par lib/database/queries.js
// et par Python). L'interface externe (POST {action, ...}) est conservée à l'identique pour
// ne pas toucher app/notes/page.jsx — seule l'implémentation change.
export async function GET(req) {
  const { searchParams } = new URL(req.url);
  const search = searchParams.get('q');
  try {
    const url = new URL(`${BACKEND}/api/notes`);
    if (search) url.searchParams.set('search', search);
    const r = await fetch(url, { signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    const notes = await r.json();
    return NextResponse.json({ notes, count: notes.length });
  } catch (e) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}

export async function POST(req) {
  const body = await req.json();
  const { action, ...data } = body;
  try {
    if (action === 'create') {
      const r = await fetch(`${BACKEND}/api/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: data.title, content: data.content || '', tags: data.tags || [] }),
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      const note = await r.json();
      return NextResponse.json({ success: true, note });
    }
    if (action === 'update') {
      const { id, ...updates } = data;
      const r = await fetch(`${BACKEND}/api/notes/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      const note = await r.json();
      return NextResponse.json({ success: true, note });
    }
    if (action === 'delete') {
      const id = encodeURIComponent(String(data.id || ''));
      const r = await fetch(`${BACKEND}/api/notes/${id}?confirmed=true`, { method: 'DELETE', signal: AbortSignal.timeout(8000) });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      return NextResponse.json(await r.json());
    }
    if (action === 'get') {
      // Pas d'endpoint Python dédié à une note unique — filtre côté liste (action non
      // utilisée par le frontend actuel, gardée pour compatibilité d'API).
      const r = await fetch(`${BACKEND}/api/notes`, { signal: AbortSignal.timeout(8000) });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      const notes = await r.json();
      const note = notes.find((n) => n.id === data.id) || null;
      return NextResponse.json({ note });
    }
    return NextResponse.json({ error: 'Action inconnue' }, { status: 400 });
  } catch (e) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
