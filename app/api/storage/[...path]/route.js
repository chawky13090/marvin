import { getBackendUrl } from '@/lib/backend';

export const dynamic = 'force-dynamic';

export async function GET(request, { params }) {
  return proxyStorage(request, params, 'GET');
}

export async function POST(request, { params }) {
  return proxyStorage(request, params, 'POST');
}

async function proxyStorage(request, params, method) {
  const resolved = await params;
  const segments = Array.isArray(resolved?.path) ? resolved.path : [];
  if (!segments.length || segments.some(segment => !/^[A-Za-z0-9._-]+$/.test(segment))) {
    return Response.json({ detail: 'Chemin Storage API invalide.' }, { status: 400 });
  }
  const source = new URL(request.url);
  const backendPath = segments.map(encodeURIComponent).join('/');
  const target = `${getBackendUrl()}/api/storage/${backendPath}${source.search}`;
  try {
    const response = await fetch(target, {
      method,
      cache: 'no-store',
      headers: { Accept: 'application/json', ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}) },
      body: method === 'POST' ? await request.text() : undefined,
      signal: AbortSignal.timeout(method === 'POST' ? 60000 : 30000),
    });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json; charset=utf-8' },
    });
  } catch (error) {
    return Response.json(
      { detail: `Backend Storage indisponible : ${error instanceof Error ? error.message : 'erreur reseau'}` },
      { status: 502 },
    );
  }
}
