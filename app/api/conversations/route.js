import { NextResponse } from 'next/server';
import { BACKEND_URL as BACKEND } from '@/lib/backend';
import { fetchBackendRead } from '@/lib/backendRead.mjs';

// v2.107 — proxy pur vers le backend Python (source de vérité unique pour
// data/secretary.db). Avant : accès SQLite direct côté JS (lib/database/queries.js)
// en parallèle du Python, même fichier — risque de dérive de schéma entre les deux
// implémentations (constaté : la version Python gérait mal la désassignation de
// projet, corrigé côté Python plutôt que de garder deux logiques à maintenir).
export const dynamic = 'force-dynamic';

export async function GET(request) {
  try {
    const search = request?.nextUrl?.searchParams;
    const params = new URLSearchParams();
    for (const key of ['limit', 'offset', 'archived']) {
      const value = search?.get(key);
      if (value !== null && value !== undefined) params.set(key, value);
    }
    const suffix = params.size ? `?${params.toString()}` : '';
    const r = await fetchBackendRead(`${BACKEND}/api/conversations${suffix}`);
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    const conversations = await r.json();
    return NextResponse.json({ conversations });
  } catch (error) {
    console.error('[Conversations API] Backend indisponible:', error?.name || 'Error');
    return NextResponse.json(
      { error: 'Conversations temporairement indisponibles' },
      { status: 503, headers: { 'Retry-After': '2' } },
    );
  }
}
