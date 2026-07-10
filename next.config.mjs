import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Autoriser better-sqlite3 (module natif Node.js) côté serveur
  serverExternalPackages: ['better-sqlite3'],

  // Épingle la racine du projet : évite le warning "multiple lockfiles" si un
  // package-lock.json traîne ailleurs (ex. dans C:\Users\<toi>\).
  turbopack: { root: __dirname },

  // Configuration des en-têtes pour la sécurité
  async headers() {
    return [
      {
        source: '/api/:path*',
        headers: [
          { key: 'Access-Control-Allow-Origin', value: '*' },
          { key: 'Access-Control-Allow-Methods', value: 'GET,POST,PATCH,DELETE,OPTIONS' },
          { key: 'Access-Control-Allow-Headers', value: 'Content-Type' },
        ],
      },
    ];
  },
};

export default nextConfig;
