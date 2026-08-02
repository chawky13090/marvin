'use client';
import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';

import { BACKEND_URL } from '@/lib/backend';
import { CredentialGroup } from '@/components/settings/CredentialGroup';
import { ModelSettingsPanel } from '@/components/settings/ModelSettingsPanel';

// ── Définition des 3 niveaux de permission ────────────────────────────────────
const PERMISSION_LEVELS = {
  1: {
    id: 1,
    icon: '🛡️',
    name: 'Sécurisé',
    tagline: 'Lecture seule',
    color: '#10b981',
    colorDim: 'rgba(16,185,129,0.12)',
    border: '#10b981',
    allowed: [
      '📂 Parcourir les dossiers',
      '📖 Lire les fichiers (PDF, Word, TXT)',
      '✅ Gérer tâches & notes',
      '🧠 Mémoire personnelle',
      '💻 Informations système',
      '🔍 Recherche sémantique',
    ],
    blocked: [
      '✏️ Modifier / créer des fichiers',
      '🗑️ Supprimer des fichiers',
      '📦 Déplacer / renommer',
      '⚙️ Exécuter des commandes',
      '🔄 Contrôle des processus',
    ],
    warning: null,
  },
  2: {
    id: 2,
    icon: '⚡',
    name: 'Standard',
    tagline: 'Recommandé',
    color: '#f59e0b',
    colorDim: 'rgba(245,158,11,0.12)',
    border: '#f59e0b',
    allowed: [
      '📂 Tout ce qui est Sécurisé',
      '✏️ Créer & modifier des fichiers',
      '📄 Créer des documents Word / PDF',
      '📦 Déplacer, renommer',
      '⚙️ Commandes système (avec confirmation)',
      '🗑️ Supprimer (avec confirmation)',
    ],
    blocked: [
      '⚡ Actions sans confirmation',
    ],
    warning: null,
  },
  3: {
    id: 3,
    icon: '🔓',
    name: 'Expert',
    tagline: 'Capacités étendues',
    color: '#8b5cf6',
    colorDim: 'rgba(139,92,246,0.12)',
    border: '#8b5cf6',
    allowed: [
      '🔓 Toutes les permissions',
      '🧰 Accès aux outils système avancés',
      '🗑️ Suppression après autorisation',
      '⚙️ Commandes système après autorisation',
      '🔄 Tuer des processus',
      '📋 Modifier le presse-papiers',
    ],
    blocked: [],
    warning: 'Les permissions définissent les outils accessibles. Le niveau d’autonomie, visible dans la barre de chat, décide séparément si une confirmation est requise.',
  },
};

// ── Onglets de la page Paramètres ─────────────────────────────────────────────
const TABS = [
  { id: 'permissions', label: '🔐 Permissions', icon: '🔐' },
  { id: 'model', label: '🧠 Modèle IA', icon: '🧠' },
  { id: 'memory', label: '🧠 Mémoire', icon: '💾' },
  { id: 'connections', label: '🔗 Connexions', icon: '🔗' },
  { id: 'about', label: 'ℹ️ À propos', icon: 'ℹ️' },
];

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState('permissions');
  const [status, setStatus] = useState(null);
  const [autoConfig, setAutoConfig] = useState(null);
  const [portfolioPolicy, setPortfolioPolicy] = useState(null);
  const [portfolioSaving, setPortfolioSaving] = useState(false);
  const [ollamaUrl, setOllamaUrl] = useState('http://127.0.0.1:11434');
  const [savedMsg, setSavedMsg] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [pullModelName, setPullModelName] = useState('');
  const [isPulling, setIsPulling] = useState(false);

  // Ollama Cloud (v2.119) — routage local/cloud par sensibilité, jamais par profil entier
  const [cloudEnabled, setCloudEnabled] = useState(false);
  const [cloudOverrides, setCloudOverrides] = useState({});
  const [cloudSaving, setCloudSaving] = useState(false);
  const [localOnlyLockdown, setLocalOnlyLockdown] = useState(false);   // v2.120 — Hyper sécurisé
  const [ultraUnrestricted, setUltraUnrestricted] = useState(false);   // v2.121 — Ultra débridé
  const [privacyPreset, setPrivacyPreset] = useState('normal');
  const [presetApplying, setPresetApplying] = useState(false);

  // Permission
  const [permissionLevel, setPermissionLevel] = useState(2);
  const [permSaving, setPermSaving] = useState(false);

  // Mémoire
  const [memories, setMemories] = useState([]);
  const [newMemoryContent, setNewMemoryContent] = useState('');
  const [newMemoryCategory, setNewMemoryCategory] = useState('fact');

  // Connexions / Credentials
  const [credentials, setCredentials] = useState({});
  const [credGroups, setCredGroups] = useState({});
  const [credValues, setCredValues] = useState({});    // champs en cours d'édition
  const [credSaving, setCredSaving] = useState({});    // loading par clé
  const [credVisible, setCredVisible] = useState({});  // afficher/masquer
  const [lanAccess, setLanAccess] = useState(null);

  // v2.174 — Identité document par défaut (auteur/organisation/en-tête/pied de page),
  // réutilisée automatiquement par Marvin pour tout document généré (PDF/Word) sans avoir
  // à la redemander à chaque fois.
  const [docIdentity, setDocIdentity] = useState({
    author: '', org: '', address: '', phone: '', email: '', website: '',
    logo: '', footer_text: '', confidentiality: '',
  });
  const [docIdentitySaving, setDocIdentitySaving] = useState(false);

  async function fetchDocIdentity() {
    try {
      const res = await fetch(`${BACKEND_URL}/api/settings/document_identity`);
      const data = await res.json();
      if (data.value && typeof data.value === 'object') {
        setDocIdentity(v => ({ ...v, ...data.value }));
      }
    } catch { }
  }

  async function handleSaveDocIdentity() {
    setDocIdentitySaving(true);
    try {
      await fetch(`${BACKEND_URL}/api/settings/document_identity`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: docIdentity }),
      });
      showNotification('✅ Identité document enregistrée');
    } catch (err) {
      showNotification(`❌ Erreur : ${err.message}`);
    } finally {
      setDocIdentitySaving(false);
    }
  }

  async function regenerateLanPairingCode() {
    try {
      const response = await fetch(`${BACKEND_URL}/api/auth/lan/pairing-code`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error('pairing_code_refused');
      const generated = await response.json();
      setLanAccess(current => ({
        ...(current || {}),
        pairing_code: generated.pairing_code,
        pairing_expires_in_seconds: generated.expires_in_seconds,
      }));
      showNotification('Code de jumelage renouvelé pour cinq minutes');
    } catch {
      showNotification('Impossible de renouveler le code depuis cet appareil');
    }
  }

  useEffect(() => {
    fetchStatus();
    fetchAutoConfig();
    fetchMemories();
    fetchPermissionLevel();
    fetchCredentials();
    fetchCloudConfig();
    fetchDocIdentity();
    fetch(`${BACKEND_URL}/api/auth/lan/status`, { cache: 'no-store' })
      .then(response => response.json())
      .then(setLanAccess)
      .catch(() => {});
    // Lire tab depuis l'URL (callback OAuth)
    const tab = searchParams?.get('tab');
    if (tab) setActiveTab(tab);
    const google = searchParams?.get('google');
    const microsoft = searchParams?.get('microsoft');
    if (google === 'connected') showNotification('✅ Google connecté avec succès !');
    if (microsoft === 'connected') showNotification('✅ Microsoft connecté avec succès !');
    // Chargement initial uniquement; les callbacks OAuth mettent à jour l'URL via navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Permission Level ────────────────────────────────────────────────────────

  async function fetchPermissionLevel() {
    try {
      const res = await fetch(`${BACKEND_URL}/api/settings/permission_level`);
      const data = await res.json();
      if (data.value !== null && data.value !== undefined) {
        setPermissionLevel(parseInt(data.value) || 2);
      }
    } catch { }
  }

  async function handleSetPermissionLevel(level) {
    if (level === permissionLevel) return;
    setPermSaving(true);
    try {
      await fetch(`${BACKEND_URL}/api/settings/permission_level`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: level }),
      });
      setPermissionLevel(level);
      showNotification(`${PERMISSION_LEVELS[level].icon} Niveau activé : ${PERMISSION_LEVELS[level].name}`);
    } catch (err) {
      showNotification(`❌ Erreur: ${err.message}`);
    } finally {
      setPermSaving(false);
    }
  }

  // ── Credentials ─────────────────────────────────────────────────────────────

  async function fetchCredentials() {
    try {
      const res = await fetch(`${BACKEND_URL}/api/credentials`);
      const data = await res.json();
      setCredentials(data.credentials || {});
      setCredGroups(data.groups || {});
    } catch { }
  }

  async function handleSaveCredential(name) {
    const value = credValues[name];
    if (value === undefined) return;
    setCredSaving(s => ({ ...s, [name]: true }));
    try {
      await fetch(`${BACKEND_URL}/api/credentials/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      });
      showNotification(`✅ ${name} enregistré`);
      setCredValues(v => { const n = { ...v }; delete n[name]; return n; });
      fetchCredentials();
    } catch (err) {
      showNotification(`❌ Erreur : ${err.message}`);
    } finally {
      setCredSaving(s => ({ ...s, [name]: false }));
    }
  }

  async function handleDeleteCredential(name) {
    if (!confirm(`Supprimer la clé "${name}" ?`)) return;
    await fetch(`${BACKEND_URL}/api/credentials/${name}`, { method: 'DELETE' });
    showNotification(`🗑️ ${name} supprimé`);
    fetchCredentials();
  }

  async function handleGoogleOAuth() {
    try {
      const res = await fetch(`${BACKEND_URL}/api/oauth/google/start`);
      const data = await res.json();
      if (data.auth_url) window.location.href = data.auth_url;
      else showNotification('❌ ' + (data.detail || 'Erreur OAuth Google'));
    } catch (err) { showNotification(`❌ ${err.message}`); }
  }

  async function handleMicrosoftOAuth() {
    try {
      const res = await fetch(`${BACKEND_URL}/api/oauth/microsoft/start`);
      const data = await res.json();
      if (data.auth_url) window.location.href = data.auth_url;
      else showNotification('❌ ' + (data.detail || 'Erreur OAuth Microsoft'));
    } catch (err) { showNotification(`❌ ${err.message}`); }
  }

  // ── Mémoires ────────────────────────────────────────────────────────────────

  async function fetchMemories() {
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'get_memories' })
      });
      const data = await res.json();
      if (data.success) setMemories(data.memories || []);
    } catch { }
  }

  async function handleAddMemory(e) {
    if (e) e.preventDefault();
    if (!newMemoryContent.trim()) return;
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'create_memory', content: newMemoryContent.trim(), category: newMemoryCategory })
      });
      const data = await res.json();
      if (data.success) { setNewMemoryContent(''); showNotification('🧠 Nouveau fait mémorisé !'); fetchMemories(); }
    } catch (err) { showNotification(`❌ Erreur : ${err.message}`); }
  }

  async function handleDeleteMemory(id) {
    if (!confirm('Oublier ce souvenir ?')) return;
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'delete_memory', id })
      });
      const data = await res.json();
      if (data.success) { showNotification('🧠 Souvenir oublié !'); fetchMemories(); }
    } catch (err) { showNotification(`❌ Erreur : ${err.message}`); }
  }

  async function handleClearAllMemories() {
    if (!confirm('Effacer TOUT ce que Marvin a appris sur vous ? Cette action est irréversible !')) return;
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'clear_memories' })
      });
      const data = await res.json();
      if (data.success) { showNotification('🧠 Mémoire entièrement réinitialisée !'); fetchMemories(); }
    } catch (err) { showNotification(`❌ Erreur : ${err.message}`); }
  }

  // ── Modèle ──────────────────────────────────────────────────────────────────

  async function fetchStatus() {
    try {
      const res = await fetch('/api/status?t=' + Date.now());
      const data = await res.json();
      setStatus(data);
      if (data?.ollama?.selectedModel) setSelectedModel(data.ollama.selectedModel);
      else if (data?.ollama?.model) setSelectedModel(data.ollama.model);
    } catch { }
  }

  async function fetchAutoConfig() {
    try {
      const [res, policyRes] = await Promise.all([
        fetch(`${BACKEND_URL}/api/auto-config`, { cache: 'no-store' }),
        fetch(`${BACKEND_URL}/api/auto-config/models/policy`, { cache: 'no-store' }),
      ]);
      const data = await res.json();
      setAutoConfig(data);
      if (policyRes.ok) setPortfolioPolicy(await policyRes.json());
      const first = (data?.recommended_to_install || [])[0];
      if (first) setPullModelName(current => current || first);
    } catch { }
  }

  async function savePortfolioPolicy(next) {
    const current = portfolioPolicy?.policy || {};
    setPortfolioSaving(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/auto-config/models/policy`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: true,
          auto_download: Boolean(next.auto_download),
          download_network: next.download_network || 'unmetered',
          max_disk_gb: Number(next.max_disk_gb || 25),
          min_free_disk_gb: Number(next.min_free_disk_gb || 10),
          maintained_roles: next.maintained_roles || current.maintained_roles || [],
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Politique locale refusée');
      setPortfolioPolicy(data);
      showNotification(data.download ? 'Portefeuille autonome activé, téléchargement contrôlé planifié.' : 'Politique du portefeuille local enregistrée.');
      await fetchAutoConfig();
    } catch (err) {
      showNotification(`Erreur : ${err.message}`);
    } finally {
      setPortfolioSaving(false);
    }
  }

  // ── Ollama Cloud ──────────────────────────────────────────────────────────
  async function fetchCloudConfig() {
    try {
      const [r1, r2, r3, r4, r5] = await Promise.all([
        fetch(`${BACKEND_URL}/api/settings/cloud_enabled`),
        fetch(`${BACKEND_URL}/api/settings/cloud_overrides`),
        fetch(`${BACKEND_URL}/api/settings/local_only_lockdown`),
        fetch(`${BACKEND_URL}/api/settings/ultra_unrestricted`),
        fetch(`${BACKEND_URL}/api/settings/privacy_preset`),
      ]);
      const d1 = await r1.json(), d2 = await r2.json(), d3 = await r3.json(), d4 = await r4.json(), d5 = await r5.json();
      setCloudEnabled(!!d1.value);
      setCloudOverrides((d2.value && typeof d2.value === 'object') ? d2.value : {});
      setLocalOnlyLockdown(!!d3.value);
      setUltraUnrestricted(!!d4.value);
      setPrivacyPreset(['normal', 'hyper', 'cloud_max', 'ultra'].includes(d5.value) ? d5.value : 'normal');
    } catch { }
  }

  async function saveCloudEnabled(value) {
    setCloudEnabled(value);
    setCloudSaving(true);
    try {
      await fetch(`${BACKEND_URL}/api/settings/cloud_enabled`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      });
      showNotification(value ? '☁️ Ollama Cloud activé' : '☁️ Ollama Cloud désactivé');
    } catch (err) { showNotification(`❌ Erreur: ${err.message}`); }
    setCloudSaving(false);
  }

  // v2.120-121 — 4 préréglages globaux. Le garde-fou système (security.py, commandes
  // catastrophiques) reste actif dans LES QUATRE modes SANS EXCEPTION — jamais désactivable
  // depuis cette page, quel que soit le préréglage. Seul le mode Ultra débridé (v2.121)
  // désactive le garde-fou de SENSIBILITÉ (emails/SSH/mots de passe peuvent partir au
  // cloud) — un choix de confidentialité, pas de sécurité système — et exige une
  // confirmation explicite avant d'être activé (effet non réversible sur les données déjà
  // envoyées). Chaque preset écrit simplement les réglages existants (cloud_enabled/
  // cloud_overrides/local_only_lockdown/ultra_unrestricted), aucun nouveau mécanisme lourd.
  async function applyPreset(preset) {
    if (preset === 'ultra' && !ultraUnrestricted) {
      const ok = window.confirm(
        "⚠️ Mode Ultra débridé\n\n" +
        "Ce mode envoie TOUTES vos données au cloud, y compris les emails, mots de passe, " +
        "connexions SSH et factures — sans aucune exception. Une fois envoyée, une donnée " +
        "ne peut pas être rappelée.\n\n" +
        "Le garde-fou système contre les commandes destructrices (formatage disque, " +
        "suppression système…) reste actif — ce mode ne concerne QUE le routage cloud/local.\n\n" +
        "Confirmer l'activation ?"
      );
      if (!ok) return;
    }
    setPresetApplying(true);
    try {
      // v2.243 — une route transactionnelle applique l'ensemble du contrat. L'ancienne
      // rafale de quatre PUT pouvait laisser un état partiel après une erreur réseau.
      const presetResponse = await fetch(`${BACKEND_URL}/api/settings/privacy-preset`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preset }),
      });
      const presetState = await presetResponse.json();
      if (!presetResponse.ok) throw new Error(presetState.detail || 'Application du mode impossible');
      setLocalOnlyLockdown(Boolean(presetState.local_only_lockdown));
      setCloudEnabled(Boolean(presetState.cloud_enabled));
      setCloudOverrides(presetState.cloud_overrides || {});
      setUltraUnrestricted(Boolean(presetState.ultra_unrestricted));
      setPrivacyPreset(presetState.privacy_preset || preset);
      showNotification(
        preset === 'normal' ? '🛡️ Mode Normal appliqué' :
        preset === 'hyper' ? '🔒 Mode Hyper sécurisé appliqué — cloud totalement verrouillé' :
        preset === 'ultra' ? '☠️ Mode Ultra débridé appliqué — plus aucune exception de sensibilité' :
        '☁️ Mode Tout cloud appliqué'
      );
    } catch (err) { showNotification(`❌ Erreur: ${err.message}`); }
    setPresetApplying(false);
  }

  async function setCloudModelForProfile(profile, modelName) {
    const next = { ...cloudOverrides };
    if (modelName) next[profile] = modelName; else delete next[profile];
    setCloudOverrides(next);
    setCloudSaving(true);
    try {
      await fetch(`${BACKEND_URL}/api/settings/cloud_overrides`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: next }),
      });
      showNotification(`☁️ Profil « ${profile} » → ${modelName || 'local (retiré)'}`);
    } catch (err) { showNotification(`❌ Erreur: ${err.message}`); }
    setCloudSaving(false);
  }

  async function handleSetModel(modelName) {
    setSelectedModel(modelName);
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'set_model', modelName })
      });
      const data = await res.json();
      if (data.success) { showNotification(`✅ Modèle actif : ${modelName}`); fetchStatus(); }
    } catch (err) { showNotification(`❌ Erreur: ${err.message}`); }
  }

  async function handlePullModel() {
    if (!pullModelName.trim()) return;
    setIsPulling(true);
    showNotification(`⏳ Téléchargement de ${pullModelName} lancé...`);
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'pull_model', modelName: pullModelName })
      });
      const data = await res.json();
      if (data.success) showNotification(`📥 Téléchargement en cours pour : ${pullModelName}.`);
    } catch (err) { showNotification(`❌ Erreur: ${err.message}`); }
    finally { setIsPulling(false); }
  }

  function showNotification(msg) {
    setSavedMsg(msg);
    setTimeout(() => setSavedMsg(''), 5000);
  }

  const models = status?.ollama?.models || [];
  const recommendedModels = Object.values(autoConfig?.portfolio || {}).reduce((items, item) => {
    if (!item?.recommended || items.some(existing => existing.name === item.recommended)) return items;
    const plan = (autoConfig?.download_plan || []).find(entry => entry.model === item.recommended);
    items.push({
      name: item.recommended,
      size: plan?.size_bytes ? `${(plan.size_bytes / (1024 ** 3)).toFixed(1)} Go` : 'taille mesurée après installation',
      speed: 'Adapté au matériel détecté',
      note: `Rôle : ${item.role || 'général'}`,
    });
    return items;
  }, []);

  const currentPerm = PERMISSION_LEVELS[permissionLevel] || PERMISSION_LEVELS[2];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* ── En-tête ─────────────────────────────────────────────────────────── */}
      <div className="page-header">
        <h1>⚙️ Paramètres</h1>
        {savedMsg && (
          <div style={{
            padding: '8px 16px', borderRadius: '8px', fontSize: 'var(--font-sm)',
            background: savedMsg.includes('❌') ? 'var(--danger-bg)' : 'var(--success-bg)',
            color: savedMsg.includes('❌') ? 'var(--danger)' : 'var(--success)',
            animation: 'slideIn 0.3s ease', fontWeight: 600,
          }}>
            {savedMsg}
          </div>
        )}
      </div>

      {/* ── Onglets ─────────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', gap: '2px', padding: '0 24px',
        borderBottom: '1px solid var(--border)',
        overflowX: 'auto',
      }}>
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '12px 18px',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === tab.id ? '2px solid var(--accent-primary)' : '2px solid transparent',
              color: activeTab === tab.id ? 'var(--accent-primary)' : 'var(--text-secondary)',
              fontWeight: activeTab === tab.id ? 700 : 500,
              cursor: 'pointer',
              fontSize: 'var(--font-sm)',
              whiteSpace: 'nowrap',
              transition: 'all 0.2s',
              marginBottom: '-1px',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Corps ───────────────────────────────────────────────────────────── */}
      <div className="page-body" style={{ maxWidth: '850px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>

          {/* ═══════════════════════════════════════════════════════════════════
              ONGLET : PERMISSIONS
              ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === 'permissions' && (
            <>
              {/* Statut actuel */}
              <div className="card" style={{
                borderLeft: `4px solid ${currentPerm.color}`,
                background: `linear-gradient(135deg, ${currentPerm.colorDim}, transparent)`,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <span style={{ fontSize: '2.5rem' }}>{currentPerm.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '2px' }}>
                      Niveau de permission actif
                    </div>
                    <div style={{
                      fontSize: '1.4rem', fontWeight: 800,
                      color: currentPerm.color,
                    }}>
                      Niveau {permissionLevel} — {currentPerm.name}
                    </div>
                    <div style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      {currentPerm.tagline}
                    </div>
                  </div>
                  <div style={{
                    padding: '6px 14px', borderRadius: '20px',
                    background: currentPerm.colorDim,
                    border: `1px solid ${currentPerm.color}`,
                    color: currentPerm.color, fontWeight: 700, fontSize: '12px',
                  }}>
                    ACTIF
                  </div>
                </div>
              </div>

              {/* Sélecteur de niveau */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
                {[1, 2, 3].map(level => {
                  const perm = PERMISSION_LEVELS[level];
                  const isActive = permissionLevel === level;
                  return (
                    <button
                      key={level}
                      onClick={() => handleSetPermissionLevel(level)}
                      disabled={permSaving}
                      style={{
                        display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                        padding: '20px', borderRadius: 'var(--radius-lg)',
                        border: `2px solid ${isActive ? perm.color : 'var(--border)'}`,
                        background: isActive ? perm.colorDim : 'var(--bg-secondary)',
                        cursor: permSaving ? 'wait' : 'pointer',
                        textAlign: 'left', transition: 'all 0.25s',
                        boxShadow: isActive ? `0 0 20px ${perm.colorDim}` : 'none',
                        transform: isActive ? 'translateY(-2px)' : 'none',
                        opacity: permSaving ? 0.7 : 1,
                        position: 'relative', overflow: 'hidden',
                      }}
                    >
                      {/* Badge ACTIF */}
                      {isActive && (
                        <div style={{
                          position: 'absolute', top: '10px', right: '10px',
                          padding: '2px 8px', borderRadius: '10px',
                          background: perm.color, color: 'white',
                          fontSize: '10px', fontWeight: 800,
                        }}>
                          ACTIF
                        </div>
                      )}

                      {/* Icône + titre */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                        <span style={{ fontSize: '2rem' }}>{perm.icon}</span>
                        <div>
                          <div style={{
                            fontWeight: 800, fontSize: 'var(--font-md)',
                            color: isActive ? perm.color : 'var(--text-primary)',
                          }}>
                            {perm.name}
                          </div>
                          <div style={{
                            fontSize: '11px', fontWeight: 600,
                            color: isActive ? perm.color : 'var(--text-muted)',
                            opacity: isActive ? 0.9 : 0.7,
                          }}>
                            Niveau {level} • {perm.tagline}
                          </div>
                        </div>
                      </div>

                      {/* Ce qui est autorisé */}
                      <div style={{ width: '100%', marginBottom: perm.blocked.length > 0 ? '10px' : 0 }}>
                        <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                          Autorisé
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          {perm.allowed.map((item, i) => (
                            <div key={i} style={{ fontSize: '12px', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <span style={{ color: '#10b981', fontWeight: 700 }}>✓</span> {item}
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Ce qui est bloqué */}
                      {perm.blocked.length > 0 && (
                        <div style={{ width: '100%' }}>
                          <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            Bloqué
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            {perm.blocked.map((item, i) => (
                              <div key={i} style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <span style={{ color: '#ef4444', fontWeight: 700 }}>✗</span> {item}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Avertissement niveau Expert */}
                      {perm.warning && (
                        <div style={{
                          marginTop: '12px', padding: '8px 10px',
                          background: 'rgba(239,68,68,0.08)', borderRadius: '8px',
                          border: '1px solid rgba(239,68,68,0.25)',
                          fontSize: '11px', color: '#ef4444', lineHeight: 1.5,
                          width: '100%',
                        }}>
                          {perm.warning}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>

              {/* Info sur la persistance */}
              <div style={{
                padding: '12px 16px', background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)', border: '1px solid var(--border)',
                fontSize: 'var(--font-xs)', color: 'var(--text-muted)', lineHeight: 1.6,
              }}>
                💡 Le niveau de permission est appliqué immédiatement pour toutes les nouvelles conversations.
                Il contrôle ce que l&apos;IA peut exécuter sur votre PC — pas seulement ce qu&apos;elle peut suggérer.
              </div>
            </>
          )}

          <ModelSettingsPanel
            activeTab={activeTab}
            status={status}
            models={models}
            recommendedModels={recommendedModels}
            selectedModel={selectedModel}
            handleSetModel={handleSetModel}
            pullModelName={pullModelName}
            setPullModelName={setPullModelName}
            isPulling={isPulling}
            handlePullModel={handlePullModel}
            ollamaUrl={ollamaUrl}
            autoConfig={autoConfig}
            portfolioPolicy={portfolioPolicy}
            savePortfolioPolicy={savePortfolioPolicy}
            portfolioSaving={portfolioSaving}
            cloudEnabled={cloudEnabled}
            localOnlyLockdown={localOnlyLockdown}
            ultraUnrestricted={ultraUnrestricted}
            privacyPreset={privacyPreset}
            presetApplying={presetApplying}
            applyPreset={applyPreset}
            cloudOverrides={cloudOverrides}
            setCloudModelForProfile={setCloudModelForProfile}
            cloudSaving={cloudSaving}
          />

          {/* ═══════════════════════════════════════════════════════════════════
              ONGLET : MÉMOIRE
              ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === 'memory' && (
            <div className="card" style={{ borderLeft: '4px solid var(--accent-secondary)' }}>
              <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>🧠 Mémoire personnelle &amp; Profil</span>
                {memories.length > 0 && (
                  <button onClick={handleClearAllMemories} style={{
                    background: 'none', border: '1px solid var(--danger)',
                    borderRadius: '4px', color: 'var(--danger)',
                    padding: '2px 8px', fontSize: '10px', cursor: 'pointer',
                    fontWeight: 600, transition: 'all 0.2s',
                  }}>
                    Tout effacer
                  </button>
                )}
              </div>
              <p style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: '16px' }}>
                Marvin apprend de vos échanges. Voici les faits, préférences et informations mémorisés pour s&apos;adapter à votre façon de travailler.
              </p>
              <form onSubmit={handleAddMemory} style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
                <input className="input" value={newMemoryContent} onChange={e => setNewMemoryContent(e.target.value)}
                  placeholder="Fait à retenir (ex: Je m'appelle Abdou, J'aime travailler sur le Bureau...)"
                  style={{ flex: 1, fontSize: 'var(--font-sm)' }} />
                <select className="input" value={newMemoryCategory} onChange={e => setNewMemoryCategory(e.target.value)}
                  style={{ width: '120px', cursor: 'pointer', fontSize: 'var(--font-xs)', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '4px', color: 'var(--text-primary)', padding: '0 8px' }}>
                  <option value="fact">📌 Fait/Infos</option>
                  <option value="preference">⭐ Préférence</option>
                  <option value="user_profile">👤 Profil</option>
                  <option value="habit">🕒 Habitude</option>
                </select>
                <button type="submit" disabled={!newMemoryContent.trim()} style={{
                  padding: '8px 16px', background: 'var(--accent-gradient)',
                  border: 'none', borderRadius: 'var(--radius-md)',
                  color: 'white', fontWeight: 600, cursor: 'pointer',
                  opacity: newMemoryContent.trim() ? 1 : 0.5, fontSize: 'var(--font-xs)',
                }}>
                  Enregistrer
                </button>
              </form>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '300px', overflowY: 'auto', paddingRight: '4px' }}>
                {memories.length === 0 ? (
                  <div style={{
                    padding: '16px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)',
                    border: '1px dashed var(--border)', textAlign: 'center', color: 'var(--text-muted)',
                    fontSize: 'var(--font-xs)', lineHeight: 1.5,
                  }}>
                    🧠 Aucun souvenir enregistré.<br />
                    Parlez-moi de vous dans le chat pour que je m&apos;en souvienne automatiquement !
                  </div>
                ) : memories.map(m => {
                  const labels = { fact: '📌 Infos', preference: '⭐ Préférence', user_profile: '👤 Profil', habit: '🕒 Habitude' };
                  const colors = { fact: 'var(--accent-secondary)', preference: '#f59e0b', user_profile: 'var(--accent-primary)', habit: '#10b981' };
                  return (
                    <div key={m.id} style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '10px 14px', background: 'var(--bg-secondary)',
                      borderRadius: 'var(--radius-md)', border: '1px solid var(--border)',
                      fontSize: 'var(--font-sm)', animation: 'fadeIn 0.3s ease',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, marginRight: '12px' }}>
                        <span style={{
                          fontSize: '10px', padding: '2px 6px', borderRadius: '12px',
                          background: 'rgba(255,255,255,0.02)', color: colors[m.category] || 'var(--text-muted)',
                          fontWeight: 700, border: `1px solid ${colors[m.category] || 'var(--border)'}`, whiteSpace: 'nowrap',
                        }}>
                          {labels[m.category] || m.category}
                        </span>
                        <span style={{ color: 'var(--text-primary)', wordBreak: 'break-word', lineHeight: 1.4 }}>{m.content}</span>
                      </div>
                      <button onClick={() => handleDeleteMemory(m.id)} style={{
                        background: 'none', border: 'none', cursor: 'pointer',
                        fontSize: '16px', color: 'var(--text-muted)', display: 'flex',
                        alignItems: 'center', justifyContent: 'center', padding: '4px',
                      }}>×</button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════════
              ONGLET : CONNEXIONS
              ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === 'connections' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

              {lanAccess && (
                <div style={{
                  padding: '16px', background: 'var(--bg-secondary)',
                  border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
                }}>
                  <div style={{ fontWeight: 650, marginBottom: 6 }}>Accès réseau protégé</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-xs)', lineHeight: 1.5 }}>
                    Le code est à usage unique, valable cinq minutes et n&apos;est jamais écrit dans les journaux.
                  </div>
                  {lanAccess.pairing_code ? (
                    <code style={{
                      display: 'inline-block', marginTop: 10, padding: '9px 12px',
                      borderRadius: 8, background: 'var(--bg-primary)', userSelect: 'all',
                      letterSpacing: '0.06em',
                    }}>
                      {lanAccess.pairing_code}
                    </code>
                  ) : (
                    <div style={{ marginTop: 10, color: 'var(--text-muted)', fontSize: 'var(--font-xs)' }}>
                      Aucun code actif.
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                    <button type="button" className="btn btn-ghost" onClick={regenerateLanPairingCode}>
                      Générer un nouveau code
                    </button>
                    {lanAccess.https?.origins?.map(origin => (
                      <a key={origin} className="btn btn-ghost" href={origin} target="_blank" rel="noreferrer">
                        Ouvrir {origin}
                      </a>
                    ))}
                  </div>
                  {lanAccess.https?.root_sha256 && (
                    <>
                      <div style={{ marginTop: 10, color: 'var(--text-muted)', fontSize: 11, wordBreak: 'break-all' }}>
                        Empreinte SHA-256 de l&apos;autorité Marvin : {lanAccess.https.root_sha256}
                      </div>
                      <a
                        href={`${BACKEND_URL}/api/auth/lan/ca-certificate`}
                        className="btn btn-ghost"
                        style={{ display: 'inline-flex', marginTop: 8 }}
                      >
                        Télécharger l&apos;autorité HTTPS
                      </a>
                    </>
                  )}
                </div>
              )}

              {/* Info générale */}
              <div style={{
                padding: '12px 16px', background: 'rgba(79, 140, 255,0.06)',
                border: '1px solid rgba(79, 140, 255,0.2)', borderRadius: 'var(--radius-md)',
                fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.6,
              }}>
                🔑 Entrez vos clés API et identifiants OAuth pour connecter Marvin aux services externes.
                Tout est stocké localement dans la base de données SQLite — aucune donnée n&apos;est transmise.
              </div>

              {/* ── Identité document (v2.174) ────────────────────────────────── */}
              <div style={{
                padding: '16px', background: 'var(--bg-secondary)',
                border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
              }}>
                <div style={{ fontWeight: 600, fontSize: 'var(--font-sm)', marginBottom: '4px' }}>
                  📄 Identité des documents
                </div>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '12px', lineHeight: 1.5 }}>
                  Renseigné une fois, réutilisé automatiquement par Marvin pour tout PDF/Word généré
                  depuis le chat (auteur, en-tête, pied de page) — plus besoin de le redonner à chaque fois.
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                  {[
                    ['author', 'Auteur (votre nom)'],
                    ['org', 'Organisation'],
                    ['address', 'Adresse'],
                    ['phone', 'Téléphone'],
                    ['email', 'Email'],
                    ['website', 'Site web'],
                    ['logo', 'Chemin du logo (image)'],
                    ['footer_text', 'Texte de pied de page'],
                    ['confidentiality', 'Mention de confidentialité'],
                  ].map(([key, label]) => (
                    <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <label style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>{label}</label>
                      <input
                        type="text"
                        value={docIdentity[key] || ''}
                        onChange={e => setDocIdentity(v => ({ ...v, [key]: e.target.value }))}
                        style={{
                          padding: '8px 10px', borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--border)', background: 'var(--bg-primary)',
                          color: 'var(--text-primary)', fontSize: 'var(--font-sm)',
                        }}
                      />
                    </div>
                  ))}
                </div>
                <button
                  onClick={handleSaveDocIdentity}
                  disabled={docIdentitySaving}
                  style={{
                    marginTop: '12px', padding: '8px 16px', borderRadius: 'var(--radius-sm)',
                    border: 'none', background: 'var(--accent-primary)', color: '#fff',
                    fontSize: 'var(--font-sm)', fontWeight: 600, cursor: docIdentitySaving ? 'default' : 'pointer',
                    opacity: docIdentitySaving ? 0.6 : 1,
                  }}
                >
                  {docIdentitySaving ? 'Enregistrement…' : 'Enregistrer'}
                </button>
              </div>

              {/* ── Google ─────────────────────────────────────────────────────── */}
              <CredentialGroup
                groupKey="google"
                icon="🔴"
                title="Google (Drive, Gmail, Calendar)"
                group={credGroups.google}
                credentials={credentials}
                credValues={credValues}
                setCredValues={setCredValues}
                credVisible={credVisible}
                setCredVisible={setCredVisible}
                credSaving={credSaving}
                onSave={handleSaveCredential}
                onDelete={handleDeleteCredential}
                oauthButton={{
                  label: credGroups.google?.connected ? '🔄 Reconnecter Google' : '🔐 Connexion OAuth Google',
                  onClick: handleGoogleOAuth,
                  disabled: !credGroups.google?.keys_set,
                  hint: !credGroups.google?.keys_set ? 'Renseignez Client ID et Client Secret d\'abord' : null,
                }}
              />

              {/* ── Microsoft ──────────────────────────────────────────────────── */}
              <CredentialGroup
                groupKey="microsoft"
                icon="🔵"
                title="Microsoft (OneDrive, Outlook, Teams)"
                group={credGroups.microsoft}
                credentials={credentials}
                credValues={credValues}
                setCredValues={setCredValues}
                credVisible={credVisible}
                setCredVisible={setCredVisible}
                credSaving={credSaving}
                onSave={handleSaveCredential}
                onDelete={handleDeleteCredential}
                oauthButton={{
                  label: credGroups.microsoft?.connected ? '🔄 Reconnecter Microsoft' : '🔐 Connexion OAuth Microsoft',
                  onClick: handleMicrosoftOAuth,
                  disabled: !credGroups.microsoft?.keys_set,
                  hint: !credGroups.microsoft?.keys_set ? 'Renseignez le Client ID d\'abord' : null,
                }}
              />

              {/* ── Canva ──────────────────────────────────────────────────────── */}
              <CredentialGroup
                groupKey="canva"
                icon="🎨"
                title="Canva"
                group={credGroups.canva}
                credentials={credentials}
                credValues={credValues}
                setCredValues={setCredValues}
                credVisible={credVisible}
                setCredVisible={setCredVisible}
                credSaving={credSaving}
                onSave={handleSaveCredential}
                onDelete={handleDeleteCredential}
              />

              {/* ── Recherche web ───────────────────────────────────────────────── */}
              <CredentialGroup
                groupKey="search"
                icon="🔍"
                title="Recherche Web (SearXNG uniquement)"
                group={credGroups.search}
                credentials={credentials}
                credValues={credValues}
                setCredValues={setCredValues}
                credVisible={credVisible}
                setCredVisible={setCredVisible}
                credSaving={credSaving}
                onSave={handleSaveCredential}
                onDelete={handleDeleteCredential}
                note="Toutes les recherches Marvin passent par l'instance SearXNG locale configurée."
              />

              {/* ── Traduction ──────────────────────────────────────────────────── */}
              <CredentialGroup
                groupKey="translate"
                icon="🌍"
                title="Traduction (MyMemory)"
                group={credGroups.translate}
                credentials={credentials}
                credValues={credValues}
                setCredValues={setCredValues}
                credVisible={credVisible}
                setCredVisible={setCredVisible}
                credSaving={credSaving}
                onSave={handleSaveCredential}
                onDelete={handleDeleteCredential}
                note="Optionnel. Sans clé : 1000 traductions/jour gratuites. Avec clé MyMemory : quota augmenté."
              />

              {/* ── IA distante ────────────────────────────────────────────────── */}
              <CredentialGroup
                groupKey="ai"
                icon="🤖"
                title="IA distante (OpenAI / Anthropic)"
                group={credGroups.ai}
                credentials={credentials}
                credValues={credValues}
                setCredValues={setCredValues}
                credVisible={credVisible}
                setCredVisible={setCredVisible}
                credSaving={credSaving}
                onSave={handleSaveCredential}
                onDelete={handleDeleteCredential}
                note="Optionnel — Marvin utilise Ollama (local) par défaut."
              />

            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════════
              ONGLET : À PROPOS
              ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === 'about' && (
            <div className="card">
              <div className="card-title">ℹ️ À propos</div>
              <div style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
                <strong style={{ color: 'var(--text-primary)' }}>Marvin</strong> — Agent IA Secrétaire v2.33<br />
                Propulsé par Ollama (LLM local) • Next.js • FastAPI Python<br />
                Langues : Français, English<br /><br />
                <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
                  🔒 Toutes les données restent sur votre machine. Aucune donnée n&apos;est envoyée à des serveurs externes.
                </span>
              </div>

              {/* Statut système */}
              <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ fontSize: 'var(--font-sm)', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '4px' }}>Statut système</div>
                {[
                  { label: 'Backend FastAPI', value: 'http://127.0.0.1:8005', ok: true },
                  { label: 'Frontend Next.js', value: 'http://localhost:3000', ok: true },
                  { label: 'Ollama', value: status?.ollama?.connected ? 'Connecté' : 'Déconnecté', ok: status?.ollama?.connected },
                  { label: 'Modèle actif', value: status?.ollama?.model || '—', ok: !!status?.ollama?.model },
                ].map(item => (
                  <div key={item.label} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '8px 12px', background: 'var(--bg-secondary)',
                    borderRadius: 'var(--radius-md)', fontSize: 'var(--font-xs)',
                  }}>
                    <span style={{ color: 'var(--text-muted)' }}>{item.label}</span>
                    <span style={{ color: item.ok ? 'var(--success)' : 'var(--danger)', fontWeight: 600, fontFamily: 'monospace' }}>
                      {item.ok ? '✓' : '✗'} {item.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}

// ── CredentialGroup ────────────────────────────────────────────────────────────
