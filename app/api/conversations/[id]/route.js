import { NextResponse } from 'next/server';
import { BACKEND_URL as BACKEND } from '@/lib/backend';
import { fetchBackendRead } from '@/lib/backendRead.mjs';

// v2.107 — proxy pur vers le backend Python (voir app/api/conversations/route.js).
// L'ancienne implémentation dupliquait ici la reconstruction messages BD → format UI
// (parts/toolInvocations) déjà faite côté Python dans GET /api/conversations/{cid} —
// même logique, deux endroits à maintenir en cohérence. Le backend Python la fait
// déjà correctement (shape identique : {conversation, messages}).
export const dynamic = 'force-dynamic';

export async function GET(req, { params }) {
  try {
    const { id } = await params;
    const query = new URL(req.url).searchParams;
    const before = query.get('before_rowid');
    const suffix = before && /^\d+$/.test(before) ? `?before_rowid=${before}` : '';
    // Une lecture abandonnée continue dans le thread FastAPI. La rejouer sur un
    // historique lourd multiplierait le travail identique et empirerait la latence.
    const r = await fetchBackendRead(`${BACKEND}/api/conversations/${id}${suffix}`, {
      attempts: 1,
      timeoutMs: 30000,
    });
    if (r.status === 404) {
      return NextResponse.json({ error: 'Conversation non trouvée' }, { status: 404 });
    }
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    const data = await r.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('[Conversation ID API] Backend indisponible:', error?.name || 'Error');
    return NextResponse.json(
      { error: 'Conversation temporairement indisponible' },
      { status: 503, headers: { 'Retry-After': '2' } },
    );
  }
}

export async function DELETE(req, { params }) {
  try {
    const { id } = await params;
    if (!id) return NextResponse.json({ error: 'ID manquant' }, { status: 400 });
    const r = await fetch(`${BACKEND}/api/conversations/${id}`, { method: 'DELETE', signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    return NextResponse.json(await r.json());
  } catch {
    return NextResponse.json({ error: 'Suppression de conversation impossible' }, { status: 500 });
  }
}

export async function PUT(req, { params }) {
  try {
    const { id } = await params;
    if (!id) return NextResponse.json({ error: 'ID manquant' }, { status: 400 });
    const body = await req.json();
    const r = await fetch(`${BACKEND}/api/conversations/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    return NextResponse.json(await r.json());
  } catch {
    return NextResponse.json({ error: 'Modification de conversation impossible' }, { status: 500 });
  }
}
