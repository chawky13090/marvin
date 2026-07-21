import { NextResponse } from 'next/server';
import { BACKEND_URL as BACKEND } from '@/lib/backend';

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

// v2.142 — instructions persistantes du projet (équivalent Claude/ChatGPT Projects).
export async function PUT(req, { params }) {
  try {
    const { id } = await params;
    if (!id) return NextResponse.json({ error: 'ID manquant' }, { status: 400 });
    const body = await req.json();
    const r = await fetch(`${BACKEND}/api/projects/${id}`, {
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
