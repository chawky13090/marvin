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

