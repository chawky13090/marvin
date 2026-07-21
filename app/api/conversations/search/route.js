import { NextResponse } from 'next/server';
import { BACKEND_URL as BACKEND } from '@/lib/backend';

// v2.171 — proxy pur vers le backend Python (voir app/api/conversations/route.js).
// Recherche FULL-TEXT (titre + contenu des messages), demandée explicitement — la
// recherche précédente ne filtrait que côté client sur le titre tronqué à 6 mots.
export const dynamic = 'force-dynamic';

export async function GET(req) {
  try {
    const { searchParams } = new URL(req.url);
    const q = searchParams.get('q') || '';
    if (!q.trim()) return NextResponse.json([]);
    const r = await fetch(`${BACKEND}/api/conversations/search?q=${encodeURIComponent(q)}`, { signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    return NextResponse.json(await r.json());
  } catch (error) {
    console.error('[Conversations Search API] Error:', error);
    return NextResponse.json({ error: 'Erreur lors de la recherche' }, { status: 500 });
  }
}
