'use client';
import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';

import { BACKEND_URL } from '@/lib/backend';

const isCloudModelName = model => (
  model.endsWith(':cloud')
  || model.endsWith('-cloud')
  || /^gemma4:e\d+b$/i.test(model)
);

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
    tagline: 'Accès total',
    color: '#8b5cf6',
    colorDim: 'rgba(139,92,246,0.12)',
    border: '#8b5cf6',
    allowed: [
      '🔓 Toutes les permissions',
      '⚡ Aucune confirmation requise',
      '🗑️ Suppression directe',
      '⚙️ Commandes système libres',
      '🔄 Tuer des processus',
      '📋 Modifier le presse-papiers',
    ],
    blocked: [],
    warning: '⚠️ Les actions irréversibles (suppression, commandes) seront exécutées immédiatement sans demande de confirmation.',
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
      const res = await fetch(`${BACKEND_URL}/api/auto-config`, { cache: 'no-store' });
      const data = await res.json();
      setAutoConfig(data);
      const first = (data?.recommended_to_install || [])[0];
      if (first) setPullModelName(current => current || first);
    } catch { }
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

          {/* ═══════════════════════════════════════════════════════════════════
              ONGLET : MODÈLE IA
              ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === 'model' && (
            <div className="card" style={{ borderLeft: '4px solid var(--accent-primary)' }}>
              <div className="card-title" style={{ fontSize: 'var(--font-lg)' }}>🧠 Modèle IA — Ollama</div>

              <div style={{
                display: 'flex', alignItems: 'center', gap: '12px',
                padding: '12px 16px', background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)', marginBottom: '16px',
              }}>
                <span className={`badge-dot ${status?.ollama?.connected ? 'connected' : 'disconnected'}`}
                  style={{ width: '12px', height: '12px' }} />
                <div>
                  <div style={{ fontWeight: 600, color: status?.ollama?.connected ? 'var(--success)' : 'var(--danger)' }}>
                    {status?.ollama?.connected ? '🟢 Ollama est connecté et prêt' : '🔴 Ollama est déconnecté'}
                  </div>
                  {!status?.ollama?.connected && (
                    <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginTop: '4px' }}>
                      Lancez Ollama sur votre PC pour continuer. Téléchargez-le sur{' '}
                      <a href="https://ollama.com" target="_blank" rel="noreferrer" style={{ color: 'var(--accent-secondary)' }}>ollama.com</a>
                    </div>
                  )}
                </div>
              </div>

              <div style={{
                display: 'flex', alignItems: 'center', gap: '12px',
                padding: '12px 16px', background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)', marginBottom: '16px',
              }}>
                <span style={{ fontSize: '1.4rem' }}>🎯</span>
                <div>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>Modèle actuellement actif :</div>
                  <div style={{
                    fontWeight: 700, fontSize: 'var(--font-md)',
                    background: 'var(--accent-gradient)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                  }}>
                    {status?.ollama?.model || 'Aucun modèle détecté'}
                  </div>
                </div>
              </div>

              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', marginBottom: '8px', fontWeight: 600 }}>
                  📋 Changer de modèle actif :
                </label>
                {models.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {models.map(m => {
                      const isActive = m === selectedModel || m === status?.ollama?.model;
                      const recInfo = recommendedModels.find(r => m === r.name);
                      return (
                        <button key={m} onClick={() => handleSetModel(m)} style={{
                          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                          padding: '10px 16px', border: `2px solid ${isActive ? 'var(--accent-primary)' : 'var(--border)'}`,
                          borderRadius: 'var(--radius-md)', cursor: 'pointer',
                          background: isActive ? 'rgba(139, 92, 246, 0.08)' : 'var(--bg-secondary)',
                          color: 'var(--text-primary)', transition: 'all 0.2s', textAlign: 'left',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <span style={{ fontSize: '1.2rem' }}>{isActive ? '✅' : '⚪'}</span>
                            <div>
                              <div style={{ fontWeight: isActive ? 700 : 500, fontSize: 'var(--font-sm)' }}>{m}</div>
                              {recInfo && <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{recInfo.speed} • {recInfo.size}</div>}
                            </div>
                          </div>
                          {isActive && <span className="badge badge-success" style={{ fontSize: '10px' }}>ACTIF</span>}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{
                    padding: '16px', background: 'var(--warning-bg)', borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--warning)', color: 'var(--warning)', fontSize: 'var(--font-sm)',
                  }}>
                    ⚠️ Aucun modèle détecté. {status?.ollama?.connected ? 'Téléchargez-en un ci-dessous.' : 'Lancez d\'abord Ollama.'}
                  </div>
                )}
                <button onClick={fetchStatus} style={{
                  marginTop: '8px', padding: '6px 12px',
                  background: 'transparent', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-md)', color: 'var(--text-secondary)',
                  cursor: 'pointer', fontSize: 'var(--font-xs)',
                }}>
                  🔄 Rafraîchir la liste des modèles
                </button>
              </div>

              <div style={{
                background: 'var(--bg-tertiary)', padding: '16px',
                borderRadius: 'var(--radius-md)', border: '1px solid var(--border)',
              }}>
                {autoConfig && (
                  <div style={{
                    marginBottom: 14, padding: 12, borderRadius: 'var(--radius-md)',
                    background: 'var(--bg-secondary)', color: 'var(--text-secondary)',
                    fontSize: 'var(--font-xs)', lineHeight: 1.6,
                  }}>
                    Budget local sûr : <strong>{autoConfig.model_memory_budget_gb} Go</strong>
                    {' '}— {autoConfig.hardware?.gpu || 'CPU détecté'}.
                    {(autoConfig.rejected_overrides || []).length > 0 && (
                      <div style={{ color: 'var(--warning)', marginTop: 4 }}>
                        {(autoConfig.rejected_overrides || []).length} préférence obsolète ignorée
                        pour éviter un modèle trop lourd ou incompatible.
                      </div>
                    )}
                  </div>
                )}
                <div style={{ fontWeight: 700, fontSize: 'var(--font-sm)', marginBottom: '12px', color: 'var(--text-primary)' }}>
                  📥 Télécharger un nouveau modèle
                </div>
                <div style={{ display: 'flex', gap: '12px', marginBottom: '12px' }}>
                  <input className="input" value={pullModelName} onChange={e => setPullModelName(e.target.value)}
                    placeholder="ex: llama3.2:3b" style={{ flex: 1 }} />
                  <button onClick={handlePullModel} disabled={isPulling} style={{
                    padding: '10px 20px', background: 'var(--accent-gradient)',
                    border: 'none', borderRadius: 'var(--radius-md)',
                    color: 'white', fontWeight: 700, cursor: 'pointer',
                    boxShadow: 'var(--accent-glow)', opacity: isPulling ? 0.7 : 1, whiteSpace: 'nowrap',
                  }}>
                    {isPulling ? '⏳ Téléchargement...' : '📥 Télécharger'}
                  </button>
                </div>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '8px', fontWeight: 600 }}>
                  💡 Suggestions rapides :
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {recommendedModels.map(r => (
                    <button key={r.name} onClick={() => setPullModelName(r.name)} style={{
                      padding: '6px 10px', border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-full)', cursor: 'pointer',
                      background: pullModelName === r.name ? 'var(--accent-gradient)' : 'var(--bg-secondary)',
                      color: pullModelName === r.name ? 'white' : 'var(--text-secondary)',
                      fontSize: '11px', fontWeight: 500, transition: 'all 0.2s',
                    }}>
                      {r.name} ({r.size})
                    </button>
                  ))}
                </div>
              </div>

              <div style={{ marginTop: '16px' }}>
                <label style={{ display: 'block', fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
                  🔗 URL Ollama (avancé)
                </label>
                <input className="input" value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)} placeholder="http://localhost:11434" />
              </div>
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════════
              ONGLET : MODÈLE IA — Ollama Cloud (v2.119)
              ═══════════════════════════════════════════════════════════════════ */}
          {activeTab === 'model' && (() => {
            const activePreset = localOnlyLockdown ? 'hyper'
              : (ultraUnrestricted && cloudEnabled) ? 'ultra'
              : privacyPreset;
            const PRESETS = [
              { id: 'normal', icon: '🛡️', label: 'Normal', tagline: 'Sécurisé — vous choisissez', color: '#f59e0b' },
              { id: 'hyper', icon: '🔒', label: 'Hyper sécurisé', tagline: '100% local, verrouillé', color: '#10b981' },
              { id: 'cloud_max', icon: '☁️', label: 'Tout cloud', tagline: 'Vitesse maximale', color: '#06b6d4' },
              { id: 'ultra', icon: '☠️', label: 'Ultra débridé', tagline: 'Aucune exception', color: '#ef4444' },
            ];
            return (
            <div className="card" style={{ borderLeft: '4px solid #06b6d4', marginTop: '16px' }}>
              <div className="card-title" style={{ fontSize: 'var(--font-lg)' }}>☁️ Ollama Cloud</div>

              {/* v2.120-121 — 4 préréglages globaux : un clic pour appliquer un setup complet */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', marginBottom: '16px' }}>
                {PRESETS.map(p => {
                  const isActive = activePreset === p.id;
                  return (
                    <button key={p.id} onClick={() => applyPreset(p.id)} disabled={presetApplying} style={{
                      padding: '14px 12px', borderRadius: 'var(--radius-md)', cursor: presetApplying ? 'default' : 'pointer',
                      border: `2px solid ${isActive ? p.color : 'var(--border)'}`,
                      background: isActive ? `${p.color}18` : 'var(--bg-secondary)',
                      textAlign: 'center', transition: 'all 0.2s', opacity: presetApplying ? 0.6 : 1,
                    }}>
                      <div style={{ fontSize: '1.5rem', marginBottom: '4px' }}>{p.icon}</div>
                      <div style={{ fontWeight: 700, fontSize: 'var(--font-sm)', color: isActive ? p.color : 'var(--text-primary)' }}>{p.label}</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>{p.tagline}</div>
                      {isActive && <div style={{ marginTop: '6px', fontSize: '10px', fontWeight: 700, color: p.color }}>● ACTIF</div>}
                    </button>
                  );
                })}
              </div>

              {localOnlyLockdown && (
                <div style={{
                  padding: '12px 16px', background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.3)',
                  borderRadius: 'var(--radius-md)', marginBottom: '16px', fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.6,
                }}>
                  🔒 <strong>Mode Hyper sécurisé actif</strong> : aucun modèle cloud ne peut être utilisé, même sélectionné manuellement — coupe-circuit total. Repassez en Normal pour reconfigurer le cloud.
                </div>
              )}

              {activePreset === 'ultra' && (
                <div style={{
                  padding: '12px 16px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.35)',
                  borderRadius: 'var(--radius-md)', marginBottom: '16px', fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.6,
                }}>
                  ☠️ <strong>Mode Ultra débridé actif — cloud strict</strong> : tous les appels LLM génératifs, y compris vision, compétences et replis, restent dans Ollama Cloud. Si le cloud est indisponible, Marvin échoue explicitement au lieu de basculer sur un modèle local. Emails, SSH, mots de passe et factures peuvent partir au cloud. Le garde-fou système contre les commandes destructrices reste actif.
                </div>
              )}

              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
                padding: '12px 16px', background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-md)', marginBottom: '14px', opacity: localOnlyLockdown ? 0.5 : 1,
              }}>
                <div>
                  <div style={{ fontWeight: 600 }}>Activer les modèles cloud</div>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginTop: '2px' }}>
                    Utilise votre abonnement Ollama Cloud pour les tâches lourdes — plus rapide, sans limite de VRAM.
                  </div>
                </div>
                <label style={{ position: 'relative', display: 'inline-block', width: '44px', height: '24px', flexShrink: 0 }}>
                  <input type="checkbox" checked={cloudEnabled} onChange={e => saveCloudEnabled(e.target.checked)}
                    disabled={cloudSaving || localOnlyLockdown} style={{ opacity: 0, width: 0, height: 0 }} />
                  <span onClick={() => !cloudSaving && !localOnlyLockdown && saveCloudEnabled(!cloudEnabled)} style={{
                    position: 'absolute', inset: 0, borderRadius: '999px', cursor: localOnlyLockdown ? 'not-allowed' : 'pointer', transition: 'background 0.2s',
                    background: cloudEnabled ? '#06b6d4' : 'var(--border)',
                  }}>
                    <span style={{
                      position: 'absolute', top: '3px', left: cloudEnabled ? '23px' : '3px',
                      width: '18px', height: '18px', borderRadius: '50%', background: 'white', transition: 'left 0.2s',
                    }} />
                  </span>
                </label>
              </div>

              {activePreset !== 'ultra' && <div style={{
                padding: '12px 16px', background: 'rgba(6,182,212,0.08)', border: '1px solid rgba(6,182,212,0.25)',
                borderRadius: 'var(--radius-md)', marginBottom: '16px', fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.6,
              }}>
                🔒 <strong>Garde-fou intégré, non désactivable</strong> : toute demande touchant des données sensibles
                (emails, SSH, mots de passe/identifiants, clés API, factures/devis clients) reste <strong>toujours en local</strong>,
                même si le cloud est activé ci-dessus — Marvin bascule automatiquement, y compris en cours de conversation
                si un outil sensible est appelé de façon inattendue.
              </div>}

              {cloudEnabled && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {['agent', 'chat', 'analysis'].map(profile => {
                    const cloudModels = models.filter(isCloudModelName);
                    return (
                      <div key={profile} style={{
                        display: 'flex', alignItems: 'center', gap: '12px',
                        padding: '10px 14px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)',
                      }}>
                        <div style={{ width: '90px', fontSize: 'var(--font-sm)', fontWeight: 600, textTransform: 'capitalize' }}>
                          {profile === 'agent' ? '🤖 Agent' : profile === 'chat' ? '💬 Chat' : '🔍 Analyse'}
                        </div>
                        <select
                          className="input"
                          value={cloudOverrides[profile] || ''}
                          onChange={e => setCloudModelForProfile(profile, e.target.value)}
                          disabled={cloudSaving}
                          style={{ flex: 1 }}
                        >
                          <option value="">— Rester en local —</option>
                          {cloudModels.map(m => <option key={m} value={m}>{m}</option>)}
                        </select>
                      </div>
                    );
                  })}
                  {models.filter(isCloudModelName).length === 0 && (
                    <div style={{
                      padding: '12px 16px', background: 'var(--warning-bg)', borderRadius: 'var(--radius-md)',
                      border: '1px solid var(--warning)', color: 'var(--warning)', fontSize: 'var(--font-xs)',
                    }}>
                      ⚠️ Aucun modèle cloud détecté. Téléchargez-en un via <code>ollama pull deepseek-v3.1:cloud</code>
                      {' '}(ou glm/kimi) puis rafraîchissez la liste des modèles ci-dessus.
                    </div>
                  )}
                </div>
              )}
            </div>
            ); })()}

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

              {lanAccess?.pairing_code && (
                <div style={{
                  padding: '16px', background: 'var(--bg-secondary)',
                  border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
                }}>
                  <div style={{ fontWeight: 650, marginBottom: 6 }}>Accès réseau protégé</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-xs)', lineHeight: 1.5 }}>
                    Saisis ce code temporaire sur le téléphone ou le PC à jumeler. Il change au redémarrage
                    et n&apos;est jamais écrit dans les journaux.
                  </div>
                  <code style={{
                    display: 'inline-block', marginTop: 10, padding: '9px 12px',
                    borderRadius: 8, background: 'var(--bg-primary)', userSelect: 'all',
                    letterSpacing: '0.06em',
                  }}>
                    {lanAccess.pairing_code}
                  </code>
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
function CredentialGroup({
  groupKey, icon, title, group, credentials,
  credValues, setCredValues, credVisible, setCredVisible,
  credSaving, onSave, onDelete, oauthButton, note,
}) {
  const [expanded, setExpanded] = useState(true);
  const groupCreds = Object.entries(credentials).filter(([, meta]) => meta.group === groupKey);
  const isConnected = group?.connected;

  return (
    <div className="card" style={{
      border: `1px solid ${isConnected ? 'rgba(16,185,129,0.3)' : 'var(--border)'}`,
      borderLeft: `4px solid ${isConnected ? '#10b981' : 'rgba(79, 140, 255,0.4)'}`,
    }}>
      {/* Header */}
      <div
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', marginBottom: expanded ? '16px' : 0 }}
        onClick={() => setExpanded(e => !e)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '1.4rem' }}>{icon}</span>
          <div>
            <div style={{ fontWeight: 700, fontSize: 'var(--font-sm)', color: 'var(--text-primary)' }}>{title}</div>
            <div style={{ fontSize: '11px', color: isConnected ? '#10b981' : 'var(--text-muted)' }}>
              {isConnected ? '✅ Connecté' : `${group?.keys_set || 0} / ${group?.total_keys || 0} clés configurées`}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{
            padding: '2px 10px', borderRadius: '12px', fontSize: '10px', fontWeight: 700,
            background: isConnected ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.04)',
            color: isConnected ? '#10b981' : 'var(--text-muted)',
            border: `1px solid ${isConnected ? 'rgba(16,185,129,0.4)' : 'var(--border)'}`,
          }}>
            {isConnected ? 'CONNECTÉ' : 'INACTIF'}
          </span>
          <span style={{ color: 'var(--text-muted)', fontSize: '1rem' }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {expanded && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {note && (
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', padding: '8px 12px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)', marginBottom: '4px' }}>
              💡 {note}
            </div>
          )}

          {groupCreds.map(([name, meta]) => {
            const hasValue = meta.has_value;
            const isSecret = meta.secret;
            const isEditing = credValues[name] !== undefined;
            const saving = credSaving[name];
            const visible = credVisible[name];

            return (
              <div key={name} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {meta.label}
                  {hasValue && <span style={{ color: '#10b981', fontSize: '10px' }}>● Configuré</span>}
                </label>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <div style={{ flex: 1, position: 'relative' }}>
                    <input
                      className="input"
                      type={isSecret && !visible ? 'password' : 'text'}
                      value={isEditing ? credValues[name] : (hasValue && isSecret ? '' : (meta.value || ''))}
                      placeholder={hasValue ? (isSecret ? '••••••••••••••• (configuré)' : meta.value) : `Entrez ${meta.label}...`}
                      onChange={e => setCredValues(v => ({ ...v, [name]: e.target.value }))}
                      style={{ width: '100%', paddingRight: isSecret ? '40px' : '12px', fontSize: 'var(--font-xs)', fontFamily: isSecret && !visible ? 'monospace' : 'inherit' }}
                    />
                    {isSecret && (
                      <button
                        onClick={() => setCredVisible(v => ({ ...v, [name]: !v[name] }))}
                        style={{ position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: '14px', padding: '2px' }}
                      >
                        {visible ? '🙈' : '👁️'}
                      </button>
                    )}
                  </div>
                  {isEditing && (
                    <button
                      onClick={() => onSave(name)}
                      disabled={saving}
                      style={{
                        padding: '0 14px', background: 'var(--accent-gradient)', border: 'none',
                        borderRadius: 'var(--radius-md)', color: 'white', fontWeight: 700,
                        cursor: 'pointer', fontSize: '12px', whiteSpace: 'nowrap', opacity: saving ? 0.6 : 1,
                      }}
                    >
                      {saving ? '...' : '💾 Sauver'}
                    </button>
                  )}
                  {hasValue && !isEditing && (
                    <button
                      onClick={() => onDelete(name)}
                      style={{
                        padding: '0 12px', background: 'transparent',
                        border: '1px solid rgba(239,68,68,0.3)', borderRadius: 'var(--radius-md)',
                        color: 'rgba(239,68,68,0.7)', cursor: 'pointer', fontSize: '12px',
                      }}
                    >
                      🗑️
                    </button>
                  )}
                </div>
              </div>
            );
          })}

          {/* Bouton OAuth */}
          {oauthButton && (
            <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <button
                onClick={oauthButton.onClick}
                disabled={oauthButton.disabled}
                style={{
                  padding: '10px 20px',
                  background: oauthButton.disabled ? 'var(--bg-secondary)' : 'var(--accent-gradient)',
                  border: oauthButton.disabled ? '1px solid var(--border)' : 'none',
                  borderRadius: 'var(--radius-md)',
                  color: oauthButton.disabled ? 'var(--text-muted)' : 'white',
                  fontWeight: 700, cursor: oauthButton.disabled ? 'not-allowed' : 'pointer',
                  fontSize: 'var(--font-sm)', transition: 'all 0.2s',
                  boxShadow: oauthButton.disabled ? 'none' : 'var(--accent-glow)',
                }}
              >
                {oauthButton.label}
              </button>
              {oauthButton.hint && (
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>← {oauthButton.hint}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
