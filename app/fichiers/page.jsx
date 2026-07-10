'use client';

import { Suspense, useState, useEffect, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { FilesView } from '../files/page';
import { DocumentsView } from '../documents/page';
import { IndexationView } from '../indexation/page';

// « Fichiers » — hub unique qui regroupe 3 anciennes pages qui se recoupaient
// (Fichiers = navigateur brut, Mes documents = questions/réponses sur des PDF/Word
// indexés, Indexation = recherche par contenu sur tout le PC). Même sujet côté
// utilisateur ("mes fichiers"), un seul point d'entrée avec onglets. Les anciennes
// routes (/files, /documents, /indexation) redirigent ici avec le bon onglet.
const TABS = [
  { id: 'parcourir', label: 'Parcourir',  icon: '📁', View: FilesView },
  { id: 'documents', label: 'Documents',  icon: '📄', View: DocumentsView },
  { id: 'indexation',label: 'Recherche PC',icon: '🗂️', View: IndexationView },
];

function FichiersHub() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initial = TABS.some(t => t.id === searchParams.get('tab')) ? searchParams.get('tab') : 'parcourir';
  const [active, setActive] = useState(initial);

  useEffect(() => {
    const t = searchParams.get('tab');
    if (t && TABS.some(x => x.id === t) && t !== active) setActive(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const selectTab = useCallback((id) => {
    setActive(id);
    router.replace(`/fichiers?tab=${id}`, { scroll: false });
  }, [router]);

  const ActiveView = TABS.find(t => t.id === active)?.View || FilesView;

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)' }}>
      {/* Barre d'onglets (le contenu « Parcourir » a déjà son propre page-header) */}
      <div style={{
        display: 'flex', gap: 4, padding: '0 24px', borderBottom: '1px solid var(--border)',
        flexShrink: 0, overflowX: 'auto', background: 'var(--bg-secondary)',
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

      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <ActiveView />
      </div>
    </div>
  );
}

export default function FichiersPage() {
  return (
    <Suspense fallback={null}>
      <FichiersHub />
    </Suspense>
  );
}
