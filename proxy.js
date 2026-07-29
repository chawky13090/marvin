import { NextResponse } from 'next/server';


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

  try {
    const response = await fetch(`${INTROSPECTION_URL}/api/auth/lan/introspect`, {
      method: 'POST',
      headers: { cookie },
      cache: 'no-store',
      signal: AbortSignal.timeout(3000),
    });
    const result = response.ok ? await response.json() : null;
    if (result?.authenticated === true) {
      return NextResponse.next();
    }
  } catch {
    // Échec fermé : une panne du backend ne rend jamais les routes Next publiques.
  }
  return Response.json(
    { detail: 'lan_authentication_required' },
    { status: 401, headers: { 'Cache-Control': 'no-store' } },
  );
}


export const config = {
  matcher: '/api/:path*',
};
