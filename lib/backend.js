/**
 * Point d'entrée unique vers le backend FastAPI.
 *
 * Dans le navigateur, on conserve l'hôte réellement utilisé pour ouvrir Marvin
 * afin que l'accès LAN/mobile continue de fonctionner. Côté serveur Next.js, la
 * variable d'environnement reste prioritaire avec un repli IPv4 local fiable.
 */
export function getBackendUrl() {
  if (typeof window !== 'undefined' && window.location) {
    return `${window.location.protocol}//${window.location.hostname}:8005`;
  }
  return process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8005';
}

export const BACKEND_URL = getBackendUrl();

function readCookie(name) {
  if (typeof document === 'undefined') return '';
  const prefix = `${encodeURIComponent(name)}=`;
  for (const item of document.cookie.split(';')) {
    const value = item.trim();
    if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
  }
  return '';
}

// Frontend et FastAPI utilisent deux ports mais le même hôte. Ce pont conserve
// le cookie HttpOnly LAN hors du JavaScript et ajoute uniquement le jeton CSRF
// lisible aux mutations dirigées vers le backend Marvin.
if (typeof window !== 'undefined' && !window.__marvinBackendFetchInstalled) {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    let target;
    try {
      const raw = typeof input === 'string' || input instanceof URL ? input : input.url;
      target = new URL(raw, window.location.href);
    } catch {
      return nativeFetch(input, init);
    }
    if (
      target.hostname !== window.location.hostname
      || target.port !== '8005'
      || !target.pathname.startsWith('/api/')
    ) {
      return nativeFetch(input, init);
    }
    const method = String(init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const headers = new Headers(input instanceof Request ? input.headers : undefined);
    new Headers(init.headers || {}).forEach((value, key) => headers.set(key, value));
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const csrf = readCookie('marvin_csrf');
      if (csrf) headers.set('X-Marvin-CSRF', csrf);
    }
    return nativeFetch(input, {
      ...init,
      headers,
      credentials: 'include',
    });
  };
  window.__marvinBackendFetchInstalled = true;
}
