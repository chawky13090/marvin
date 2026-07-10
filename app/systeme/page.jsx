'use client';

import { Suspense, useState, useEffect, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { SanteView } from '../sante/page';
import { EmporiumView } from '../emporium/page';
import { PantheonView } from '../pantheon/page';
import { CatharsisView } from '../catharsis/page';
import { CodexView } from '../codex/page';

// « PC & Système » — hub unique qui regroupe 5 anciennes pages séparées (Santé,
// Logiciels, Optimisation, Nettoyage, Système) : même sujet ("prendre soin de cette
// machine"), un seul point d'entrée avec des onglets internes au lieu de 5 destinations
// à mémoriser. Les anciennes routes (/sante, /emporium, /pantheon, /catharsis, /codex)
// redirigent ici avec le bon onglet préselectionné → rien n'a disparu, juste regroupé.
const TABS = [
  { id: 'sante',        label: 'Santé',        icon: '🩺', View: SanteView },
  { id: 'logiciels',    label: 'Logiciels',    icon: '📦', View: EmporiumView },
  { id: 'optimisation', label: 'Optimisation', icon: '🚀', View: PantheonView },
  { id: 'nettoyage',    label: 'Nettoyage',    icon: '🧹', View: CatharsisView },
  { id: 'systeme',      label: 'Système',      icon: '🎛️', View: CodexView },
];

function SystemeHub() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initial = TABS.some(t => t.id === searchParams.get('tab')) ? searchParams.get('tab') : 'sante';
  const [active, setActive] = useState(initial);

  useEffect(() => {
    const t = searchParams.get('tab');
    if (t && TABS.some(x => x.id === t) && t !== active) setActive(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const selectTab = useCallback((id) => {
    setActive(id);
    router.replace(`/systeme?tab=${id}`, { scroll: false });
  }, [router]);

  const ActiveView = TABS.find(t => t.id === active)?.View || SanteView;

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)' }}>
      <div className="page-header" style={{ paddingBottom: 0, borderBottom: 'none', flexDirection: 'column', alignItems: 'stretch', gap: 4 }}>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>🖥️ PC &amp; Système</h1>
        <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginBottom: 4 }}>
          Santé, logiciels, optimisation, nettoyage et réglages système — regroupés au même endroit.
        </div>
      </div>

      {/* Barre d'onglets */}
      <div style={{
        display: 'flex', gap: 4, padding: '0 32px', borderBottom: '1px solid var(--border)',
        flexShrink: 0, overflowX: 'auto',
      }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => selectTab(t.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 7,
              padding: '11px 16px', border: 'none', background: 'transparent',
              borderBottom: active === t.id ? '2px solid var(--accent-primary)' : '2px solid transparent',
              color: active === t.id ? 'var(--text-primary)' : 'var(--text-muted)',
              fontWeight: active === t.id ? 700 : 500,
              fontSize: 13.5, cursor: 'pointer', whiteSpace: 'nowrap',
              transition: 'color 0.15s, border-color 0.15s',
            }}
          >
            <span>{t.icon}</span>{t.label}
          </button>
        ))}
      </div>

      {/* Contenu de l'onglet actif */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <ActiveView />
      </div>
    </div>
  );
}

export default function SystemePage() {
  return (
    <Suspense fallback={null}>
      <SystemeHub />
    </Suspense>
  );
}
