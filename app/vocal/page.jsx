'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

// Le mode vocal mains libres est maintenant directement dans la barre de chat
// (bouton 🔊, bandeau « Mode vocal actif » avec voix/vitesse/barge-in dans
// ChatContainer.jsx) — plus besoin d'une page séparée. Cette route redirige les
// anciens liens/favoris vers l'accueil, où toute la fonctionnalité est disponible.
export default function VocalRedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/'); }, [router]);
  return null;
}
