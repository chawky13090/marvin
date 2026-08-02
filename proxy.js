import { NextResponse } from 'next/server';
import { decideLanProxy } from './lib/lanProxyPolicy.mjs';


const INTROSPECTION_URL =
  process.env.MARVIN_BACKEND_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  'http://127.0.0.1:8005';


export async function proxy(request) {
  // Endpoint de compatibilité utilisé par start.bat comme simple sonde.
  if (request.nextUrl.pathname === '/api/status') {
    return NextResponse.next();
  }

  const cookie = request.headers.get('cookie') || '';
  if (!cookie.includes('marvin_session=')) {
    return Response.json(
      { detail: 'lan_authentication_required' },
      { status: 401, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  let response;
  try {
    response = await fetch(`${INTROSPECTION_URL}/api/auth/lan/introspect`, {
      method: 'POST',
      headers: { cookie, 'content-type': 'application/json' },
      body: JSON.stringify({
        path: request.nextUrl.pathname,
        method: request.method,
      }),
      cache: 'no-store',
      signal: AbortSignal.timeout(3000),
    });
  } catch {
    // Échec fermé : une panne du backend ne rend jamais les routes Next publiques.
    return Response.json(
      { detail: 'lan_introspection_unavailable' },
      {
        status: 503,
        headers: { 'Cache-Control': 'no-store', 'Retry-After': '1' },
      },
    );
  }
  if (!response.ok) {
    return Response.json(
      { detail: 'lan_introspection_unavailable' },
      {
        status: 503,
        headers: { 'Cache-Control': 'no-store', 'Retry-After': '1' },
      },
    );
  }
  const result = await response.json();
  const decision = decideLanProxy(result);
  if (decision === 'allow') {
    return NextResponse.next();
  }
  if (decision === 'forbid') {
    return Response.json(
      { detail: 'capability_required' },
      { status: 403, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  return Response.json(
    { detail: 'lan_authentication_required' },
    { status: 401, headers: { 'Cache-Control': 'no-store' } },
  );
}


export const config = {
  matcher: '/api/:path*',
};
