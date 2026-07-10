import { NextResponse } from 'next/server';

// v2.107 — proxy pur vers le backend Python (voir app/api/conversations/route.js).
// L'ancienne implémentation dupliquait ici la reconstruction messages BD → format UI
// (parts/toolInvocations) déjà faite côté Python dans GET /api/conversations/{cid} —
// même logique, deux endroits à maintenir en cohérence. Le backend Python la fait
// déjà correctement (shape identique : {conversation, messages}).
const BACKEND = (typeof window !== 'undefined' && window.location
  ? window.location.protocol + '//' + window.location.hostname + ':8005'
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005'));

export const dynamic = 'force-dynamic';

export async function GET(req, { params }) {
  try {
    const { id } = await params;
    const r = await fetch(`${BACKEND}/api/conversations/${id}`, { signal: AbortSignal.timeout(8000) });
    if (r.status === 404) {
      return NextResponse.json({ error: 'Conversation non trouvée' }, { status: 404 });
    }
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    const data = await r.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('[Conversation ID API] Error fetching conversation:', error);
    return NextResponse.json({ error: 'Erreur lors de la récupération de la conversation' }, { status: 500 });
  }
}

export async function DELETE(req, { params }) {
  try {
    const { id } = await params;
    if (!id) return NextResponse.json({ error: 'ID manquant' }, { status: 400 });
    const r = await fetch(`${BACKEND}/api/conversations/${id}`, { method: 'DELETE', signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    return NextResponse.json(await r.json());
  } catch (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
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
  } catch (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
