import { getBackendUrl } from '@/lib/backend';

export const dynamic = 'force-dynamic';

export async function GET(request, { params }) {
  return proxyVMLab(request, params, 'GET');
}

export async function POST(request, { params }) {
  return proxyVMLab(request, params, 'POST');
}

async function proxyVMLab(request, params, method) {
  const resolved = await params;
  const segments = Array.isArray(resolved?.path) ? resolved.path : [];
  if (!segments.length || segments.some(segment => !/^[A-Za-z0-9._-]+$/.test(segment))) {
    return Response.json({ detail: 'Chemin VM Lab API invalide.' }, { status: 400 });
  }
  const source = new URL(request.url);
  const target = `${getBackendUrl()}/api/vm-lab/${segments.map(encodeURIComponent).join('/')}${source.search}`;
  try {
    const response = await fetch(target, {
      method, cache: 'no-store',
      headers: { Accept: 'application/json', ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}) },
      body: method === 'POST' ? await request.text() : undefined,
      signal: AbortSignal.timeout(method === 'POST' ? 180000 : 30000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json; charset=utf-8' },
    });
  } catch (error) {
    return Response.json({ detail: `Backend VM Lab indisponible : ${error instanceof Error ? error.message : 'erreur reseau'}` }, { status: 502 });
  }
}
