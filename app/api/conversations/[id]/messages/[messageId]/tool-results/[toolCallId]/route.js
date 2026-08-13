import { NextResponse } from 'next/server';
import { BACKEND_URL as BACKEND } from '@/lib/backend';

export const dynamic = 'force-dynamic';

export async function GET(req, { params }) {
  const { id, messageId, toolCallId } = await params;
  const values = [id, messageId, toolCallId];
  if (values.some((value) => !value || !/^[A-Za-z0-9._:-]{1,160}$/.test(value))) {
    return NextResponse.json({ error: 'Référence de résultat invalide' }, { status: 400 });
  }
  try {
    const path = `/api/conversations/${encodeURIComponent(id)}/messages/${encodeURIComponent(messageId)}/tool-results/${encodeURIComponent(toolCallId)}`;
    const response = await fetch(`${BACKEND}${path}`, {
      signal: AbortSignal.timeout(12000),
      cache: 'no-store',
      headers: { cookie: req.headers.get('cookie') || '' },
    });
    if (response.status === 404) {
      return NextResponse.json({ error: 'Résultat détaillé introuvable' }, { status: 404 });
    }
    if (!response.ok) throw new Error(`Backend ${response.status}`);
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json(
      { error: 'Résultat détaillé temporairement indisponible' },
      { status: 503, headers: { 'Retry-After': '2' } },
    );
  }
}
