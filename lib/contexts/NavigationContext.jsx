'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import {
  normalizeNavigationMode,
  resolveNavigationMode,
  routePreferenceKey,
} from '@/lib/navigationLayout.mjs';

const GLOBAL_MODE_KEY = 'marvin:navigation-mode:v1';
const ROUTE_MODES_KEY = 'marvin:navigation-route-modes:v1';
const NavigationContext = createContext(null);

function readRouteModes() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(ROUTE_MODES_KEY) || '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .filter(([key]) => /^\/(?:[a-z0-9_-]{1,64})?$/.test(key))
        .slice(0, 64)
        .map(([key, value]) => [key, normalizeNavigationMode(value)]),
    );
  } catch {
    return {};
  }
}

export function NavigationProvider({ children }) {
  const pathname = usePathname();
  const [hydrated, setHydrated] = useState(false);
  const [preference, setPreferenceState] = useState('auto');
  const [routeModes, setRouteModes] = useState({});
  const [compact, setCompact] = useState(false);
  const [overlayOpen, setOverlayOpen] = useState(false);

  useEffect(() => {
    try {
      setPreferenceState(normalizeNavigationMode(window.localStorage.getItem(GLOBAL_MODE_KEY)));
      setRouteModes(readRouteModes());
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    const query = window.matchMedia('(max-width: 1024px), (hover: none) and (pointer: coarse)');
    const apply = () => setCompact(query.matches);
    apply();
    query.addEventListener('change', apply);
    return () => query.removeEventListener('change', apply);
  }, []);

  useEffect(() => setOverlayOpen(false), [pathname]);

  const routeKey = routePreferenceKey(pathname);
  const routePreference = normalizeNavigationMode(routeModes[routeKey]);
  const mode = resolveNavigationMode({ pathname, preference, routePreference, compact });

  const setMode = useCallback((nextMode, scope = 'global') => {
    const normalized = normalizeNavigationMode(nextMode);
    if (scope === 'route') {
      setRouteModes(current => {
        const next = { ...current };
        if (normalized === 'auto') delete next[routePreferenceKey(window.location.pathname)];
        else next[routePreferenceKey(window.location.pathname)] = normalized;
        try { window.localStorage.setItem(ROUTE_MODES_KEY, JSON.stringify(next)); } catch {}
        return next;
      });
    } else {
      setPreferenceState(normalized);
      try { window.localStorage.setItem(GLOBAL_MODE_KEY, normalized); } catch {}
    }
    setOverlayOpen(false);
  }, []);

  useEffect(() => {
    const onMode = event => setMode(event.detail?.mode, event.detail?.scope || 'global');
    const onOpen = () => setOverlayOpen(true);
    const onKeyDown = event => {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'b') {
        event.preventDefault();
        setMode(mode === 'focus' ? 'auto' : 'focus');
      }
    };
    window.addEventListener('marvin:set-navigation-mode', onMode);
    window.addEventListener('marvin:open-navigation', onOpen);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('marvin:set-navigation-mode', onMode);
      window.removeEventListener('marvin:open-navigation', onOpen);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [mode, setMode]);

  const value = useMemo(() => ({
    compact,
    hydrated,
    mode,
    overlayOpen,
    pathname,
    preference,
    routePreference,
    closeOverlay: () => setOverlayOpen(false),
    openOverlay: () => setOverlayOpen(true),
    setMode,
    toggleOverlay: () => setOverlayOpen(current => !current),
  }), [compact, hydrated, mode, overlayOpen, pathname, preference, routePreference, setMode]);

  return <NavigationContext.Provider value={value}>{children}</NavigationContext.Provider>;
}

export function useNavigationLayout() {
  const value = useContext(NavigationContext);
  if (!value) throw new Error('useNavigationLayout doit être utilisé dans NavigationProvider');
  return value;
}
