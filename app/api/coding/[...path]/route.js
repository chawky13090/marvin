import { getBackendUrl } from '@/lib/backend';

export const dynamic = 'force-dynamic';

export async function GET(request, { params }) {
  return proxyCoding(request, params, 'GET');
}

export async function POST(request, { params }) {
  return proxyCoding(request, params, 'POST');
}

async function proxyCoding(request, params, method) {
  const resolved = await params;
  const segments = Array.isArray(resolved?.path) ? resolved.path : [];
  if (!segments.length || segments.some(segment => !/^[A-Za-z0-9._-]+$/.test(segment))) {
    return Response.json({ detail: 'Chemin Coding API invalide.' }, { status: 400 });
  }
  const source = new URL(request.url);
  const backendPath = segments.map(encodeURIComponent).join('/');
  const target = `${getBackendUrl()}/api/coding/${backendPath}${source.search}`;
  const isEventStream = method === 'GET' && backendPath.endsWith('/events/stream');
  try {
    const response = await fetch(target, {
      method,
      cache: 'no-store',
      headers: { Accept: isEventStream ? 'text/event-stream' : 'application/json', ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}) },
      body: method === 'POST' ? await request.text() : undefined,
      signal: isEventStream ? undefined : AbortSignal.timeout(method === 'POST' ? 60000 : 30000),
    });
    if (isEventStream && response.ok) {
      return new Response(response.body, {
        status: response.status,
        headers: {
          'Content-Type': 'text/event-stream; charset=utf-8',
          'Cache-Control': 'no-cache, no-transform',
          'X-Accel-Buffering': 'no',
        },
      });
    }
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json; charset=utf-8' },
    });
  } catch (error) {
    return Response.json(
      { detail: `Backend Coding indisponible : ${error instanceof Error ? error.message : 'erreur réseau'}` },
      { status: 502 },
    );
  }
}
