'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Moon, Shield, Sparkles, Sun, Zap } from 'lucide-react';

const STORAGE_KEY = 'marvin_theme';
const THEME_COLORS = Object.freeze({
  dark: '#0a0a0d',
  light: '#f4f6fb',
  manga: '#fff8fc',
  medieval: '#17130d',
  cyberpunk: '#070713',
});
const THEMES = Object.freeze([
  { id: 'dark', label: 'Sombre', icon: Moon },
  { id: 'light', label: 'Clair', icon: Sun },
  { id: 'manga', label: 'Manga', icon: Sparkles },
  { id: 'medieval', label: 'Médiéval', icon: Shield },
  { id: 'cyberpunk', label: 'Cyberpunk', icon: Zap },
]);

function normalizeTheme(value) {
  return THEMES.some((theme) => theme.id === value) ? value : 'dark';
}

function applyTheme(theme) {
  const safeTheme = normalizeTheme(theme);
  document.documentElement.dataset.theme = safeTheme;
  document.documentElement.style.colorScheme = safeTheme === 'dark' || safeTheme === 'cyberpunk' ? 'dark' : 'light';
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[safeTheme]);
  return safeTheme;
}

export default function ThemeControl() {
  const [theme, setTheme] = useState('dark');
  const [open, setOpen] = useState(false);
  const shellRef = useRef(null);

  useEffect(() => {
    setTheme(applyTheme(localStorage.getItem(STORAGE_KEY)));
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (!shellRef.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  const current = THEMES.find((item) => item.id === theme) || THEMES[0];
  const CurrentIcon = current.icon;

  const select = (nextTheme) => {
    const safeTheme = applyTheme(nextTheme);
    localStorage.setItem(STORAGE_KEY, safeTheme);
    setTheme(safeTheme);
    setOpen(false);
  };

  return (
    <div className="theme-control" ref={shellRef}>
      <button
        type="button"
        className="theme-control__trigger"
        aria-label={`Thème visuel : ${current.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={`Thème : ${current.label}`}
        onClick={() => setOpen((value) => !value)}
      >
        <CurrentIcon size={14} aria-hidden="true" />
        <span>{current.label}</span>
        <ChevronDown size={12} aria-hidden="true" />
      </button>
      {open && (
        <div className="theme-control__menu" role="menu" aria-label="Choisir le thème visuel">
          {THEMES.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                role="menuitemradio"
                aria-checked={item.id === theme}
                className="theme-control__option"
                onClick={() => select(item.id)}
              >
                <Icon size={15} aria-hidden="true" />
                <span>{item.label}</span>
                {item.id === theme && <Check size={14} aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
