'use client';
import { useState, useEffect, useRef, useCallback, useMemo, forwardRef, useImperativeHandle } from 'react';
import { useToast } from '@/components/ui/Toast';
import { LoadingRow } from '@/components/ui/Spinner';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

// ── Terminal interactif RÉEL (PTY via WebSocket + xterm.js) ──────────────────
// v2.118 — remplace l'ancien modèle "tapez une commande → attendez le résultat" (SSE,
// une requête par commande) par un vrai shell interactif : paramiko ouvre un canal PTY
// (`invoke_shell`) côté backend et transmet les octets bruts en continu dans les deux sens.
// Fonctionne IDENTIQUEMENT pour une cible Windows ou Linux — le protocole SSH délègue le
// choix du shell (cmd.exe/PowerShell ou bash/sh) au serveur OpenSSH distant, Marvin ne fait
// que relayer les octets. Supporte nativement : historique de commandes du shell distant,
// tab-completion, programmes plein écran (top, vim, less…), couleurs, Ctrl+C, etc. — tout
// ce qu'un vrai client SSH (PuTTY) offre déjà.
const XtermSSH = forwardRef(function XtermSSH({ conn }, ref) {
  const containerRef = useRef(null);
  const termRef = useRef(null);
  const wsRef = useRef(null);
  const fitRef = useRef(null);
  const [status, setStatus] = useState('connecting'); // connecting | open | closed | error

  useImperativeHandle(ref, () => ({
    sendText: (text) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data: text }));
      termRef.current?.focus();
    },
    clear: () => termRef.current?.clear(),
    fit: () => {
      // Le conteneur a des dimensions nulles pendant qu'il est display:none (onglet
      // Fichiers/Infos actif) — recalcule la taille au moment où l'onglet Terminal
      // redevient visible, sinon xterm.js reste figé sur son dernier calcul (souvent 0).
      try {
        fitRef.current?.fit();
        const ws = wsRef.current, term = termRef.current;
        if (ws?.readyState === WebSocket.OPEN && term) {
          ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
        }
      } catch {}
    },
  }), []);

  useEffect(() => {
    let disposed = false;
    const term = new XTerm({
      cursorBlink: true,
      fontFamily: '"Cascadia Code", "Fira Code", "Consolas", monospace',
      fontSize: 13,
      theme: { background: '#0a0a0a', foreground: '#e2e8f0', cursor: '#4f8cff', selectionBackground: '#4f8cff44' },
      scrollback: 5000,
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);
    fitAddon.fit();
    termRef.current = term;
    fitRef.current = fitAddon;

    const wsUrl = `${BACKEND.replace(/^http/, 'ws')}/api/ssh/${conn.id}/shell`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    setStatus('connecting');

    ws.onopen = () => {
      if (disposed) return;
      setStatus('open');
      ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      term.focus();
    };
    ws.onmessage = (e) => {
      if (disposed) return;
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'data') term.write(msg.data);
        else if (msg.type === 'error') { setStatus('error'); term.write(`\r\n\x1b[31m❌ ${msg.message}\x1b[0m\r\n`); }
        else if (msg.type === 'closed') { setStatus('closed'); term.write('\r\n\x1b[90m[Connexion fermée]\x1b[0m\r\n'); }
      } catch {}
    };
    ws.onerror = () => { if (!disposed) setStatus('error'); };
    ws.onclose = () => { if (!disposed) setStatus(s => s === 'error' ? s : 'closed'); };

    const dataDisposable = term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data }));
    });

    const resizeObserver = new ResizeObserver(() => {
      try {
        fitAddon.fit();
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      } catch {}
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      disposed = true;
      resizeObserver.disconnect();
      dataDisposable.dispose();
      try { ws.close(); } catch {}
      term.dispose();
    };
  }, [conn.id]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {status !== 'open' && (
        <div style={{
          padding: '5px 16px', fontSize: '11px',
          color: status === 'error' ? '#f87171' : status === 'closed' ? 'var(--text-muted)' : '#60a5fa',
        }}>
          {status === 'connecting' ? '⏳ Connexion au shell distant…' : status === 'error' ? '❌ Erreur de connexion' : '○ Session fermée'}
        </div>
      )}
      <div ref={containerRef} style={{ flex: 1, padding: '8px 12px', minHeight: 0 }} />
    </div>
  );
});

// ── Formulaire nouvelle connexion / édition ──────────────────────────────────
function ConnectionForm({ editing, onSaved, onClose }) {
  const { toast } = useToast();
  const [form, setForm] = useState(editing
    ? { name: editing.name, host: editing.host, port: String(editing.port), username: editing.username, password: '', private_key: '', key_passphrase: '' }
    : { name: '', host: '', port: '22', username: '', password: '', private_key: '', key_passphrase: '' });
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [authMode, setAuthMode] = useState('password'); // 'password' | 'key'

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const handleTest = async () => {
    setTesting(true); setTestResult(null);
    try {
      // En édition, si le formulaire ne contient pas de nouveau secret, le backend réutilise
      // automatiquement celui déjà en base (cf. /api/ssh/test, connection_id).
      const r = await fetch(`${BACKEND}/api/ssh/test`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, port: Number(form.port), connection_id: editing?.id || '' }),
      });
      setTestResult(await r.json());
    } catch (e) { setTestResult({ success: false, error: e.message }); }
    setTesting(false);
  };

  const handleSave = async () => {
    if (!form.name || !form.host || !form.username) return;
    setSaving(true);
    try {
      const url = editing ? `${BACKEND}/api/ssh/${editing.id}` : `${BACKEND}/api/ssh`;
      const r = await fetch(url, {
        method: editing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, port: Number(form.port) }),
      });
      if (!r.ok) throw new Error(await r.text());
      onSaved(await r.json());
      toast.success(editing ? 'Connexion mise à jour' : 'Connexion ajoutée', form.name);
      onClose();
    } catch (e) { toast.error('Échec de la sauvegarde', String(e)); }
    setSaving(false);
  };

  const inp = (k, label, opts = {}) => (
    <div>
      <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '4px' }}>
        {label}{opts.required && <span style={{ color: '#4f8cff' }}> *</span>}
      </label>
      {opts.textarea ? (
        <textarea
          value={form[k]} onChange={e => set(k, e.target.value)}
          placeholder={opts.placeholder} rows={4}
          style={{ ...iStyle, resize: 'vertical', fontFamily: 'monospace', fontSize: '11px' }}
        />
      ) : (
        <input
          type={opts.password ? 'password' : opts.number ? 'number' : 'text'}
          value={form[k]} onChange={e => set(k, e.target.value)}
          placeholder={opts.placeholder}
          style={iStyle}
        />
      )}
    </div>
  );

  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(79, 140, 255,0.3)',
      borderRadius: '14px', padding: '22px 24px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '18px' }}>
        <span style={{ fontWeight: 700, color: '#4f8cff' }}>
          {editing ? `✏️ Modifier « ${editing.name} »` : '🔗 Nouvelle connexion SSH'}
        </span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '18px' }}>×</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        {inp('name', 'Nom', { required: true, placeholder: 'Mon serveur Linux' })}
        {inp('host', 'Hôte / IP', { required: true, placeholder: '192.168.1.100 ou serveur.com' })}
        {inp('port', 'Port', { number: true, placeholder: '22' })}
        {inp('username', 'Nom d\'utilisateur', { required: true, placeholder: 'root ou ubuntu' })}

        <div style={{ gridColumn: '1 / -1' }}>
          <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
            {['password', 'key'].map(m => (
              <button key={m} onClick={() => setAuthMode(m)} style={{
                padding: '5px 14px', borderRadius: '8px', border: 'none', cursor: 'pointer',
                background: authMode === m ? '#4f8cff22' : 'rgba(255,255,255,0.04)',
                color: authMode === m ? '#4f8cff' : 'var(--text-muted)',
                fontWeight: authMode === m ? 700 : 400, fontSize: '12px',
                borderBottom: authMode === m ? '2px solid #4f8cff' : '2px solid transparent',
              }}>
                {m === 'password' ? '🔑 Mot de passe' : '🗝️ Clé privée'}
              </button>
            ))}
          </div>
          {editing && (
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px' }}>
              Laissez vide pour conserver le secret actuel — ne sera remplacé que si vous saisissez une nouvelle valeur.
            </div>
          )}
          {authMode === 'password'
            ? inp('password', 'Mot de passe', { password: true, placeholder: editing ? '(inchangé)' : '••••••••' })
            : (
              <div style={{ display: 'grid', gap: '10px' }}>
                {inp('private_key', 'Clé privée (PEM — RSA, Ed25519, ECDSA, DSS)', { textarea: true, placeholder: editing ? '(inchangée)' : '-----BEGIN OPENSSH PRIVATE KEY-----\n...' })}
                {inp('key_passphrase', 'Passphrase de la clé (si chiffrée)', { password: true, placeholder: editing ? '(inchangée)' : 'optionnel' })}
              </div>
            )
          }
        </div>
      </div>

      {testResult && (
        <div style={{
          marginTop: '12px', padding: '10px 14px', borderRadius: '8px',
          background: testResult.success ? '#22c55e15' : '#ef444415',
          border: `1px solid ${testResult.success ? '#22c55e40' : '#ef444440'}`,
          fontSize: '12px', color: testResult.success ? '#4ade80' : '#f87171',
        }}>
          {testResult.success ? `✅ Connecté — ${testResult.info}` : `❌ ${testResult.error}`}
        </div>
      )}

      <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
        <button onClick={handleTest} disabled={testing || !form.host}
          style={{ ...btnBase('#3b82f6'), flex: 1 }}>
          {testing ? '⏳ Test…' : '🧪 Tester'}
        </button>
        <button onClick={handleSave} disabled={saving || !form.name || !form.host || !form.username}
          style={{ ...btnBase('#4f8cff'), flex: 2, opacity: (!form.name || !form.host || !form.username) ? 0.5 : 1 }}>
          {saving ? '⏳ Sauvegarde…' : '💾 Sauvegarder'}
        </button>
      </div>
    </div>
  );
}

const iStyle = {
  width: '100%', padding: '8px 12px', background: 'var(--bg-primary)',
  border: '1px solid var(--border)', borderRadius: '8px',
  color: 'var(--text-primary)', fontSize: '0.875rem', outline: 'none',
  boxSizing: 'border-box',
};
const btnBase = (color) => ({
  padding: '9px 18px', background: `${color}20`, border: `1px solid ${color}50`,
  borderRadius: '9px', color: color, cursor: 'pointer', fontWeight: 600, fontSize: '13px',
});

// ── Panneau SFTP (navigateur de fichiers distant) ────────────────────────────
function SftpBrowser({ conn }) {
  const { toast } = useToast();
  const [path, setPath] = useState('.');
  const [entries, setEntries] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async (p) => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${BACKEND}/api/ssh/${conn.id}/browse?path=${encodeURIComponent(p)}`);
      const data = await r.json();
      if (data.error) { setError(data.error); setEntries(null); }
      else { setEntries(data.entries || []); setPath(data.remote_path ?? p); }
    } catch (e) { setError(String(e)); }
    setLoading(false);
  }, [conn.id]);

  useEffect(() => { load('.'); }, [load]);

  const openDir = (entry) => load(entry.path);
  const goUp = () => {
    const parent = path.replace(/\/+$/, '').split('/').slice(0, -1).join('/') || '/';
    load(parent);
  };

  const download = (entry) => {
    window.open(`${BACKEND}/api/ssh/${conn.id}/download?path=${encodeURIComponent(entry.path)}`, '_blank');
  };

  const upload = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const remote = (path === '.' ? '' : path.replace(/\/+$/, '')) + '/' + file.name;
      const fd = new FormData();
      fd.append('remote_path', remote.replace(/^\/+/, '/'));
      fd.append('file', file);
      const r = await fetch(`${BACKEND}/api/ssh/${conn.id}/upload`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      toast.success('Envoyé', file.name);
      load(path);
    } catch (e) { toast.error('Échec de l\'envoi', String(e)); }
    setUploading(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <button onClick={goUp} disabled={loading} title="Dossier parent"
          style={{ padding: '4px 10px', fontSize: '12px', borderRadius: '6px', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-muted)', cursor: 'pointer' }}>⬆ ..</button>
        <span style={{ fontFamily: 'monospace', fontSize: '12px', color: '#4f8cff', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{path}</span>
        <input ref={fileInputRef} type="file" style={{ display: 'none' }} onChange={e => upload(e.target.files?.[0])} />
        <button onClick={() => fileInputRef.current?.click()} disabled={uploading}
          style={{ padding: '4px 12px', fontSize: '11px', borderRadius: '6px', background: '#4f8cff20', border: '1px solid #4f8cff50', color: '#4f8cff', cursor: 'pointer', fontWeight: 600 }}>
          {uploading ? '⏳ Envoi…' : '⬆ Envoyer un fichier'}
        </button>
        <button onClick={() => load(path)} disabled={loading} title="Rafraîchir"
          style={{ padding: '4px 10px', fontSize: '12px', borderRadius: '6px', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-muted)', cursor: 'pointer' }}>↻</button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 16px 16px' }}>
        {loading && !entries ? <LoadingRow /> : error ? (
          <div style={{ color: '#f87171', fontSize: '12px', padding: '16px 0' }}>❌ {error}</div>
        ) : (entries || []).length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '12px', padding: '16px 0', textAlign: 'center' }}>Dossier vide.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {entries.map((e, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: '10px', padding: '6px 8px',
                borderRadius: '6px', fontSize: '12px', cursor: e.is_dir ? 'pointer' : 'default',
              }}
                onMouseEnter={ev => ev.currentTarget.style.background = 'rgba(255,255,255,0.04)'}
                onMouseLeave={ev => ev.currentTarget.style.background = 'transparent'}
                onClick={() => e.is_dir && openDir(e)}
              >
                <span style={{ width: '16px', textAlign: 'center' }}>{e.is_dir ? '📁' : '📄'}</span>
                <span style={{ flex: 1, color: e.is_dir ? '#4f8cff' : 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.name}</span>
                {!e.is_dir && <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: '11px' }}>{e.size_human}</span>}
                {!e.is_dir && (
                  <button onClick={ev => { ev.stopPropagation(); download(e); }} title="Télécharger"
                    style={{ background: 'none', border: 'none', color: '#4f8cff', cursor: 'pointer', fontSize: '13px', padding: '2px 4px' }}>⬇</button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Panneau Infos serveur (diagnostic rapide) ────────────────────────────────
function ServerInfoPanel({ conn }) {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${BACKEND}/api/ssh/${conn.id}/info`);
      const data = await r.json();
      if (data.error) setError(data.error); else setInfo(data.info);
    } catch (e) { setError(String(e)); }
    setLoading(false);
  }, [conn.id]);

  useEffect(() => { load(); }, [load]);

  const rows = [
    ['os', '🖥️ Système'], ['up', '⏱️ Uptime'], ['mem', '🧠 Mémoire'],
    ['disk', '💾 Disque (/)'], ['load', '📈 Charge'], ['who', '👤 Sessions'],
  ];

  return (
    <div style={{ padding: '16px 20px', overflowY: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
        <span style={{ fontWeight: 600, fontSize: '13px' }}>🩺 Diagnostic serveur</span>
        <button onClick={load} disabled={loading} style={{ padding: '4px 10px', fontSize: '11px', borderRadius: '6px', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-muted)', cursor: 'pointer' }}>↻ Rafraîchir</button>
      </div>
      {loading ? <LoadingRow /> : error ? (
        <div style={{ color: '#f87171', fontSize: '12px' }}>❌ {error}</div>
      ) : (
        <div style={{ display: 'grid', gap: '10px' }}>
          {rows.map(([key, label]) => info?.[key] ? (
            <div key={key} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '10px', padding: '12px 14px' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '6px' }}>{label}</div>
              <pre style={{ margin: 0, fontFamily: 'monospace', fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{info[key]}</pre>
            </div>
          ) : null)}
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Page principale
// ══════════════════════════════════════════════════════════════════════════════
export default function SSHPage() {
  const { toast } = useToast();
  const [connections, setConnections] = useState([]);
  const [activeConn, setActiveConn] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [editingConn, setEditingConn] = useState(null);
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState('terminal'); // terminal | files | info
  const [testingId, setTestingId] = useState(null);
  const termRef = useRef(null);

  const refreshConnections = useCallback(() => {
    fetch(`${BACKEND}/api/ssh`).then(r => r.json()).then(setConnections).catch(() => {});
  }, []);

  useEffect(() => { refreshConnections(); }, [refreshConnections]);

  const handleQuickTest = async (conn) => {
    setTestingId(conn.id);
    try {
      const r = await fetch(`${BACKEND}/api/ssh/test`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: conn.name, host: conn.host, port: conn.port, username: conn.username, connection_id: conn.id }),
      });
      const data = await r.json();
      if (data.success) toast.success('Connexion OK', `${conn.username}@${conn.host}`);
      else toast.error('Connexion échouée', data.error || conn.name);
    } catch (e) { toast.error('Connexion échouée', String(e)); }
    setTestingId(null);
    refreshConnections();
  };

  const handleDelete = async (id) => {
    if (!confirm('Supprimer cette connexion ?')) return;
    await fetch(`${BACKEND}/api/ssh/${id}`, { method: 'DELETE' });
    setConnections(prev => prev.filter(c => c.id !== id));
    if (activeConn?.id === id) setActiveConn(null);
  };

  const selectConn = (conn) => {
    setActiveConn(conn);
    setTab('terminal');
  };

  useEffect(() => {
    if (tab === 'terminal') termRef.current?.fit();
  }, [tab]);

  const filteredConnections = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return connections;
    return connections.filter(c =>
      c.name.toLowerCase().includes(q) || c.host.toLowerCase().includes(q) || c.username.toLowerCase().includes(q)
    );
  }, [connections, search]);

  return (
    <div style={{ display: 'flex', height: '100vh', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}>

      {/* ── Panneau gauche : liste connexions ── */}
      <div style={{
        width: '280px', flexShrink: 0,
        borderRight: '1px solid rgba(255,255,255,0.07)',
        display: 'flex', flexDirection: 'column',
        background: '#0d0d0d',
      }}>
        <div style={{ padding: '18px 16px 14px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <div style={{ fontWeight: 700, fontSize: '1rem', marginBottom: '2px' }}>🔗 SSH</div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Manager de connexions</div>
        </div>

        {/* Bouton Ajouter */}
        <div style={{ padding: '10px 12px 6px' }}>
          <button
            onClick={() => { setEditingConn(null); setShowAdd(s => !s); }}
            style={{
              width: '100%', padding: '8px', borderRadius: '9px', border: 'none',
              background: (showAdd && !editingConn) ? '#4f8cff22' : 'rgba(255,255,255,0.05)',
              color: (showAdd && !editingConn) ? '#4f8cff' : 'var(--text-muted)',
              cursor: 'pointer', fontSize: '12px', fontWeight: 600,
            }}
          >
            {(showAdd && !editingConn) ? '✕ Annuler' : '＋ Nouvelle connexion'}
          </button>
        </div>

        {/* Recherche */}
        {connections.length > 3 && (
          <div style={{ padding: '0 12px 8px' }}>
            <input
              value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Filtrer les connexions…"
              style={{
                width: '100%', padding: '6px 10px', borderRadius: '8px',
                border: '1px solid var(--border)', background: 'rgba(255,255,255,0.03)',
                color: 'var(--text-primary)', fontSize: '11px', boxSizing: 'border-box', outline: 'none',
              }}
            />
          </div>
        )}

        {/* Liste */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 8px' }}>
          {filteredConnections.length === 0 ? (
            <div style={{ padding: '20px 8px', color: 'var(--text-muted)', fontSize: '12px', textAlign: 'center' }}>
              {connections.length === 0 ? 'Aucune connexion. Ajoutez-en une.' : 'Aucun résultat.'}
            </div>
          ) : filteredConnections.map(conn => (
            <div
              key={conn.id}
              onClick={() => selectConn(conn)}
              style={{
                display: 'flex', alignItems: 'center', gap: '10px',
                padding: '10px 12px', borderRadius: '9px', cursor: 'pointer',
                marginBottom: '2px',
                background: activeConn?.id === conn.id ? 'rgba(79, 140, 255,0.1)' : 'transparent',
                border: `1px solid ${activeConn?.id === conn.id ? 'rgba(79, 140, 255,0.3)' : 'transparent'}`,
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { if (activeConn?.id !== conn.id) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
              onMouseLeave={e => { if (activeConn?.id !== conn.id) e.currentTarget.style.background = 'transparent'; }}
            >
              <div style={{
                width: '32px', height: '32px', borderRadius: '8px', flexShrink: 0, position: 'relative',
                background: '#1a1a1a', border: '1px solid rgba(255,255,255,0.08)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px',
              }}>
                🖥️
                {conn.last_test_ok != null && (
                  <span title={conn.last_test_ok ? 'Dernier test réussi' : 'Dernier test échoué'} style={{
                    position: 'absolute', bottom: '-2px', right: '-2px', width: '9px', height: '9px',
                    borderRadius: '50%', border: '2px solid #0d0d0d',
                    background: conn.last_test_ok ? '#22c55e' : '#ef4444',
                  }} />
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: '12px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  color: activeConn?.id === conn.id ? '#4f8cff' : 'var(--text-primary)' }}>
                  {conn.name}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {conn.username}@{conn.host}:{conn.port}
                </div>
              </div>
              <button
                onClick={e => { e.stopPropagation(); handleQuickTest(conn); }}
                disabled={testingId === conn.id}
                title="Tester la connexion"
                style={{ background: 'none', border: 'none', color: '#6b7280', cursor: testingId === conn.id ? 'default' : 'pointer', fontSize: '12px', padding: '2px 4px', opacity: testingId === conn.id ? 0.3 : 0.6 }}
              >{testingId === conn.id ? '⏳' : '🧪'}</button>
              <button
                onClick={e => { e.stopPropagation(); setEditingConn(conn); setShowAdd(true); }}
                title="Modifier"
                style={{ background: 'none', border: 'none', color: '#6b7280', cursor: 'pointer', fontSize: '13px', padding: '2px 4px', opacity: 0.6 }}
              >✏️</button>
              <button
                onClick={e => { e.stopPropagation(); handleDelete(conn.id); }}
                title="Supprimer"
                style={{ background: 'none', border: 'none', color: '#6b7280', cursor: 'pointer', fontSize: '14px', padding: '2px 4px', opacity: 0.6 }}
              >✕</button>
            </div>
          ))}
        </div>
      </div>

      {/* ── Panneau droit : terminal / fichiers / infos ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Formulaire ajout/édition (overlay) */}
        {showAdd && (
          <div style={{ padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.06)', overflowY: 'auto' }}>
            <ConnectionForm
              editing={editingConn}
              onSaved={(conn) => {
                if (editingConn) {
                  setConnections(prev => prev.map(c => c.id === conn.id ? { ...c, ...conn } : c));
                  if (activeConn?.id === conn.id) setActiveConn(prev => ({ ...prev, ...conn }));
                } else {
                  setConnections(prev => [...prev, conn]);
                  selectConn(conn);
                }
                setShowAdd(false); setEditingConn(null);
              }}
              onClose={() => { setShowAdd(false); setEditingConn(null); }}
            />
          </div>
        )}

        {!activeConn ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: '12px', color: 'var(--text-muted)' }}>
            <div style={{ fontSize: '3rem' }}>🔗</div>
            <div style={{ fontSize: '0.9rem' }}>Sélectionnez ou créez une connexion SSH</div>
          </div>
        ) : (
          <>
            {/* Header + onglets */}
            <div style={{
              padding: '10px 20px', borderBottom: '1px solid rgba(255,255,255,0.06)',
              display: 'flex', alignItems: 'center', gap: '12px',
              background: 'rgba(0,0,0,0.3)',
            }}>
              <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#22c55e', boxShadow: '0 0 6px #22c55e88' }} />
              <span style={{ fontFamily: 'monospace', fontSize: '12px', color: '#4f8cff' }}>
                {activeConn.username}@{activeConn.host}:{activeConn.port}
              </span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: '4px' }}>— {activeConn.name}</span>

              <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto' }}>
                {[['terminal', '💻 Terminal'], ['files', '📁 Fichiers'], ['info', '🩺 Infos']].map(([v, lbl]) => (
                  <button key={v} onClick={() => setTab(v)} style={{
                    padding: '5px 12px', borderRadius: '7px', fontSize: '11px', cursor: 'pointer',
                    border: `1px solid ${tab === v ? 'rgba(79, 140, 255,0.4)' : 'transparent'}`,
                    background: tab === v ? 'rgba(79, 140, 255,0.12)' : 'rgba(255,255,255,0.04)',
                    color: tab === v ? '#4f8cff' : 'var(--text-muted)', fontWeight: tab === v ? 700 : 400,
                  }}>{lbl}</button>
                ))}
              </div>
              {tab === 'terminal' && (
                <button
                  onClick={() => termRef.current?.clear()}
                  style={{ padding: '4px 10px', fontSize: '11px', borderRadius: '6px',
                    background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)',
                    color: 'var(--text-muted)', cursor: 'pointer' }}
                >
                  🗑️ Vider
                </button>
              )}
            </div>

            {/* v2.118 — le terminal reste TOUJOURS monté (masqué en display:none plutôt que
                démonté) tant que la connexion active ne change pas : basculer sur Fichiers/
                Infos ne doit pas couper la session shell interactive en cours. Seul un
                changement de connexion (key={activeConn.id}) force une vraie reconnexion. */}
            <div style={{ flex: 1, overflow: 'hidden', display: tab === 'files' ? 'block' : 'none' }}>
              <SftpBrowser key={activeConn.id} conn={activeConn} />
            </div>
            <div style={{ flex: 1, overflow: 'hidden', display: tab === 'info' ? 'block' : 'none' }}>
              <ServerInfoPanel key={activeConn.id} conn={activeConn} />
            </div>
            <div style={{ flex: 1, display: tab === 'terminal' ? 'flex' : 'none', flexDirection: 'column', overflow: 'hidden' }}>
              {/* Terminal interactif réel (PTY) — identique quelle que soit la cible Windows/Linux */}
              <div style={{ flex: 1, overflow: 'hidden', padding: '10px 4px 4px' }}>
                <XtermSSH key={activeConn.id} ref={termRef} conn={activeConn} />
              </div>

              {/* Raccourcis — insèrent le texte directement dans le shell interactif, comme si tapé au clavier */}
              <div style={{ padding: '0 16px 12px', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '10px' }}>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  {['ls -la', 'pwd', 'df -h', 'free -h', 'top', 'uname -a', 'ps aux --sort=-%cpu | head -8', 'dir', 'Get-Process | Sort CPU -desc | select -First 8'].map(q => (
                    <button key={q} onClick={() => termRef.current?.sendText(q + '\r')}
                      style={{
                        padding: '3px 10px', fontSize: '10px', borderRadius: '6px',
                        background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                        color: 'var(--text-muted)', cursor: 'pointer',
                      }}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
