'use client';

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { NAV_SECTIONS } from '@/components/sidebar/Sidebar';
import { BACKEND_URL as BACKEND } from '@/lib/backend';

// Actions rapides, en plus de la navigation (pas des pages, des raccourcis d'action)
const QUICK_ACTIONS = [
  { id: 'new-conv', icon: '➕', label: 'Nouvelle conversation', href: '/?new=1' },
];

function buildIndex() {
  const navItems = NAV_SECTIONS.flatMap(s => s.items.map(i => ({ ...i, section: s.title })));
  return [...QUICK_ACTIONS.map(a => ({ ...a, section: 'Actions' })), ...navItems];
}

/**
 * Palette de commandes (Ctrl+K / Cmd+K) — saut rapide vers n'importe quelle
 * destination de la sidebar sans la parcourir à la souris. Standard des outils
 * pro (Linear, Raycast, VS Code, GitHub).
 */
export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [tools, setTools] = useState(null);   // chargé à la demande (294 outils, pas au montage)
  const inputRef = useRef(null);
  const router = useRouter();
  const items = useMemo(() => buildIndex(), []);

  // Charge le catalogue d'outils UNE fois, à la première ouverture — pas de coût
  // au chargement de chaque page, seulement quand l'utilisateur ouvre Ctrl+K.
  useEffect(() => {
    if (!open || tools !== null) return;
    fetch(`${BACKEND}/api/tools/list`)
      .then(r => r.json())
      .then(d => {
        const list = (d.tools || []).map(t => ({
          id: `tool:${t.function.name}`,
          icon: '🔧',
          label: t.function.name,
          description: t.function.description,
          section: 'Outil',
          isTool: true,
        }));
        setTools(list);
      })
      .catch(() => setTools([]));
  }, [open, tools]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;   // requête vide : uniquement pages/actions (pas les 294 outils)
    const navMatches = items.filter(i =>
      i.label.toLowerCase().includes(q) || i.section.toLowerCase().includes(q)
    );
    const toolMatches = (tools || []).filter(t =>
      t.label.toLowerCase().includes(q) || t.description?.toLowerCase().includes(q)
    ).slice(0, 20);   // plafond pour ne pas noyer les résultats de pages
    return [...navMatches, ...toolMatches];
  }, [items, tools, query]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery('');
    setActive(0);
  }, []);

  const startNewConversation = useCallback(() => {
    // "/" est une page client persistante (ChatProvider) : si on y est déjà,
    // router.push('/') ne fait rien → on passe par un événement que la page écoute.
    if (window.location.pathname === '/') {
      window.dispatchEvent(new Event('marvin:new-conversation'));
    } else {
      router.push('/');
    }
  }, [router]);

  const go = useCallback((item) => {
    if (!item) return;
    if (item.id === 'new-conv') startNewConversation();
    else if (item.isTool) router.push(`/outils?q=${encodeURIComponent(item.label)}`);
    else router.push(item.href);
    close();
  }, [router, close, startNewConversation]);

  // Ouverture globale : Ctrl+K / Cmd+K, Ctrl+N (nouvelle conversation), depuis n'importe quelle page
  useEffect(() => {
    const onKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen(o => !o);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n' && !open) {
        e.preventDefault();
        startNewConversation();
      } else if (e.key === 'Escape' && open) {
        close();
      }
    };
    // Permet aussi l'ouverture par clic (ex: bouton dans la sidebar)
    const onCustomOpen = () => setOpen(true);
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('marvin:open-command-palette', onCustomOpen);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('marvin:open-command-palette', onCustomOpen);
    };
  }, [open, close, startNewConversation]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 10);
  }, [open]);

  useEffect(() => { setActive(0); }, [query]);

  if (!open) return null;

  return (
    <div
      onClick={close}
      style={{
        position: 'fixed', inset: 0, zIndex: 20000,
        background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        paddingTop: '14vh',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(560px, 92vw)', background: 'var(--bg-secondary)',
          border: '1px solid var(--border-hover)', borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-lg)', overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
          <span style={{ color: 'var(--text-muted)', fontSize: 15 }}>⌘</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Aller à… (page, outil, action)"
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, results.length - 1)); }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)); }
              else if (e.key === 'Enter') { e.preventDefault(); go(results[active]); }
            }}
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              color: 'var(--text-primary)', fontSize: 14,
            }}
          />
          <kbd style={{ fontSize: 10, color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 6px' }}>Échap</kbd>
        </div>

        <div style={{ maxHeight: '55vh', overflowY: 'auto', padding: 6 }}>
          {results.length === 0 ? (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              Aucun résultat pour « {query} ».
            </div>
          ) : results.map((item, i) => (
            <div
              key={item.href || item.id}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(item)}
              style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '9px 12px', borderRadius: 'var(--radius-md)', cursor: 'pointer',
                background: active === i ? 'rgba(79, 140, 255,0.12)' : 'transparent',
              }}
            >
              <span style={{ fontSize: 16, width: 22, textAlign: 'center', flexShrink: 0 }}>{item.icon}</span>
              <span style={{ flex: 1, fontSize: 13.5, color: active === i ? 'var(--text-primary)' : 'var(--text-secondary)' }}>{item.label}</span>
              <span style={{ fontSize: 10.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{item.section}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
