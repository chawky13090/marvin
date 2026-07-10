'use client';

import { useChatStatus } from '@/lib/contexts/ChatContext';

/**
 * Barre de progression globale (façon YouTube/GitHub) : visible en haut de
 * l'écran, sur N'IMPORTE QUELLE page, tant que Marvin traite une demande de
 * chat en arrière-plan. Sert de signal permanent "Marvin travaille", même si
 * l'utilisateur a navigué vers une autre page pendant que la réponse arrive.
 */
export default function TopLoadingBar() {
  const { isLoading } = useChatStatus();
  if (!isLoading) return null;
  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, height: '2.5px',
      zIndex: 10000, overflow: 'hidden', background: 'transparent', pointerEvents: 'none',
    }}>
      <div style={{
        position: 'absolute', top: 0, bottom: 0, width: '40%',
        background: 'linear-gradient(90deg, transparent, var(--accent-primary), var(--accent-secondary), transparent)',
        animation: 'topLoadingSweep 1.1s ease-in-out infinite',
        boxShadow: '0 0 8px var(--accent-primary)',
      }} />
    </div>
  );
}
