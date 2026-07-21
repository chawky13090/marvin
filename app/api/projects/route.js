import { NextResponse } from 'next/server';
import { BACKEND_URL as BACKEND } from '@/lib/backend';

// v2.107 — proxy pur vers le backend Python (voir app/api/conversations/route.js).
// Python n'avait qu'une fonction de lecture (get_projects) ; create_project/delete_project
// + les endpoints POST/DELETE ont été ajoutés côté Python pour permettre ce proxy.
export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const r = await fetch(`${BACKEND}/api/projects`, { signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    return NextResponse.json(await r.json());
  } catch (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function POST(req) {
  try {
    const { name } = await req.json();
    if (!name || name.trim() === '') {
      return NextResponse.json({ error: 'Le nom du projet est requis' }, { status: 400 });
    }
    const r = await fetch(`${BACKEND}/api/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim() }),
      signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    return NextResponse.json(await r.json());
  } catch (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
