'use client';

import { useEffect, useRef, useState } from 'react';
import { Menu, PanelLeft, PanelLeftClose, Rows3, Sparkles } from 'lucide-react';
import { useNavigationLayout } from '@/lib/contexts/NavigationContext';

const OPTIONS = [
  { mode: 'auto', label: 'Automatique', detail: 'Marvin adapte la disposition', icon: Sparkles },
  { mode: 'focus', label: 'Focus', detail: 'Contenu maximal', icon: PanelLeftClose },
  { mode: 'rail', label: 'Rail', detail: 'Raccourcis essentiels', icon: Rows3 },
  { mode: 'full', label: 'Complet', detail: 'Toutes les sections', icon: PanelLeft },
  { mode: 'classic', label: 'Classique', detail: 'Ancienne sidebar', icon: Menu },
];

export default function NavigationModeControl({ embedded = false }) {
  const { mode, openOverlay, preference, routePreference, setMode } = useNavigationLayout();
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState('global');
  const rootRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = event => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const escape = event => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={`navigation-mode-control navigation-mode-control--${mode}${embedded ? ' navigation-mode-control--embedded' : ''}`}>
      <button
        type="button"
        className="navigation-mode-trigger"
        aria-label="Changer la disposition de navigation"
        aria-expanded={open}
        onClick={() => setOpen(current => !current)}
        title="Disposition de navigation"
      >
        <Menu size={18} aria-hidden="true" />
        <span className="navigation-mode-trigger__label">{mode === 'focus' ? 'Navigation' : mode}</span>
      </button>
      {open && (
        <div className="navigation-mode-popover" role="dialog" aria-label="Disposition de navigation">
          <div className="navigation-mode-popover__header">
            <strong>Disposition</strong>
            <span>Ctrl+Maj+B bascule le mode Focus</span>
          </div>
          <button
            type="button"
            className="navigation-mode-open-full"
            onClick={() => {
              openOverlay();
              setOpen(false);
            }}
          >
            <PanelLeft size={16} aria-hidden="true" />
            Ouvrir toute la navigation
          </button>
          <div className="navigation-mode-scope" role="group" aria-label="Portée du réglage">
            <button type="button" aria-pressed={scope === 'global'} onClick={() => setScope('global')}>
              Partout
            </button>
            <button type="button" aria-pressed={scope === 'route'} onClick={() => setScope('route')}>
              Cette section
            </button>
          </div>
          <div className="navigation-mode-options">
            {OPTIONS.map(option => {
              const Icon = option.icon;
              const selected = scope === 'route'
                ? routePreference === option.mode
                : preference === option.mode;
              return (
                <button
                  type="button"
                  key={option.mode}
                  aria-pressed={selected}
                  onClick={() => {
                    setMode(option.mode, scope);
                    setOpen(false);
                  }}
                >
                  <Icon size={17} aria-hidden="true" />
                  <span><strong>{option.label}</strong><small>{option.detail}</small></span>
                  {selected && <span aria-hidden="true">✓</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
