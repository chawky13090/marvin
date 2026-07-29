'use client';

import { Command, Menu } from 'lucide-react';
import { useChatStatus } from '@/lib/contexts/ChatContext';
import { useNavigationLayout } from '@/lib/contexts/NavigationContext';

const ROUTE_LABELS = Object.freeze({
  '/': 'Conversation',
  '/agents': 'Agents',
  '/calendar': 'Agenda',
  '/code': 'Code Workspace',
  '/documents': 'Documents',
  '/emails': 'E-mails',
  '/evolution': 'Evolution Lab',
  '/files': 'Fichiers',
  '/forge': 'Forge',
  '/historique': 'Historique',
  '/market': 'Model Market',
  '/missions': 'Mission Canvas',
  '/recherche': 'Recherche',
  '/settings': 'Réglages',
  '/skills': 'Compétences',
  '/vocal': 'Mode vocal',
  '/workflows': 'Workflows',
});

function resolveRouteLabel(pathname) {
  if (ROUTE_LABELS[pathname]) return ROUTE_LABELS[pathname];
  const prefix = Object.keys(ROUTE_LABELS)
    .filter((route) => route !== '/' && pathname.startsWith(`${route}/`))
    .sort((left, right) => right.length - left.length)[0];
  if (prefix) return ROUTE_LABELS[prefix];

  const segment = pathname.split('/').filter(Boolean)[0];
  if (!segment) return ROUTE_LABELS['/'];
  return segment
    .replaceAll('-', ' ')
    .replace(/(^|\s)\p{L}/gu, (letter) => letter.toLocaleUpperCase('fr-FR'));
}

export default function ContextBar() {
  const navigation = useNavigationLayout();
  const chatStatus = useChatStatus();
  const label = resolveRouteLabel(navigation.pathname);

  return (
    <header className="context-bar" aria-label="Contexte de travail">
      <div className="context-bar__primary">
        <button
          type="button"
          className="context-bar__button"
          onClick={navigation.openOverlay}
          aria-label="Ouvrir la navigation Marvin"
          title="Navigation"
        >
          <Menu size={18} aria-hidden="true" />
        </button>
        <div className="context-bar__identity">
          <strong>Marvin</strong>
          <span aria-hidden="true">/</span>
          <span>{label}</span>
        </div>
      </div>

      <div className="context-bar__secondary">
        <span
          className={`context-bar__status${chatStatus.isLoading ? ' context-bar__status--active' : ''}`}
          role="status"
          aria-live="polite"
        >
          <span className="context-bar__status-dot" aria-hidden="true" />
          {chatStatus.isLoading ? 'Travail en cours' : 'Prêt'}
        </span>
        <button
          type="button"
          className="context-bar__command"
          onClick={() => window.dispatchEvent(new CustomEvent('marvin:open-command-palette'))}
          aria-label="Ouvrir la palette de commandes"
          title="Palette de commandes (Ctrl+K)"
        >
          <Command size={15} aria-hidden="true" />
          <kbd>Ctrl K</kbd>
        </button>
      </div>
    </header>
  );
}
