'use client';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useChatStatus } from '@/lib/contexts/ChatContext';
import LivingAvatar from '@/components/avatar/LivingAvatar';
import { BACKEND_URL } from '@/lib/backend';

export const NAV_SECTIONS = [
  { title: 'Assistant', items: [
    { href: '/',           icon: '💬', label: 'Chat' },
    { href: '/jour',       icon: '🌅', label: 'Mon jour' },
    { href: '/recherche',  icon: '🔍', label: 'Recherche' },
  ]},
  { title: 'PC & Système', items: [
    { href: '/outils',     icon: '🔧', label: 'Outils' },
    { href: '/systeme',    icon: '🖥️', label: 'PC & Système' },
    { href: '/ssh',        icon: '🔗', label: 'SSH' },
    { href: '/monitoring', icon: '📊', label: 'Monitoring' },
  ]},
  { title: 'Organisation', items: [
    { href: '/tasks',      icon: '✅', label: 'Tâches' },
    { href: '/notes',      icon: '📝', label: 'Notes' },
    { href: '/emails',     icon: '📧', label: 'Emails' },
    { href: '/calendar',   icon: '📅', label: 'Calendrier' },
    { href: '/devis',      icon: '📋', label: 'Devis & Factu' },
    { href: '/fichiers',   icon: '📁', label: 'Fichiers' },
  ]},
  { title: 'IA & Contenu', items: [
    { href: '/skills',     icon: '🧩', label: 'Compétences' },
    { href: '/redaction',  icon: '✍️', label: 'Rédaction IA' },
    { href: '/video',      icon: '🎬', label: 'Vidéo IA' },
    { href: '/docs',       icon: '📚', label: 'Doc Tech IA' },
    { href: '/memoire',    icon: '🧠', label: 'Mémoire' },
  ]},
  { title: 'Automatisation', items: [
    { href: '/code',       icon: '</>', label: 'Code Workspace' },
    { href: '/workflows',  icon: '⚡', label: 'Workflows' },
    { href: '/agents',     icon: '🤖', label: 'Multi-Agents' },
    { href: '/market',     icon: 'M', label: 'Model Market' },
    { href: '/evolution',  icon: 'E', label: 'Evolution Lab' },
    { href: '/missions',   icon: 'C', label: 'Mission Canvas' },
    { href: '/forge',      icon: 'F', label: 'Forge' },
    { href: '/cron',       icon: '⏰', label: 'Planificateur' },
  ]},
  { title: 'Réglages', items: [
    { href: '/technique',  icon: '📖', label: 'Guide Technique' },
    { href: '/mobile',     icon: '📱', label: 'Accès mobile' },
    { href: '/mcp',        icon: '🔌', label: 'MCP' },
    { href: '/settings',   icon: '⚙️', label: 'Paramètres' },
  ]},
];
const NAV_ITEMS = NAV_SECTIONS.flatMap(s => s.items);
const OLLAMA_PORT = process.env.NEXT_PUBLIC_OLLAMA_PORT || '11434';

export default function Sidebar() {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);
  const [ollamaStatus, setOllamaStatus] = useState('checking');
  const [isMobile, setIsMobile] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [avatarStatus, setAvatarStatus] = useState('checking');
  // v2.146 — indicateur ambiant de tâche(s) longue(s) en cours (long_task_start, v2.145) :
  // demandé explicitement (« que l'on sache que Marvin travaille d'une certaine manière »).
  // Jusqu'ici totalement invisible tant qu'on ne demandait pas explicitement long_task_status
  // — une tâche pouvait tourner en arrière-plan (reprise cron) sans AUCUN signal ambiant.
  const [longTaskCount, setLongTaskCount] = useState(0);
  const chatStatus = useChatStatus();   // { isLoading, status, conversationId, messageCount }

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
  const open = isMobile ? mobileOpen : expanded;

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
        onMouseLeave={() => { if (!isMobile) setExpanded(false); }}
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
          return (
            <Link key={item.href} href={item.href} style={{ textDecoration: 'none' }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: open ? '13px' : 0,
                  padding: open ? '9px 13px' : '9px 0',
                  margin: open ? '0 8px' : '0 9px',
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
                  fontSize: '1.15rem',
                  flexShrink: 0,
                  width: '26px',
                  textAlign: 'center',
                  filter: isActive ? 'none' : 'grayscale(0.4)',
                  position: 'relative',
                }}>
                  {item.icon}
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
                  display: 'flex',
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
