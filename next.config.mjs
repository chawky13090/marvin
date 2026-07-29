import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { networkInterfaces } from 'node:os';

const __dirname = dirname(fileURLToPath(import.meta.url));
const allowedDevOrigins = new Set(['127.0.0.1', 'localhost']);
for (const addresses of Object.values(networkInterfaces())) {
  for (const address of addresses || []) {
    if (address.family === 'IPv4' && !address.internal) {
      allowedDevOrigins.add(address.address);
    }
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Épingle la racine du projet : évite le warning "multiple lockfiles" si un
  // package-lock.json traîne ailleurs (ex. dans C:\Users\<toi>\).
  turbopack: { root: __dirname },

  // L'avatar de bureau Electron charge http://127.0.0.1:3000 (pas localhost). Sans cette
  // entrée, le serveur de dev bloque le websocket HMR comme "cross-origin" → la page ne finit
  // jamais son hydratation et boucle en rechargement complet (aucun bouton ne répond).
  allowedDevOrigins: [...allowedDevOrigins],

};

export default nextConfig;
