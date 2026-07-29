'use client';
import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useChatStatus } from '@/lib/contexts/ChatContext';
import LivingAvatar from '@/components/avatar/LivingAvatar';
import NavigationModeControl from '@/components/layout/NavigationModeControl';
import { BACKEND_URL } from '@/lib/backend';
import {
  Activity,
  BookMarked,
  BookOpen,
  Bot,
  Brain,
  CalendarDays,
  Clapperboard,
  Clock3,
  Code2,
  FlaskConical,
  FolderOpen,
  Hammer,
  ListChecks,
  Mail,
  MessageSquare,
  MoreHorizontal,
  MonitorCog,
  NotebookPen,
  PanelsTopLeft,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Plug,
  Puzzle,
  ReceiptText,
  Search,
  Settings,
  Smartphone,
  Store,
  Sun,
  Terminal,
  Workflow,
  Wrench,
  X,
} from 'lucide-react';

export const NAV_SECTIONS = [
  { title: 'Assistant', items: [
    { href: '/',           icon: MessageSquare, label: 'Chat' },
    { href: '/jour',       icon: Sun, label: 'Mon jour' },
    { href: '/recherche',  icon: Search, label: 'Recherche' },
  ]},
  { title: 'PC & Système', items: [
    { href: '/outils',     icon: Wrench, label: 'Outils' },
    { href: '/systeme',    icon: MonitorCog, label: 'PC & Système' },
    { href: '/ssh',        icon: Terminal, label: 'SSH' },
    { href: '/monitoring', icon: Activity, label: 'Monitoring' },
  ]},
  { title: 'Organisation', items: [
    { href: '/tasks',      icon: ListChecks, label: 'Tâches' },
    { href: '/notes',      icon: NotebookPen, label: 'Notes' },
    { href: '/emails',     icon: Mail, label: 'Emails' },
    { href: '/calendar',   icon: CalendarDays, label: 'Calendrier' },
    { href: '/devis',      icon: ReceiptText, label: 'Devis & Factu' },
    { href: '/fichiers',   icon: FolderOpen, label: 'Fichiers' },
  ]},
  { title: 'IA & Contenu', items: [
    { href: '/skills',     icon: Puzzle, label: 'Compétences' },
    { href: '/redaction',  icon: PenLine, label: 'Rédaction IA' },
    { href: '/video',      icon: Clapperboard, label: 'Vidéo IA' },
    { href: '/docs',       icon: BookOpen, label: 'Doc Tech IA' },
    { href: '/memoire',    icon: Brain, label: 'Mémoire' },
  ]},
  { title: 'Automatisation', items: [
    { href: '/code',       icon: Code2, label: 'Code Workspace' },
    { href: '/workflows',  icon: Workflow, label: 'Workflows' },
    { href: '/agents',     icon: Bot, label: 'Multi-Agents' },
    { href: '/market',     icon: Store, label: 'Model Market' },
    { href: '/evolution',  icon: FlaskConical, label: 'Evolution Lab' },
    { href: '/missions',   icon: PanelsTopLeft, label: 'Mission Canvas' },
    { href: '/forge',      icon: Hammer, label: 'Forge' },
    { href: '/cron',       icon: Clock3, label: 'Planificateur' },
  ]},
  { title: 'Réglages', items: [
    { href: '/technique',  icon: BookMarked, label: 'Guide Technique' },
    { href: '/mobile',     icon: Smartphone, label: 'Accès mobile' },
    { href: '/mcp',        icon: Plug, label: 'MCP' },
    { href: '/settings',   icon: Settings, label: 'Paramètres' },
  ]},
];
const NAV_ITEMS = NAV_SECTIONS.flatMap(s => s.items);
const CORE_NAV_HREFS = new Set(['/', '/recherche', '/code', '/fichiers', '/missions']);
const OLLAMA_PORT = process.env.NEXT_PUBLIC_OLLAMA_PORT || '11434';

export default function Sidebar({ displayMode = 'classic', onRequestClose, onRequestFull }) {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [ollamaStatus, setOllamaStatus] = useState('checking');
  const [isMobile, setIsMobile] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [avatarStatus, setAvatarStatus] = useState('checking');
  const previousPathRef = useRef(pathname);
  // v2.146 — indicateur ambiant de tâche(s) longue(s) en cours (long_task_start, v2.145) :
  // demandé explicitement (« que l'on sache que Marvin travaille d'une certaine manière »).
  // Jusqu'ici totalement invisible tant qu'on ne demandait pas explicitement long_task_status
  // — une tâche pouvait tourner en arrière-plan (reprise cron) sans AUCUN signal ambiant.
  const [longTaskCount, setLongTaskCount] = useState(0);
  const chatStatus = useChatStatus();   // { isLoading, status, conversationId, messageCount }

  useEffect(() => {
    try { setPinned(window.localStorage.getItem('marvin:nav-pinned') === '1'); } catch {}
  }, []);

  const togglePinned = () => {
    setPinned((current) => {
      const next = !current;
      try { window.localStorage.setItem('marvin:nav-pinned', next ? '1' : '0'); } catch {}
      return next;
    });
  };

  // Détecte le mobile/tactile (tiroir au lieu du survol) — couvre aussi le « mode bureau »
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1024px), (hover: none) and (pointer: coarse)');
    const apply = () => setIsMobile(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  // Ferme le tiroir quand on change de page (mobile)
  useEffect(() => { setMobileOpen(false); }, [pathname]);
  useEffect(() => {
    if (previousPathRef.current !== pathname && displayMode === 'overlay') onRequestClose?.();
    previousPathRef.current = pathname;
  }, [displayMode, onRequestClose, pathname]);

  useEffect(() => {
    checkOllama();
    const interval = setInterval(checkOllama, 30000);
    return () => clearInterval(interval);
  }, []);

  async function checkOllama() {
    try {
      // Même hôte que la page (marche aussi depuis le téléphone si Ollama est exposé)
      const host = (typeof window !== 'undefined' && window.location) ? window.location.hostname : '127.0.0.1';
      const res = await fetch(`http://${host}:${OLLAMA_PORT}/api/tags`, { signal: AbortSignal.timeout(8000) });
      setOllamaStatus(res.ok ? 'connected' : 'disconnected');
    } catch {
      setOllamaStatus('disconnected');
    }
  }

  useEffect(() => {
    checkLongTasks();
    const interval = setInterval(checkLongTasks, 30000);
    return () => clearInterval(interval);
  }, []);

  async function checkLongTasks() {
    try {
      // Compte directement les jobs cron de reprise (_long_task_resume) — pas besoin de
      // passer par l'exécution d'outil, /api/cron est un endpoint REST simple.
      const res = await fetch(`${BACKEND_URL}/api/cron`, { signal: AbortSignal.timeout(8000) });
      if (!res.ok) return;
      const jobs = await res.json();
      const count = Array.isArray(jobs) ? jobs.filter(j => j.tool_name === '_long_task_resume' && j.enabled).length : 0;
      setLongTaskCount(count);
    } catch {
      // silencieux — l'indicateur reste simplement à son dernier état connu
    }
  }

  useEffect(() => {
    checkAvatar();
    const interval = setInterval(checkAvatar, 30000);
    return () => clearInterval(interval);
  }, []);

  async function checkAvatar() {
    try {
      const response = await fetch(`${BACKEND_URL}/api/avatar/status`, { signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      setAvatarStatus(data.running ? 'running' : data.available ? 'available' : 'unavailable');
    } catch { setAvatarStatus('unavailable'); }
  }

  async function activateAvatar() {
    setAvatarStatus('starting');
    try {
      const response = await fetch(`${BACKEND_URL}/api/avatar/activate`, { method: 'POST', signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error(String(response.status));
      setAvatarStatus('running');
    } catch { setAvatarStatus('unavailable'); }
  }

  // Sur mobile : barre déployée (240px) en tiroir, masquée hors écran sauf si ouverte.
  const open = isMobile ? mobileOpen : (expanded || pinned);

  if (displayMode !== 'classic') {
    const expandedAdaptive = displayMode === 'full' || displayMode === 'overlay';
    const adaptiveSections = expandedAdaptive
      ? NAV_SECTIONS
      : [{
          title: 'Essentiel',
          items: NAV_ITEMS.filter(item => CORE_NAV_HREFS.has(item.href)),
        }];
    return (
      <>
        {displayMode === 'overlay' && (
          <button
            type="button"
            className="adaptive-nav-backdrop"
            aria-label="Fermer la navigation"
            onClick={onRequestClose}
          />
        )}
        <aside
          className={`adaptive-nav adaptive-nav--${displayMode}`}
          aria-label={expandedAdaptive ? 'Navigation complète' : 'Navigation essentielle'}
        >
          <div className="adaptive-nav__brand">
            {!expandedAdaptive ? (
              <NavigationModeControl embedded />
            ) : (
              <button
                type="button"
                className="adaptive-nav__icon-button"
                onClick={activateAvatar}
                aria-label="Activer ou afficher l’avatar Marvin"
                title="Avatar Marvin"
              >
                <LivingAvatar size={36} thinking={chatStatus.isLoading} />
              </button>
            )}
            {expandedAdaptive && (
              <div className="adaptive-nav__brand-copy">
                <strong>MARVIN</strong>
                <small>{chatStatus.isLoading ? 'Travail en cours' : 'Prêt à travailler'}</small>
              </div>
            )}
            {expandedAdaptive && <NavigationModeControl embedded />}
            {displayMode === 'overlay' && (
              <button
                type="button"
                className="adaptive-nav__icon-button"
                onClick={onRequestClose}
                aria-label="Fermer la navigation"
              >
                <X size={18} aria-hidden="true" />
              </button>
            )}
          </div>

          <nav className="adaptive-nav__list">
            {adaptiveSections.map(section => (
              <div key={section.title}>
                {expandedAdaptive && <div className="adaptive-nav__section-label">{section.title}</div>}
                {section.items.map(item => {
                  const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
                  const Icon = item.icon;
                  return (
                    <Link
                      className="adaptive-nav__link"
                      key={item.href}
                      href={item.href}
                      aria-label={item.label}
                      aria-current={active ? 'page' : undefined}
                      title={expandedAdaptive ? undefined : item.label}
                    >
                      <Icon size={20} strokeWidth={active ? 2.2 : 1.8} aria-hidden="true" />
                      {expandedAdaptive && <span>{item.label}</span>}
                    </Link>
                  );
                })}
              </div>
            ))}
            {!expandedAdaptive && (
              <button
                type="button"
                className="adaptive-nav__link adaptive-nav__more"
                aria-label="Afficher toute la navigation"
                title="Plus"
                onClick={onRequestFull}
              >
                <MoreHorizontal size={20} aria-hidden="true" />
              </button>
            )}
          </nav>

          <div className="adaptive-nav__footer">
            <button
              type="button"
              className="adaptive-nav__icon-button"
              aria-label="Ouvrir le centre de commandes"
              title="Centre de commandes (Ctrl+K)"
              onClick={() => window.dispatchEvent(new Event('marvin:open-command-palette'))}
            >
              <Search size={19} aria-hidden="true" />
            </button>
            {expandedAdaptive && (
              <>
                <span style={{ flex: 1, color: 'var(--text-muted)', fontSize: 10 }}>
                  {longTaskCount > 0 ? `${longTaskCount} tâche(s) de fond` : 'Navigation complète'}
                </span>
                <span className={`badge-dot ${ollamaStatus}`} title={`Ollama : ${ollamaStatus}`} />
              </>
            )}
          </div>
        </aside>
      </>
    );
  }

  return (
    <>
      {/* Bouton ☰ (mobile uniquement) */}
      {isMobile && (
        <button
          onClick={() => setMobileOpen(o => !o)}
          aria-label="Menu"
          style={{
            position: 'fixed', top: 8, left: 8, zIndex: 1002,
            width: 42, height: 42, borderRadius: 10,
            background: 'rgba(13,13,13,0.92)', border: '1px solid rgba(79, 140, 255,0.3)',
            color: '#4f8cff', fontSize: 20, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            backdropFilter: 'blur(8px)',
          }}
        >
          {mobileOpen ? '✕' : '☰'}
        </button>
      )}

      {/* Fond semi-opaque quand le tiroir est ouvert (mobile) */}
      {isMobile && mobileOpen && (
        <div onClick={() => setMobileOpen(false)}
          style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)' }} />
      )}

      <aside
        onMouseEnter={() => { if (!isMobile) setExpanded(true); }}
        onMouseLeave={() => { if (!isMobile && !pinned) setExpanded(false); }}
        style={{
          position: 'fixed',
          left: 0, top: 0, bottom: 0,
          width: isMobile ? 'var(--sidebar-expanded)' : (expanded ? 'var(--sidebar-expanded)' : 'var(--sidebar-collapsed)'),
          transform: isMobile ? (mobileOpen ? 'translateX(0)' : 'translateX(-100%)') : 'none',
          background: '#0d0d0d',
          borderRight: '1px solid rgba(228, 228, 231,0.06)',
          display: 'flex',
          flexDirection: 'column',
          zIndex: 1001,
          transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1), transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
          overflow: 'hidden',
          boxShadow: isMobile && mobileOpen ? '8px 0 32px rgba(0,0,0,0.6)' : 'none',
        }}
      >
      {/* ── Logo / Brand ───────────────────────────────────────── */}
      <div style={{
        padding: open ? '14px 16px' : '13px 14px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        borderBottom: '1px solid rgba(228, 228, 231,0.06)',
        minHeight: '70px',
      }}>
        {/* Statut de Marvin (s'accélère quand il traite une demande) */}
        <button type="button" onClick={activateAvatar} style={{
          width: '44px',
          height: '44px',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 0, border: 0, background: 'transparent', cursor: 'pointer',
        }} title={avatarStatus === 'running' ? 'Afficher l’avatar de bureau' : 'Activer l’avatar de bureau'}>
          <LivingAvatar size={44} thinking={chatStatus.isLoading} />
        </button>

        {/* Brand text */}
        <button type="button" onClick={activateAvatar} aria-label="Ouvrir l’avatar de bureau Marvin" style={{
          opacity: open ? 1 : 0,
          transform: open ? 'translateX(0)' : 'translateX(-8px)',
          transition: 'all 0.22s ease',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textAlign: 'left', border: 0, padding: 0, background: 'transparent', cursor: 'pointer',
        }}>
          <div className="holo-text" style={{
            fontWeight: 800,
            fontSize: '1.05rem',
            letterSpacing: '0.16em',
            lineHeight: 1.2,
          }}>
            MARVIN
          </div>
          <div style={{
            fontSize: '9px',
            letterSpacing: '0.1em',
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
            lineHeight: 1.3,
          }}>
            {avatarStatus === 'starting' ? 'Ouverture avatar…' : avatarStatus === 'running' ? 'Avatar actif — cliquer pour afficher' : 'Avatar bureau — cliquer pour ouvrir'}
          </div>
        </button>
        {!isMobile && open && (
          <button
            type="button"
            onClick={togglePinned}
            aria-pressed={pinned}
            aria-label={pinned ? 'Réduire la navigation' : 'Garder la navigation ouverte'}
            title={pinned ? 'Réduire la navigation' : 'Garder la navigation ouverte'}
            style={{
              marginLeft: 'auto', width: 32, height: 32, flexShrink: 0,
              display: 'grid', placeItems: 'center', borderRadius: 8,
              border: '1px solid var(--border)', background: pinned ? 'rgba(79,140,255,.1)' : 'transparent',
              color: pinned ? 'var(--accent-primary)' : 'var(--text-muted)', cursor: 'pointer',
            }}
          >
            {pinned ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
          </button>
        )}
      </div>

      {/* ── Palette de commandes (Ctrl+K) ──────────────────────── */}
      <div style={{ padding: open ? '10px 12px 4px' : '10px 13px 4px' }}>
        <button
          onClick={() => window.dispatchEvent(new Event('marvin:open-command-palette'))}
          title="Rechercher (Ctrl+K)"
          style={{
            width: '100%', display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 10px', borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border)', background: 'rgba(255,255,255,0.02)',
            color: 'var(--text-muted)', cursor: 'pointer', fontSize: 12.5,
          }}
        >
          <span style={{ fontSize: 14 }}>🔍</span>
          {open && (
            <>
              <span style={{ flex: 1, textAlign: 'left' }}>Rechercher…</span>
              <kbd style={{ fontSize: 10, border: '1px solid var(--border)', borderRadius: 4, padding: '1px 5px' }}>Ctrl K</kbd>
            </>
          )}
        </button>
      </div>

      {/* ── Navigation ─────────────────────────────────────────── */}
      <nav style={{
        flex: 1,
        padding: '10px 0',
        display: 'flex',
        flexDirection: 'column',
        gap: '2px',
        overflowY: 'auto',
        overflowX: 'hidden',
        scrollbarWidth: 'thin',
        scrollbarColor: 'rgba(79, 140, 255,0.2) transparent',
      }}>
        {NAV_SECTIONS.map((section) => (
         <div key={section.title}>
          <div style={{ height: open ? 'auto' : 6, overflow: 'hidden', fontSize: 9.5, fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--accent-primary)', opacity: open ? 0.6 : 0, padding: open ? '10px 20px 3px' : '0', transition: 'opacity .2s' }}>{section.title}</div>
          {section.items.map((item) => {
          const isActive = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-label={item.label}
              aria-current={isActive ? 'page' : undefined}
              title={open ? undefined : item.label}
              style={{ display: 'block', width: '100%', textDecoration: 'none' }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: open ? '13px' : 0,
                  padding: open ? '9px 13px' : '9px 0',
                  margin: open ? '0 8px' : '0 3px 0 14px',
                  minHeight: '44px',
                  justifyContent: open ? 'flex-start' : 'center',
                  borderRadius: 'var(--radius-md)',
                  color: isActive ? '#4f8cff' : 'var(--text-muted)',
                  background: isActive ? 'rgba(79, 140, 255,0.07)' : 'transparent',
                  position: 'relative',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                  overflow: 'hidden',
                  border: isActive ? '1px solid rgba(79, 140, 255,0.15)' : '1px solid transparent',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'rgba(228, 228, 231,0.04)';
                    e.currentTarget.style.color = 'var(--text-secondary)';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = 'var(--text-muted)';
                  }
                }}
              >
                {/* Active indicator */}
                {isActive && (
                  <div style={{
                    position: 'absolute',
                    left: 0,
                    top: '20%',
                    bottom: '20%',
                    width: '3px',
                    borderRadius: '0 3px 3px 0',
                    background: 'var(--accent-gradient)',
                    boxShadow: '0 0 8px rgba(79, 140, 255,0.4)',
                  }} />
                )}
                <span style={{
                  flexShrink: 0,
                  width: open ? '26px' : '48px',
                  height: open ? '26px' : '44px',
                  display: 'grid',
                  placeItems: 'center',
                  position: 'relative',
                }}>
                  <Icon size={22} strokeWidth={isActive ? 2.2 : 1.8} aria-hidden="true" />
                  {/* Pulse indicator on the Chat nav item when Marvin is processing */}
                  {item.href === '/' && chatStatus.isLoading && (
                    <span
                      title="Marvin réfléchit…"
                      style={{
                        position: 'absolute',
                        top: '-2px',
                        right: '-4px',
                        width: '10px',
                        height: '10px',
                        borderRadius: '50%',
                        background: '#4f8cff',
                        boxShadow: '0 0 8px #4f8cff, 0 0 14px #4f8cff80',
                        animation: 'pulse 1.4s ease-in-out infinite',
                        border: '2px solid #0d0d0d',
                      }}
                    />
                  )}
                </span>
                <span style={{
                  fontSize: 'var(--font-sm)',
                  fontWeight: isActive ? 600 : 400,
                  whiteSpace: 'nowrap',
                  opacity: expanded ? 1 : 0,
                  transition: 'opacity 0.2s ease',
                  display: open ? 'flex' : 'none',
                  alignItems: 'center',
                  gap: '8px',
                }}>
                  {item.label}
                  {/* Inline thinking text when expanded + on Chat row */}
                  {item.href === '/' && chatStatus.isLoading && open && (
                    <span style={{
                      fontSize: '10px',
                      color: '#4f8cff',
                      fontStyle: 'italic',
                      letterSpacing: '0.05em',
                    }}>
                      ● en cours
                    </span>
                  )}
                </span>
              </div>
            </Link>
          );
          })}
         </div>
        ))}
      </nav>

      {/* ── Tâche(s) longue(s) en cours en arrière-plan (v2.145/v2.146) ──────── */}
      {longTaskCount > 0 && (
        <Link
          href="/tasks"
          title={`${longTaskCount} tâche(s) longue(s) en cours en arrière-plan`}
          style={{
            padding: '10px 20px',
            borderTop: '1px solid rgba(228, 228, 231,0.06)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            textDecoration: 'none',
            color: 'var(--success)',
          }}
        >
          <span style={{ fontSize: '14px', flexShrink: 0 }}>🗂️</span>
          <span style={{
            fontSize: '10px',
            whiteSpace: 'nowrap',
            opacity: open ? 1 : 0,
            transition: 'opacity 0.2s ease',
            letterSpacing: '0.03em',
            fontWeight: 600,
          }}>
            {longTaskCount} tâche{longTaskCount > 1 ? 's' : ''} de fond en cours
          </span>
        </Link>
      )}

      {/* ── Status Ollama ──────────────────────────────────────── */}
      <div style={{
        padding: '14px 20px',
        borderTop: '1px solid rgba(228, 228, 231,0.06)',
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        minHeight: '52px',
      }}>
        <span
          className={`badge-dot ${ollamaStatus}`}
          style={{ flexShrink: 0 }}
        />
        <span style={{
          fontSize: '10px',
          color: 'var(--text-muted)',
          whiteSpace: 'nowrap',
          opacity: open ? 1 : 0,
          transition: 'opacity 0.2s ease',
          letterSpacing: '0.03em',
        }}>
          {ollamaStatus === 'connected' ? 'Ollama connecté' :
           ollamaStatus === 'checking' ? 'Vérification...' : 'Ollama hors ligne'}
        </span>
      </div>
    </aside>
    </>
  );
}
