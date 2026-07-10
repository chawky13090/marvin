'use client';
import { useState, useEffect } from 'react';

const BACKEND = (typeof window!=='undefined'&&window.location?window.location.protocol+'//'+window.location.hostname+':8005':(process.env.NEXT_PUBLIC_BACKEND_URL||'http://127.0.0.1:8005'));

// ── Styles ────────────────────────────────────────────────────────────────────

const card = {
  background: 'var(--bg-glass)',
  border: '1px solid var(--border)',
  borderRadius: '12px',
  padding: '20px 24px',
  marginBottom: '16px',
};

const codeBlock = {
  background: '#0d1117',
  border: '1px solid rgba(228, 228, 231,0.1)',
  borderRadius: '8px',
  padding: '14px 16px',
  fontFamily: 'var(--font-mono, monospace)',
  fontSize: '13px',
  color: '#c9d1d9',
  overflowX: 'auto',
  lineHeight: '1.7',
  position: 'relative',
};

const badge = (color) => ({
  display: 'inline-block',
  padding: '2px 10px',
  borderRadius: '20px',
  fontSize: '11px',
  fontWeight: 700,
  background: `${color}22`,
  color: color,
  border: `1px solid ${color}44`,
  marginRight: '6px',
});

const sectionTitle = {
  fontSize: '16px',
  fontWeight: 700,
  color: 'var(--text-primary)',
  marginBottom: '12px',
  display: 'flex',
  alignItems: 'center',
  gap: '10px',
  borderBottom: '1px solid var(--border)',
  paddingBottom: '10px',
};

function CopyBtn({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      onClick={copy}
      style={{
        position: 'absolute', top: '8px', right: '8px',
        padding: '3px 10px', borderRadius: '6px', border: 'none',
        background: copied ? '#22c55e22' : '#ffffff11',
        color: copied ? '#22c55e' : '#888',
        fontSize: '11px', cursor: 'pointer', transition: 'all 0.2s',
      }}
    >
      {copied ? '✓ Copié' : 'Copier'}
    </button>
  );
}

function Code({ children }) {
  return (
    <div style={{ position: 'relative' }}>
      <pre style={codeBlock}>{children}</pre>
      <CopyBtn text={children} />
    </div>
  );
}

function Step({ num, title, children }) {
  return (
    <div style={{ display: 'flex', gap: '16px', marginBottom: '20px' }}>
      <div style={{
        width: '32px', height: '32px', borderRadius: '50%', flexShrink: 0,
        background: 'linear-gradient(135deg, #4f8cff, #38bdf8)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontWeight: 800, fontSize: '14px', color: '#111',
      }}>
        {num}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '8px', color: 'var(--text-primary)' }}>{title}</div>
        {children}
      </div>
    </div>
  );
}

// ── Health check ─────────────────────────────────────────────────────────────

function HealthPanel() {
  const [health, setHealth] = useState(null);
  const [err, setErr]       = useState(false);

  const check = async () => {
    try {
      const r = await fetch(`${BACKEND}/api/health`, { signal: AbortSignal.timeout(3000) });
      const d = await r.json();
      setHealth(d);
      setErr(false);
    } catch {
      setHealth(null);
      setErr(true);
    }
  };

  useEffect(() => { check(); }, []);

  const statusColor = err ? '#ef4444' : health ? '#22c55e' : '#f59e0b';
  const statusText  = err ? 'Backend hors ligne' : health ? `v${health.version} — ${health.tools_count} outils` : 'Vérification…';

  return (
    <div style={{
      padding: '14px 18px',
      border: `1px solid ${statusColor}44`,
      background: `${statusColor}0a`,
      borderRadius: '10px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: '20px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <span style={{
          width: '10px', height: '10px', borderRadius: '50%',
          background: statusColor,
          boxShadow: `0 0 8px ${statusColor}`,
          display: 'inline-block',
          animation: !health && !err ? 'pulse 1.5s infinite' : 'none',
        }} />
        <span style={{ fontWeight: 600, color: statusColor }}>
          Backend Python : {statusText}
        </span>
        {health?.ollama && (
          <span style={badge('#22c55e')}>Ollama OK</span>
        )}
        {health && !health.ollama && (
          <span style={badge('#ef4444')}>Ollama hors ligne</span>
        )}
      </div>
      <button
        onClick={check}
        style={{
          padding: '5px 14px', borderRadius: '6px', border: '1px solid var(--border)',
          background: 'transparent', color: 'var(--text-secondary)', fontSize: '12px',
          cursor: 'pointer',
        }}
      >
        🔄 Rafraîchir
      </button>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TechniquePage() {
  const [activeSection, setActiveSection] = useState('demarrage');

  const SECTIONS = [
    { id: 'demarrage',    icon: '🚀', label: 'Démarrage rapide'    },
    { id: 'prerequis',   icon: '📋', label: 'Prérequis'           },
    { id: 'installation',icon: '⚙️', label: 'Installation'        },
    { id: 'backend',     icon: '🐍', label: 'Backend Python'      },
    { id: 'frontend',    icon: '⚡', label: 'Frontend Next.js'     },
    { id: 'ollama',      icon: '🤖', label: 'Ollama & Modèles'    },
    { id: 'config',      icon: '🔧', label: 'Configuration'       },
    { id: 'troubleshoot',icon: '🛠️', label: 'Dépannage'           },
  ];

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: 'var(--bg-primary)' }}>
      {/* Sidebar nav */}
      <div style={{
        width: '220px', flexShrink: 0, borderRight: '1px solid var(--border)',
        padding: '20px 12px', overflowY: 'auto',
        background: 'var(--bg-secondary)',
      }}>
        <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '12px', paddingLeft: '8px' }}>
          GUIDE TECHNIQUE
        </div>
        {SECTIONS.map(s => (
          <button
            key={s.id}
            onClick={() => setActiveSection(s.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: '8px', width: '100%',
              padding: '9px 10px', borderRadius: '8px', border: 'none',
              background: activeSection === s.id ? 'rgba(79, 140, 255,0.12)' : 'transparent',
              color: activeSection === s.id ? '#4f8cff' : 'var(--text-secondary)',
              fontSize: '13px', fontWeight: activeSection === s.id ? 600 : 400,
              cursor: 'pointer', textAlign: 'left', marginBottom: '2px',
              transition: 'all 0.15s',
            }}
          >
            {s.icon} {s.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '28px 36px' }}>
        <HealthPanel />

        {/* DÉMARRAGE RAPIDE */}
        {activeSection === 'demarrage' && (
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '6px' }}>🚀 Démarrage rapide</h1>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '14px' }}>
              Démarrez Marvin en 3 commandes depuis le dossier du projet.
            </p>

            <div style={card}>
              <div style={sectionTitle}>
                <span>Terminal 1 — Ollama (LLM local)</span>
                <span style={badge('#8b5cf6')}>GPU optionnel</span>
              </div>
              <Code>{`ollama serve`}</Code>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px', marginBottom: 0 }}>
                Démarre le serveur Ollama sur le port 11434. Doit rester ouvert pendant toute l'utilisation.
              </p>
            </div>

            <div style={card}>
              <div style={sectionTitle}>
                <span>Terminal 2 — Backend Python (FastAPI)</span>
                <span style={badge('#22c55e')}>Port 8005</span>
              </div>
              <Code>{`cd secretary-ai\\backend
.venv\\Scripts\\python -m uvicorn main:app --host 0.0.0.0 --port 8005`}</Code>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px', marginBottom: 0 }}>
                Lance le backend API. ⚠️ Ne pas utiliser <code>--reload</code> : il coupe les streams SSE.
              </p>
            </div>

            <div style={card}>
              <div style={sectionTitle}>
                <span>Terminal 3 — Frontend Next.js</span>
                <span style={badge('#3b82f6')}>Port 3000</span>
              </div>
              <Code>{`cd secretary-ai
npm run dev`}</Code>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px', marginBottom: 0 }}>
                Lance l'interface web. Ouvrir <strong>http://localhost:3000</strong> dans le navigateur.
              </p>
            </div>

            <div style={{ ...card, background: 'rgba(79, 140, 255,0.05)', border: '1px solid rgba(79, 140, 255,0.2)' }}>
              <div style={{ fontWeight: 700, color: '#4f8cff', marginBottom: '10px' }}>💡 Script tout-en-un (PowerShell)</div>
              <Code>{`# Lancer depuis le dossier secretary-ai
Start-Process powershell -ArgumentList "-NoProfile -Command ollama serve"
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoProfile -Command cd backend; .venv\\Scripts\\python -m uvicorn main:app --host 0.0.0.0 --port 8005"
Start-Sleep -Seconds 3
Start-Process powershell -ArgumentList "-NoProfile -Command npm run dev"
Start-Sleep -Seconds 5
Start-Process "http://localhost:3000"`}</Code>
            </div>
          </div>
        )}

        {/* PRÉREQUIS */}
        {activeSection === 'prerequis' && (
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '6px' }}>📋 Prérequis système</h1>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '14px' }}>
              Logiciels à installer avant de commencer.
            </p>

            {[
              {
                icon: '🤖', name: 'Ollama', badge: 'Requis', badgeColor: '#ef4444',
                desc: 'Moteur LLM local. Téléchargez depuis ollama.com',
                install: 'winget install Ollama.Ollama\n# OU téléchargez depuis https://ollama.com',
                note: 'Après installation, vérifiez avec : ollama --version',
              },
              {
                icon: '🐍', name: 'Python 3.11+', badge: 'Requis', badgeColor: '#ef4444',
                desc: 'Runtime Python pour le backend FastAPI.',
                install: 'winget install Python.Python.3.11\n# OU depuis https://python.org',
                note: 'Vérifiez avec : python --version',
              },
              {
                icon: '⚡', name: 'Node.js 20+', badge: 'Requis', badgeColor: '#ef4444',
                desc: 'Runtime JavaScript pour Next.js.',
                install: 'winget install OpenJS.NodeJS\n# OU depuis https://nodejs.org',
                note: 'Vérifiez avec : node --version && npm --version',
              },
              {
                icon: '🎮', name: 'CUDA Toolkit', badge: 'Optionnel (GPU)', badgeColor: '#f59e0b',
                desc: 'Accélération GPU pour la génération vidéo locale (CogVideoX). NVIDIA uniquement.',
                install: '# Depuis https://developer.nvidia.com/cuda-downloads\n# Version recommandée : CUDA 12.x',
                note: 'Vérifiez avec : nvidia-smi',
              },
            ].map(item => (
              <div key={item.name} style={card}>
                <div style={sectionTitle}>
                  <span>{item.icon} {item.name}</span>
                  <span style={badge(item.badgeColor)}>{item.badge}</span>
                </div>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '10px' }}>{item.desc}</p>
                <Code>{item.install}</Code>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px', marginBottom: 0 }}>ℹ️ {item.note}</p>
              </div>
            ))}
          </div>
        )}

        {/* INSTALLATION */}
        {activeSection === 'installation' && (
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '6px' }}>⚙️ Installation complète</h1>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '14px' }}>
              Procédure d'installation étape par étape.
            </p>

            <div style={card}>
              <div style={sectionTitle}>📦 Cloner / ouvrir le projet</div>
              <Step num="1" title="Naviguer dans le dossier du projet">
                <Code>{`cd %USERPROFILE%\\.gemini\\antigravity\\scratch\\secretary-ai\n# OU le chemin complet de votre installation`}</Code>
              </Step>
              <Step num="2" title="Installer les dépendances frontend">
                <Code>{`npm install`}</Code>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>Installe React, Next.js et toutes les bibliothèques JS (~500 Mo).</p>
              </Step>
              <Step num="3" title="Créer et activer l'environnement Python virtuel">
                <Code>{`cd backend
python -m venv .venv
.venv\\Scripts\\activate`}</Code>
              </Step>
              <Step num="4" title="Installer les dépendances Python">
                <Code>{`pip install -r requirements.txt`}</Code>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>Installe FastAPI, Pillow, moviepy, pypdf, openpyxl, etc.</p>
              </Step>
              <Step num="5" title="(Optionnel) Installer les dépendances GPU pour la vidéo locale">
                <Code>{`pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install diffusers transformers accelerate`}</Code>
              </Step>
              <Step num="6" title="Initialiser la base de données SQLite">
                <Code>{`python -c "import database; print('Base OK')"`}</Code>
              </Step>
            </div>
          </div>
        )}

        {/* BACKEND */}
        {activeSection === 'backend' && (
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '6px' }}>🐍 Backend Python</h1>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '14px' }}>
              Le backend est une API FastAPI sur le port <strong>8005</strong>.
            </p>

            <div style={card}>
              <div style={sectionTitle}>Commandes de démarrage</div>
              <Code>{`# Depuis le dossier backend/
cd backend

# Activer l'environnement virtuel
.venv\\Scripts\\activate

# Lancer le serveur (NE PAS utiliser --reload)
python -m uvicorn main:app --host 0.0.0.0 --port 8005

# Mode production avec logging minimal
python -m uvicorn main:app --host 0.0.0.0 --port 8005 --log-level warning`}</Code>
            </div>

            <div style={card}>
              <div style={sectionTitle}>Points d'API principaux</div>
              <div style={{ display: 'grid', gap: '8px', fontSize: '13px' }}>
                {[
                  { method: 'GET',  path: '/api/health',        desc: 'Santé du backend + Ollama' },
                  { method: 'POST', path: '/api/chat',          desc: 'Stream de conversation SSE' },
                  { method: 'POST', path: '/api/tools',         desc: 'Exécution directe d\'un outil' },
                  { method: 'GET',  path: '/api/tools/list',    desc: 'Liste de tous les outils disponibles' },
                  { method: 'GET',  path: '/api/credentials',   desc: 'État des connexions OAuth' },
                  { method: 'GET',  path: '/api/video/models',  desc: 'Modèles vidéo disponibles' },
                  { method: 'POST', path: '/api/video/text-animation', desc: 'Génération vidéo texte animé (gratuit)' },
                  { method: 'POST', path: '/api/video/slideshow', desc: 'Diaporama GIF/MP4 depuis images' },
                ].map(ep => (
                  <div key={ep.path} style={{
                    display: 'flex', gap: '12px', alignItems: 'center',
                    padding: '8px 12px', background: '#0d1117', borderRadius: '6px', border: '1px solid rgba(228, 228, 231,0.08)',
                  }}>
                    <span style={{
                      ...badge(ep.method === 'GET' ? '#22c55e' : '#3b82f6'),
                      minWidth: '46px', textAlign: 'center',
                    }}>
                      {ep.method}
                    </span>
                    <code style={{ color: '#c9d1d9', fontSize: '12px', flex: 1 }}>{ep.path}</code>
                    <span style={{ color: '#888', fontSize: '12px' }}>{ep.desc}</span>
                  </div>
                ))}
              </div>
            </div>

            <div style={card}>
              <div style={sectionTitle}>Structure des fichiers</div>
              <Code>{`backend/
├── main.py           # Application FastAPI + routes API
├── agent.py          # Logique de l'agent IA (streaming SSE)
├── tools.py          # 102 outils (registre + implémentations)
├── database.py       # SQLite : conversations, settings, logs
├── config.py         # Constantes, permissions, modèles
├── video_manager.py  # Génération vidéo (slideshow, texte animé)
├── local_video.py    # Génération vidéo IA locale (CogVideoX)
├── credentials_manager.py  # Gestion OAuth Google/Microsoft
├── requirements.txt  # Dépendances Python
└── .venv/            # Environnement virtuel Python`}</Code>
            </div>
          </div>
        )}

        {/* FRONTEND */}
        {activeSection === 'frontend' && (
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '6px' }}>⚡ Frontend Next.js</h1>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '14px' }}>
              Interface web React sur le port <strong>3000</strong>.
            </p>

            <div style={card}>
              <div style={sectionTitle}>Commandes utiles</div>
              <Code>{`# Depuis la racine du projet (secretary-ai/)
npm run dev          # Développement avec hot-reload (Turbopack)
npm run build        # Build de production
npm run start        # Serveur de production (après build)
npm run lint         # Vérification ESLint`}</Code>
            </div>

            <div style={card}>
              <div style={sectionTitle}>Variables d'environnement</div>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '10px' }}>
                Fichier <code>.env.local</code> à la racine du projet :
              </p>
              <Code>{`# URL du backend Python
NEXT_PUBLIC_BACKEND_URL=http://localhost:8005

# Optionnel : désactiver la télémétrie Next.js
NEXT_TELEMETRY_DISABLED=1`}</Code>
            </div>

            <div style={card}>
              <div style={sectionTitle}>Structure des pages</div>
              <Code>{`app/
├── page.js           # Redirection vers /chat
├── layout.js         # Layout global + navigation
├── globals.css       # Variables CSS + styles globaux
├── technique/        # 📍 Cette page
├── video/            # Génération vidéo IA
├── outils/           # 100+ outils Marvin
├── agents/           # Agents autonomes
├── workflows/        # Automatisation multi-étapes
├── cron/             # Tâches planifiées
├── calendar/         # Agenda Google
├── emails/           # Boîte mail
├── files/            # Explorateur de fichiers
├── tasks/            # Tâches & notes
├── monitoring/       # Surveillance système
└── settings/         # Paramètres & connexions`}</Code>
            </div>
          </div>
        )}

        {/* OLLAMA */}
        {activeSection === 'ollama' && (
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '6px' }}>🤖 Ollama & Modèles IA</h1>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '14px' }}>
              Marvin utilise Ollama pour les LLMs locaux. Voici les modèles recommandés.
            </p>

            <div style={card}>
              <div style={sectionTitle}>Démarrer Ollama</div>
              <Code>{`# Démarrer le serveur Ollama
ollama serve

# Lister les modèles installés
ollama list

# Télécharger un modèle
ollama pull qwen2.5:14b

# Tester un modèle
ollama run qwen2.5:7b "Bonjour, comment vas-tu ?"`}</Code>
            </div>

            <div style={card}>
              <div style={sectionTitle}>Modèles recommandés</div>
              <div style={{ display: 'grid', gap: '10px' }}>
                {[
                  { name: 'qwen2.5:14b', badge: '⭐ Recommandé', color: '#4f8cff', ram: '10 Go RAM', desc: 'Meilleur équilibre qualité/performance. Excellent pour le tool calling.' },
                  { name: 'qwen2.5:7b',  badge: '⚡ Rapide',      color: '#22c55e', ram: '6 Go RAM',  desc: 'Bon pour les machines avec peu de RAM. Rapide, qualité correcte.' },
                  { name: 'qwen3:8b',    badge: '🆕 Nouveau',     color: '#3b82f6', ram: '6 Go RAM',  desc: 'Dernière génération Qwen. Très bonnes capacités de raisonnement.' },
                  { name: 'llava-phi3',  badge: '👁️ Vision',     color: '#8b5cf6', ram: '8 Go RAM',  desc: 'Modèle multimodal. Analyse d\'images et OCR visuel.' },
                ].map(m => (
                  <div key={m.name} style={{
                    padding: '12px 14px', background: '#0d1117', borderRadius: '8px',
                    border: `1px solid ${m.color}33`,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
                      <code style={{ color: '#c9d1d9', fontWeight: 700 }}>{m.name}</code>
                      <span style={badge(m.color)}>{m.badge}</span>
                      <span style={{ fontSize: '11px', color: '#666', marginLeft: 'auto' }}>{m.ram}</span>
                    </div>
                    <div style={{ fontSize: '12px', color: '#888' }}>{m.desc}</div>
                    <Code>{`ollama pull ${m.name}`}</Code>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* CONFIGURATION */}
        {activeSection === 'config' && (
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '6px' }}>🔧 Configuration</h1>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '14px' }}>
              Personnalisation avancée de Marvin.
            </p>

            <div style={card}>
              <div style={sectionTitle}>Fichier backend/config.py</div>
              <Code>{`# Port du backend (défaut : 8005)
BACKEND_PORT = 8005

# URL Ollama (défaut : localhost:11434)
OLLAMA_URL = "http://localhost:11434"

# URL du frontend
FRONTEND_URL = "http://localhost:3000"

# Modèle par défaut
DEFAULT_MODEL = "qwen2.5:14b"

# Niveaux de permission
# 1 = Sécurisé (lecture seule)
# 2 = Standard (confirmation pour les actions dangereuses)
# 3 = Expert  (tout auto-confirmé)
DEFAULT_PERMISSION_LEVEL = 2`}</Code>
            </div>

            <div style={card}>
              <div style={sectionTitle}>Connexions OAuth (Paramètres → Connexions)</div>
              <div style={{ display: 'grid', gap: '10px', fontSize: '13px' }}>
                {[
                  { name: 'Google', desc: 'Gmail + Google Drive + Google Calendar', required: 'Pour emails, agenda et Drive' },
                  { name: 'Microsoft', desc: 'Outlook + OneDrive', required: 'Pour emails Microsoft et OneDrive' },
                  { name: 'Replicate', desc: 'Génération vidéo cloud (IA)', required: 'Pour Text/Image → Vidéo cloud' },
                ].map(c => (
                  <div key={c.name} style={{
                    padding: '12px 14px', background: '#0d1117', borderRadius: '8px',
                    border: '1px solid rgba(228, 228, 231,0.08)',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  }}>
                    <div>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '3px' }}>{c.name}</div>
                      <div style={{ fontSize: '12px', color: '#888' }}>{c.desc}</div>
                    </div>
                    <span style={badge('#f59e0b')}>{c.required}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* DÉPANNAGE */}
        {activeSection === 'troubleshoot' && (
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '6px' }}>🛠️ Dépannage</h1>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '14px' }}>
              Solutions aux problèmes courants.
            </p>

            {[
              {
                problem: 'Le backend ne démarre pas',
                solution: `# Vérifier que Python est installé
python --version

# Vérifier que le venv est activé
.venv\\Scripts\\activate

# Réinstaller les dépendances
pip install -r requirements.txt

# Lancer avec log complet pour voir l'erreur
python -m uvicorn main:app --port 8005 --log-level debug`,
              },
              {
                problem: 'Ollama ne répond pas',
                solution: `# Vérifier qu'Ollama est démarré
ollama serve

# Tester la connectivité
curl http://localhost:11434/api/tags

# Vérifier qu'un modèle est téléchargé
ollama list

# Télécharger le modèle recommandé
ollama pull qwen2.5:7b`,
              },
              {
                problem: 'PowerShell bloqué par l\'antivirus',
                solution: `# Solution 1 : Ajouter le dossier backend à la liste blanche
# de votre antivirus (Windows Defender, Avast, etc.)

# Solution 2 : Le backend utilise automatiquement
# l'encodage Base64 et CREATE_NO_WINDOW pour éviter
# les faux positifs. Aucune action manuelle requise.

# Solution 3 : Si le problème persiste, utilisez
# l'outil 'Commande Shell' plutôt que PowerShell`,
              },
              {
                problem: 'Génération vidéo échoue (Replicate)',
                solution: `# Sans clé API Replicate → utilisez l'onglet "Texte Animé"
# (100% gratuit, sans GPU ni clé API)

# Avec clé API : configurez dans Paramètres → Connexions
# Créez un compte sur https://replicate.com
# Copiez votre token API et collez-le dans les paramètres`,
              },
              {
                problem: 'Le frontend ne charge pas',
                solution: `# Vérifier que Node.js est installé
node --version

# Réinstaller les modules
npm install

# Effacer le cache Next.js
rm -rf .next
npm run dev`,
              },
              {
                problem: 'Port 8005 déjà utilisé',
                solution: `# Windows PowerShell : trouver et tuer le processus
$p = (Get-NetTCPConnection -LocalPort 8005 -EA SilentlyContinue).OwningProcess
if ($p) { Stop-Process -Id $p -Force; Write-Host "Process $p killed" }

# Ou changer le port dans backend/config.py : BACKEND_PORT = 8006
# Et dans .env.local : NEXT_PUBLIC_BACKEND_URL=http://localhost:8006`,
              },
            ].map(item => (
              <div key={item.problem} style={card}>
                <div style={{
                  fontWeight: 700, fontSize: '14px', color: '#ef4444',
                  marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px',
                }}>
                  ⚠️ {item.problem}
                </div>
                <Code>{item.solution}</Code>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
