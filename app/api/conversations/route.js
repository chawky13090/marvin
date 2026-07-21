import { NextResponse } from 'next/server';
import { BACKEND_URL as BACKEND } from '@/lib/backend';

// v2.107 — proxy pur vers le backend Python (source de vérité unique pour
// data/secretary.db). Avant : accès SQLite direct côté JS (lib/database/queries.js)
// en parallèle du Python, même fichier — risque de dérive de schéma entre les deux
// implémentations (constaté : la version Python gérait mal la désassignation de
// projet, corrigé côté Python plutôt que de garder deux logiques à maintenir).
export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const r = await fetch(`${BACKEND}/api/conversations`, { signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    const conversations = await r.json();
    return NextResponse.json({ conversations });
  } catch (error) {
    console.error('[Conversations API] Error fetching conversations:', error);
    return NextResponse.json({ error: 'Erreur lors de la récupération des conversations' }, { status: 500 });
  }
}
