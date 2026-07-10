import { NextResponse } from 'next/server';

const BACKEND = (typeof window !== 'undefined' && window.location
  ? window.location.protocol + '//' + window.location.hostname + ':8005'
  : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005'));

export async function DELETE(req, { params }) {
  try {
    const { id } = await params;
    if (!id) return NextResponse.json({ error: 'ID manquant' }, { status: 400 });
    const r = await fetch(`${BACKEND}/api/projects/${id}`, { method: 'DELETE', signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    return NextResponse.json(await r.json());
  } catch (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
