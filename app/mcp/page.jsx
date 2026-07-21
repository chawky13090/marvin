'use client';

import { useState, useEffect, useCallback } from 'react';
import { useToast } from '@/components/ui/Toast';
import { LoadingRow } from '@/components/ui/Spinner';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

const PERM_COLOR = { 1: '#34d399', 2: '#60a5fa', 3: '#f97316' };

export default function McpPage() {
  const { toast } = useToast();
  const [cfg, setCfg] = useState(null);
  const [health, setHealth] = useState(null); // null=checking, true/false
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND}/api/mcp/config`).then(r => r.json());
      setCfg(r);
      setHealth(true);
    } catch {
      setHealth(false);
    }
  }, []);
  useEffect(() => { load(); const iv = setInterval(load, 15000); return () => clearInterval(iv); }, [load]);

  const copy = () => {
    if (!cfg) return;
    navigator.clipboard?.writeText(cfg.config_json).then(() => {
      setCopied(true);
      toast.success('Config copiée', 'Colle-la dans claude_desktop_config.json (ou la config de ton client MCP)');
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const card = { background: 'var(--bg-glass)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 22px', marginBottom: 18 };

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg-primary)', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 820, margin: '0 auto' }}>
        <h1 style={{ margin: 0, fontSize: '1.6rem', display: 'flex', alignItems: 'center', gap: 10 }}>🔌 MCP (Model Context Protocol)</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 22 }}>
          Connecte Marvin à Claude Desktop, Cursor ou tout autre client compatible MCP — ces applications pourront alors utiliser les {cfg?.tools_count || 294} outils de Marvin directement.
        </div>

        {/* ── Qu'est-ce que MCP ? ── */}
        <div style={card}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>ℹ️ En bref</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            MCP est un standard ouvert qui permet à une IA (Claude, Cursor…) d'appeler les outils d'une autre application.
            Marvin agit ici en <strong>serveur</strong> : il expose ses outils déjà vérifiés (fichiers, PC, réseau, calendrier…).
            <br /><br />
            <strong>Marvin ne se connecte lui-même à aucun serveur MCP tiers</strong> — uniquement le sens serveur, par choix de
            sécurité (l'écosystème MCP a des serveurs tiers non audités, parfois piégés). Voir <code>CLAUDE.md §6</code> pour le détail.
          </div>
        </div>

        {/* ── Statut ── */}
        <div style={card}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>📡 Statut</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <span style={{ width: 9, height: 9, borderRadius: '50%', background: health ? '#34d399' : health === false ? '#f87171' : '#6b7280', flexShrink: 0 }} />
            <span style={{ fontSize: 13 }}>
              {health === null ? 'Vérification…' : health ? 'Backend Marvin joignable — les outils MCP répondront.' : 'Backend injoignable — lance start.bat avant de connecter un client MCP.'}
            </span>
          </div>
          {cfg && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 9, height: 9, borderRadius: '50%', background: PERM_COLOR[cfg.permission_level] || '#6b7280', flexShrink: 0 }} />
              <span style={{ fontSize: 13 }}>
                Niveau de permission actuel : <strong>{cfg.permission_info.label}</strong> — {cfg.permission_info.note}
              </span>
            </div>
          )}
        </div>

        {/* ── Config à copier ── */}
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>⚙️ Configuration (Claude Desktop, Cursor…)</div>
            <button onClick={copy} disabled={!cfg} className="btn btn-primary" style={{ fontSize: 12, padding: '7px 14px' }}>
              {copied ? '✅ Copié' : '📋 Copier'}
            </button>
          </div>
          {!cfg ? <LoadingRow /> : (
            <pre style={{
              background: 'rgba(0,0,0,0.35)', border: '1px solid var(--border)', borderRadius: 10,
              padding: '14px 16px', fontSize: 12, fontFamily: 'monospace', overflowX: 'auto',
              color: 'var(--text-secondary)', margin: 0,
            }}>{cfg.config_json}</pre>
          )}
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 12, lineHeight: 1.6 }}>
            Colle ceci dans le fichier de config de ton client MCP :
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              <li><strong>Claude Desktop</strong> (Windows) : <code>%APPDATA%\Claude\claude_desktop_config.json</code></li>
              <li><strong>Cursor</strong> : Paramètres → MCP → Ajouter un serveur</li>
            </ul>
            Les chemins ci-dessus sont générés depuis <strong>cette installation</strong> — si tu réinstalles Marvin sur une autre machine, reviens sur cette page pour la config à jour (rien n'est codé en dur).
          </div>
        </div>

        {/* ── Sécurité ── */}
        <div style={card}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>🛡️ Ce qu'il faut savoir</div>
          <ul style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.8, margin: 0, paddingLeft: 18 }}>
            <li>Un client MCP connecté peut appeler <strong>n'importe lequel</strong> des {cfg?.tools_count || 294} outils de Marvin.</li>
            <li>Le comportement de confirmation suit ton <a href="/settings" style={{ color: 'var(--accent-primary)' }}>niveau de permission</a> actuel — pas de règle spéciale pour MCP.</li>
            <li>Rien ne se connecte automatiquement : ce serveur ne démarre que si TON client MCP le lance explicitement.</li>
            <li>Redémarre ton client MCP après un changement de niveau de permission ou une réinstallation.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
