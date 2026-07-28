'use client';
import { useEffect, useState, useCallback, useRef } from 'react';
import ChatContainer from '@/components/chat/ChatContainer';
import LivingAvatar from '@/components/avatar/LivingAvatar';
import { useChatStatus } from '@/lib/contexts/ChatContext';
import { useToast } from '@/components/ui/Toast';
import { BACKEND_URL } from '@/lib/backend';
import {
  canSwitchConversation,
  initialChatSelection,
  persistLastConversationId,
  readLastConversationId,
} from '@/lib/chatNavigation.mjs';

async function fetchWithBackendFallback(path, options) {
  try {
    const localResponse = await fetch(path, options);
    if (localResponse.ok || localResponse.status !== 404) return localResponse;
  } catch {
    // Repli direct si le proxy Next n'est momentanément pas joignable.
  }
  return fetch(`${BACKEND_URL}${path}`, options);
}

export default function ChatPage() {
  const { toast } = useToast();
  const chatStatus = useChatStatus();   // { isLoading, ... } → fait battre l'avatar plus vite
  const initialSelection = initialChatSelection(chatStatus);
  const [conversations, setConversations] = useState([]);
  const [projects, setProjects] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(initialSelection.conversationId);
  const [chatKey, setChatKey] = useState(initialSelection.chatKey);
  const [selectionHydrated, setSelectionHydrated] = useState(false);
  const [pendingActiveId, setPendingActiveId] = useState(null);
  const pendingIdRef = useRef(null);
  const [initialMessages, setInitialMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newProjectName, setNewProjectName] = useState('');
  const [showProjectInput, setShowProjectInput] = useState(false);
  const [showConv, setShowConv] = useState(false);   // tiroir des conversations (mobile)
  const [convSearch, setConvSearch] = useState('');  // recherche dans les conversations
  const [collapsed, setCollapsed] = useState(false); // sidebar des conversations repliée (desktop)
  // v2.142 — instructions persistantes de projet (équivalent Claude/ChatGPT Projects)
  const [editingProjectId, setEditingProjectId] = useState(null);
  const [projectInstructionsDraft, setProjectInstructionsDraft] = useState('');

  // Repli persistant (revient au prochain chargement tel qu'on l'a laissé)
  useEffect(() => {
    try { setCollapsed(localStorage.getItem('marvin:conv_sidebar_collapsed') === '1'); } catch {}
  }, []);
  useEffect(() => {
    try { localStorage.setItem('marvin:conv_sidebar_collapsed', collapsed ? '1' : '0'); } catch {}
  }, [collapsed]);

  // Raccourci global Ctrl+N / palette de commandes : démarre une nouvelle conversation
  // même si on est déjà sur "/" (un simple router.push('/') serait un no-op ici).
  useEffect(() => {
    const onNewConv = () => {
      if (chatStatus.isLoading) {
        toast.warning('Réponse en cours', 'Attends la fin ou arrête Marvin avant de créer une autre conversation. Le flux actuel reste conservé.');
        return;
      }
      setActiveConversationId(null);
      setInitialMessages([]);
      setChatKey('new_' + Date.now());
      setShowConv(false);
    };
    window.addEventListener('marvin:new-conversation', onNewConv);
    return () => window.removeEventListener('marvin:new-conversation', onNewConv);
  }, [chatStatus.isLoading, toast]);

  // État du modèle actif et liste des modèles disponibles
  const [activeModel, setActiveModel] = useState('auto'); // "auto" = routing intelligent
  const [availableModels, setAvailableModels] = useState([]);
  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const [ollamaConnected, setOllamaConnected] = useState(false);
  const [pullModelName, setPullModelName] = useState('');
  const [pullStatus, setPullStatus] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [convRes, projRes] = await Promise.all([
        fetch('/api/conversations?t=' + Date.now()),
        fetch('/api/projects?t=' + Date.now())
      ]);
      if (convRes.ok) {
        const data = await convRes.json();
        setConversations(data.conversations || []);
      }
      if (projRes.ok) {
        const data = await projRes.json();
        setProjects(data || []);
      }
    } catch (err) {
      console.error('Erreur chargement données:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/status?t=' + Date.now());
      if (res.ok) {
        const data = await res.json();
        // Ne pas écraser le choix "auto" de l'utilisateur lors du rafraîchissement
        setActiveModel(prev => prev === 'auto' ? 'auto' : (data.ollama?.model || prev));
        setAvailableModels(data.ollama?.models || []);
        setOllamaConnected(data.ollama?.connected || false);
      }
    } catch {
      setOllamaConnected(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchStatus();
    const interval = setInterval(fetchData, 10000);
    const statusInterval = setInterval(fetchStatus, 15000);
    return () => { clearInterval(interval); clearInterval(statusInterval); };
  }, [fetchData, fetchStatus]);

  // Restaurer le dernier fil après un rechargement complet. Seul son identifiant
  // opaque est conservé localement ; le contenu reste la source de vérité backend.
  useEffect(() => {
    if (activeConversationId || chatStatus.conversationId) {
      setSelectionHydrated(true);
      return;
    }

    const savedId = readLastConversationId(window.localStorage);
    if (!savedId) {
      setSelectionHydrated(true);
      return;
    }

    let cancelled = false;
    const restore = async () => {
      try {
        const path = `/api/conversations/${savedId}?t=${Date.now()}`;
        const response = await fetchWithBackendFallback(path);
        if (!response.ok) {
          persistLastConversationId(window.localStorage, null);
          return;
        }
        const data = await response.json();
        if (cancelled) return;
        setInitialMessages(Array.isArray(data.messages) ? data.messages : []);
        setActiveConversationId(savedId);
        setChatKey(savedId);
      } catch (error) {
        console.error('Erreur restauration conversation:', error);
      } finally {
        if (!cancelled) setSelectionHydrated(true);
      }
    };
    restore();
    return () => { cancelled = true; };
    // L'initialisation doit être exécutée une seule fois, y compris en Strict Mode.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectionHydrated) return;
    persistLastConversationId(window.localStorage, activeConversationId);
  }, [activeConversationId, selectionHydrated]);

  const loadConversation = async (id) => {
    setShowConv(false);   // referme le tiroir (mobile)
    if (!canSwitchConversation({
      isLoading: chatStatus.isLoading,
      liveConversationId: chatStatus.conversationId,
      targetConversationId: id,
    })) {
      toast.warning('Réponse en cours', 'La conversation active continue en arrière-plan. Attends sa fin ou arrête-la avant d’en ouvrir une autre.');
      return;
    }
    if (!id) {
      setInitialMessages([]);
      setActiveConversationId(null);
      setChatKey('new_' + Date.now());
      return;
    }
    if (activeConversationId === id) return;
    try {
      const path = `/api/conversations/${id}?t=${Date.now()}`;
      const res = await fetchWithBackendFallback(path);
      if (!res.ok) throw new Error(`Conversation HTTP ${res.status}`);
      const data = await res.json();
      setInitialMessages(data.messages || []);
      setActiveConversationId(id);
      setChatKey(id);
    } catch (err) {
      console.error('Erreur chargement messages:', err);
      toast.error('Conversation inaccessible', 'Les messages sont conservés. Réessayez après le diagnostic du frontend.');
    }
  };

  const switchModel = async (modelName) => {
    setActiveModel(modelName);
    setShowModelDropdown(false);
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'set_model', modelName })
      });
      fetchStatus();
    } catch (err) {
      console.error('Erreur changement modèle:', err);
    }
  };

  const pullModel = async (e) => {
    if (e) e.preventDefault();
    if (!pullModelName.trim()) return;
    setPullStatus('downloading');
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'pull_model', modelName: pullModelName.trim() })
      });
      if (res.ok) {
        setPullStatus('started');
        setPullModelName('');
        setTimeout(() => { setPullStatus(null); fetchStatus(); }, 5000);
      } else {
        setPullStatus('error');
      }
    } catch {
      setPullStatus('error');
    }
  };

  // Badge de performance / spécialité par modèle
  const getModelBadge = (modelName) => {
    if (modelName === 'auto') return { label: '✨ Routing intelligent', color: '#4f8cff' };
    const lower = modelName.toLowerCase();
    if (lower.includes('llava') || lower.includes('vision') || lower.includes('minicpm')) return { label: '👁️ Vision', color: '#8b5cf6' };
    if (lower.includes('coder'))                 return { label: '💻 Code', color: '#06b6d4' };
    if (lower.includes('qwen2.5:7b'))            return { label: '🤖 Agent IA ⭐', color: '#4f8cff' };
    if (lower.includes('qwen2.5:14b'))           return { label: '🔍 Analyse ⭐', color: '#f97316' };
    if (lower.includes('qwen2.5:3b'))            return { label: '⚡ Chat rapide', color: '#22c55e' };
    if (lower.includes(':1.5b') || lower.includes(':1b') || lower.includes(':0.5b')) return { label: '⚡ Ultra rapide', color: '#10b981' };
    if (lower.includes(':3b') || lower.includes(':4b')) return { label: '⚡ Rapide', color: '#22c55e' };
    if (lower.includes(':7b') || lower.includes(':8b')) return { label: '⏳ Équilibré', color: '#f59e0b' };
    if (lower.includes(':13b') || lower.includes(':14b')) return { label: '🔍 Puissant', color: '#f97316' };
    if (lower.includes(':70b'))                  return { label: '🐢 Très lent', color: '#ef4444' };
    return { label: '', color: '#94a3b8' };
  };

  const createProject = async (e) => {
    if (e) e.preventDefault();
    if (!newProjectName.trim()) return;
    try {
      await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newProjectName.trim() })
      });
      setNewProjectName('');
      setShowProjectInput(false);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const deleteConversation = async (e, id) => {
    e.stopPropagation();
    if (!confirm('Supprimer cette conversation définitivement ?')) return;
    try {
      const response = await fetchWithBackendFallback(`/api/conversations/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`Suppression HTTP ${response.status}`);
      if (activeConversationId === id) {
        // Clear the chat view when deleting the active conversation
        setActiveConversationId(null);
        setInitialMessages([]);
        setChatKey('new_' + Date.now());
      }
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const deleteProject = async (e, id) => {
    e.stopPropagation();
    if (!confirm('Supprimer ce projet ?')) return;
    try {
      const response = await fetchWithBackendFallback(`/api/projects/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(`Suppression projet HTTP ${response.status}`);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  // v2.142 — instructions persistantes de projet, injectées automatiquement dans le
  // prompt système de toute conversation du projet (agent.py::run_agent).
  const openProjectInstructions = (e, proj) => {
    e.stopPropagation();
    setEditingProjectId(proj.id);
    setProjectInstructionsDraft(proj.instructions || '');
  };

  const saveProjectInstructions = async () => {
    try {
      const response = await fetchWithBackendFallback(`/api/projects/${editingProjectId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instructions: projectInstructionsDraft }),
      });
      if (!response.ok) throw new Error(`Projet HTTP ${response.status}`);
      setEditingProjectId(null);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const assignProject = async (convId, projectId) => {
    try {
      const response = await fetchWithBackendFallback(`/api/conversations/${convId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId: projectId === 'none' ? null : projectId })
      });
      if (!response.ok) throw new Error(`Affectation HTTP ${response.status}`);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const renameConversation = async (id, title) => {
    const t = (title || '').trim();
    if (!t) return;
    try {
      const response = await fetchWithBackendFallback(`/api/conversations/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: t }) });
      if (!response.ok) throw new Error(`Renommage HTTP ${response.status}`);
      fetchData();
    } catch (err) { console.error(err); }
  };

  // v2.171 — épinglage (pattern Claude/ChatGPT) : garder une conversation en haut de la
  // liste indépendamment de sa date, sans avoir à la ranger dans un projet pour ça.
  const togglePin = async (e, id, pinned) => {
    e.stopPropagation();
    try {
      const response = await fetchWithBackendFallback(`/api/conversations/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pinned: !pinned }) });
      if (!response.ok) throw new Error(`Épinglage HTTP ${response.status}`);
      fetchData();
    } catch (err) { console.error(err); }
  };

  // v2.171 — recherche FULL-TEXT (titre + contenu des messages) côté backend, débounced.
  // Avant : filtre client sur le titre tronqué à 6 mots seulement (voir matchesQ ci-dessous,
  // conservé comme repli tant que la recherche serveur n'a pas encore répondu).
  const [searchResults, setSearchResults] = useState(null); // null = pas de recherche active
  const [searching, setSearching] = useState(false);
  useEffect(() => {
    const term = convSearch.trim();
    if (!term) { setSearchResults(null); setSearching(false); return; }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const res = await fetch(`/api/conversations/search?q=${encodeURIComponent(term)}`);
        if (res.ok) setSearchResults(await res.json());
      } catch (err) {
        console.error('Erreur recherche conversations:', err);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [convSearch]);

  // Recherche + groupement par date des conversations
  const q = convSearch.trim().toLowerCase();
  const matchesQ = (c) => !q || (c.title || '').toLowerCase().includes(q);
  const dateBucket = (c) => {
    // Timestamp SQLite UTC naïf (sans fuseau) — +'Z' force l'interprétation UTC correcte,
    // sinon le navigateur le lit comme heure locale et peut classer une conversation faite
    // juste après minuit locale dans "hier" au lieu d'"aujourd'hui" (décalage = écart UTC).
    const raw = (c.updated_at || c.created_at || '').replace(' ', 'T') + 'Z';
    const d = new Date(raw);
    if (isNaN(d.getTime())) return 'Plus ancien';
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return "Aujourd'hui";
    const diff = (now - d) / 86400000;
    if (diff < 7) return '7 derniers jours';
    if (diff < 30) return '30 derniers jours';
    return 'Plus ancien';
  };
  const BUCKET_ORDER = ["Aujourd'hui", '7 derniers jours', '30 derniers jours', 'Plus ancien'];

  // v2.171 — mode recherche : liste plate des résultats serveur (full-text), pas de
  // groupement par projet/date — pattern Claude/ChatGPT (les résultats de recherche ne
  // sont jamais imbriqués dans la hiérarchie normale).
  const isSearching = q.length > 0;
  const searchList = searchResults || [];

  // Épinglées : montrées à part, en haut, retirées des autres groupes pour éviter les
  // doublons visuels (indépendant du rangement par projet).
  const pinnedConvs = conversations.filter(c => c.pinned);

  // Grouper les conversations par projet
  const unassigned = conversations.filter(c => !c.project_id && !c.pinned);
  const byProject = {};
  projects.forEach(p => byProject[p.id] = []);
  conversations.forEach(c => {
    if (c.project_id && byProject[c.project_id] && !c.pinned) {
      byProject[c.project_id].push(c);
    }
  });
  const unassignedF = unassigned.filter(matchesQ);
  const buckets = {};
  unassignedF.forEach(c => { const b = dateBucket(c); (buckets[b] = buckets[b] || []).push(c); });

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* Fond cliquable quand le tiroir des conversations est ouvert (mobile) */}
      {showConv && (
        <div onClick={() => setShowConv(false)}
          style={{ position: 'fixed', inset: 0, zIndex: 1002, background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)' }} />
      )}

      {/* ═══ Sidebar des conversations ═══ (tiroir sur mobile, repliable sur desktop) */}
      <div className={`conv-sidebar ${showConv ? 'open' : ''}`} style={{
        width: collapsed ? '0px' : '280px',
        minWidth: collapsed ? '0px' : '280px',
        borderRight: collapsed ? 'none' : '1px solid rgba(228, 228, 231,0.06)',
        overflow: 'hidden',
        transition: 'width 0.2s cubic-bezier(0.4,0,0.2,1), min-width 0.2s cubic-bezier(0.4,0,0.2,1)',
        display: 'flex',
        flexShrink: 0,
      }}>
      <div style={{ width: '280px', minWidth: '280px', display: 'flex', flexDirection: 'column', background: '#0d0d0d', height: '100%' }}>
        <div style={{ padding: '16px' }}>
          <button
            onClick={() => { setActiveConversationId(null); setInitialMessages([]); setChatKey('new_' + Date.now()); setShowConv(false); }}
            style={{
              width: '100%', padding: '12px',
              background: 'var(--accent-gradient)', color: 'white',
              border: 'none', borderRadius: 'var(--radius-md)',
              cursor: 'pointer', fontWeight: 600,
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px'
            }}>
            <span>+</span> Nouvelle conversation
          </button>
          <div style={{ position: 'relative', marginTop: 10 }}>
            <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', fontSize: 12, opacity: 0.6, pointerEvents: 'none' }}>🔍</span>
            <input
              value={convSearch}
              onChange={(e) => setConvSearch(e.target.value)}
              placeholder={`Rechercher (${conversations.length})…`}
              style={{ width: '100%', padding: '8px 10px 8px 30px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)', background: 'rgba(255,255,255,0.03)', color: 'var(--text-primary)', fontSize: 12.5, boxSizing: 'border-box' }}
            />
            {convSearch && <button onClick={() => setConvSearch('')} title="Effacer" style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 14 }}>×</button>}
          </div>
        </div>

        <div style={{
          flex: 1, overflowY: 'auto', padding: '0 12px',
          display: 'flex', flexDirection: 'column', gap: '12px'
        }}>
          {isSearching ? (
            /* v2.171 — mode recherche : liste plate des résultats full-text (titre +
               contenu), pas de groupement — pattern Claude/ChatGPT. */
            <div>
              {searching ? (
                <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '8px' }}>Recherche…</div>
              ) : searchList.length === 0 ? (
                <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '8px' }}>Aucun résultat.</div>
              ) : (
                searchList.map(conv => (
                  <ConversationItem key={conv.id} conv={conv} isActive={activeConversationId === conv.id} onSelect={loadConversation} onDelete={deleteConversation} onAssign={assignProject} onRename={renameConversation} onTogglePin={togglePin} projects={projects} />
                ))
              )}
            </div>
          ) : (
          <>
          {/* Épinglées */}
          {pinnedConvs.length > 0 && (
            <div>
              <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '8px', paddingLeft: '4px' }}>📌 ÉPINGLÉES</div>
              {pinnedConvs.map(conv => (
                <ConversationItem key={conv.id} conv={conv} isActive={activeConversationId === conv.id} onSelect={loadConversation} onDelete={deleteConversation} onAssign={assignProject} onRename={renameConversation} onTogglePin={togglePin} projects={projects} />
              ))}
            </div>
          )}

          {/* Projets */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', paddingLeft: '4px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)' }}>PROJETS</span>
              <button onClick={() => setShowProjectInput(!showProjectInput)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}>+</button>
            </div>

            {showProjectInput && (
              <form onSubmit={createProject} style={{ display: 'flex', gap: '4px', marginBottom: '8px' }}>
                <input
                  type="text"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  placeholder="Nom du projet"
                  autoFocus
                  style={{ flex: 1, padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', fontSize: '13px' }}
                />
              </form>
            )}

            {projects.map(proj => (
              <div key={proj.id} style={{ marginBottom: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 8px', background: 'var(--bg-glass)', borderRadius: '4px', marginBottom: '4px' }}>
                  <strong style={{ fontSize: '13px', color: 'var(--text-primary)' }} title={proj.instructions ? 'Instructions actives' : ''}>
                    📁 {proj.name}{proj.instructions ? ' 📋' : ''}
                  </strong>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button onClick={(e) => openProjectInstructions(e, proj)} title="Instructions du projet" style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px', opacity: 0.5 }}>⚙️</button>
                    <button onClick={(e) => deleteProject(e, proj.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px', opacity: 0.5 }}>🗑️</button>
                  </div>
                </div>
                {editingProjectId === proj.id && (
                  <div style={{ padding: '8px', background: 'var(--bg-tertiary)', borderRadius: '6px', marginBottom: '6px', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                      Instructions appliquées automatiquement à toutes les conversations de ce projet :
                    </div>
                    <textarea
                      value={projectInstructionsDraft}
                      onChange={(e) => setProjectInstructionsDraft(e.target.value)}
                      placeholder="Ex. : Ce projet concerne le client X — utilise toujours le vouvoiement, mentionne le contrat de maintenance en cours..."
                      rows={4}
                      autoFocus
                      style={{ width: '100%', padding: '6px 8px', borderRadius: '4px', border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', fontSize: '12px', resize: 'vertical', boxSizing: 'border-box' }}
                    />
                    <div style={{ display: 'flex', gap: '6px', marginTop: '6px', justifyContent: 'flex-end' }}>
                      <button onClick={() => setEditingProjectId(null)} style={{ fontSize: '11px', padding: '4px 10px', borderRadius: '4px', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>Annuler</button>
                      <button onClick={saveProjectInstructions} style={{ fontSize: '11px', padding: '4px 10px', borderRadius: '4px', border: 'none', background: 'var(--accent-primary)', color: '#fff', cursor: 'pointer' }}>Enregistrer</button>
                    </div>
                  </div>
                )}
                <div style={{ paddingLeft: '12px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  {(byProject[proj.id] || []).length === 0 && <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Vide</span>}
                  {(byProject[proj.id] || []).map(conv => (
                    <ConversationItem key={conv.id} conv={conv} isActive={activeConversationId === conv.id} onSelect={loadConversation} onDelete={deleteConversation} onAssign={assignProject} onRename={renameConversation} onTogglePin={togglePin} projects={projects} />
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Conversations sans projet — groupées par date */}
          <div>
            {loading ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '8px' }}>Chargement...</div>
            ) : unassignedF.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '8px' }}>{convSearch ? 'Aucun résultat.' : 'Aucune conversation'}</div>
            ) : (
              BUCKET_ORDER.filter(b => buckets[b]?.length).map(b => (
                <div key={b} style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--accent-primary)', opacity: 0.55, marginBottom: '5px', paddingLeft: '4px' }}>{b}</div>
                  {buckets[b].map(conv => (
                    <ConversationItem key={conv.id} conv={conv} isActive={activeConversationId === conv.id} onSelect={loadConversation} onDelete={deleteConversation} onAssign={assignProject} onRename={renameConversation} onTogglePin={togglePin} projects={projects} />
                  ))}
                </div>
              ))
            )}
          </div>
          </>
          )}
        </div>
      </div>
      </div>

      {/* Poignée de repli/dépli de la sidebar des conversations (desktop uniquement —
          sur mobile le tiroir est déjà géré par showConv/conv-toggle). */}
      <button
        className="conv-collapse-handle"
        onClick={() => setCollapsed(c => !c)}
        title={collapsed ? 'Afficher les conversations' : 'Masquer les conversations'}
        aria-label={collapsed ? 'Afficher les conversations' : 'Masquer les conversations'}
        style={{
          width: '14px', flexShrink: 0, alignSelf: 'stretch',
          border: 'none', borderRight: '1px solid var(--border)',
          background: 'var(--bg-secondary)', color: 'var(--text-muted)',
          cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 9, padding: 0, transition: 'color 0.15s, background 0.15s',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--accent-primary)'; e.currentTarget.style.background = 'var(--bg-tertiary)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.background = 'var(--bg-secondary)'; }}
      >
        {collapsed ? '▶' : '◀'}
      </button>

      {/* ═══ Zone de chat ═══ */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', position: 'relative' }}>
        {/* Header avec modèle dynamique */}
        <div className="page-header" style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-primary)', zIndex: 10 }}>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button className="conv-toggle" onClick={() => setShowConv(true)} aria-label="Conversations" title="Conversations"
              style={{ background: 'rgba(79, 140, 255,0.12)', border: '1px solid rgba(79, 140, 255,0.3)', color: '#4f8cff',
                       borderRadius: 8, width: 36, height: 36, fontSize: 16, cursor: 'pointer', flexShrink: 0,
                       alignItems: 'center', justifyContent: 'center' }}>💬</button>
            <LivingAvatar size={36} thinking={chatStatus?.isLoading} />
            <span className="holo-text">Marvin</span>
          </h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', position: 'relative' }}>
            {/* Indicateur Ollama */}
            <span className={`badge-dot ${ollamaConnected ? 'connected' : 'disconnected'}`} />

            {/* Sélecteur de modèle rapide */}
            <button
              onClick={() => setShowModelDropdown(!showModelDropdown)}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '6px 12px',
                background: 'var(--bg-glass)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-full)', cursor: 'pointer',
                color: 'var(--text-primary)', fontSize: 'var(--font-xs)',
                fontWeight: 600, transition: 'all 0.2s',
              }}
            >
              <span style={{ background: 'var(--accent-gradient)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                🧠 {activeModel === 'auto' ? '✨ Auto' : activeModel}
              </span>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>▼</span>
            </button>

            {/* Dropdown des modèles */}
            {showModelDropdown && (
              <div style={{
                position: 'absolute', top: '100%', right: 0, marginTop: '8px',
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)', padding: '8px',
                minWidth: '220px', zIndex: 100,
                boxShadow: 'var(--shadow-lg)',
                animation: 'slideDown 0.2s ease',
              }}>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', padding: '4px 8px', marginBottom: '4px', fontWeight: 600 }}>
                  Modèles disponibles
                </div>

                {/* Option Auto — toujours présente en premier */}
                {(() => {
                  const badge = getModelBadge('auto');
                  const isActive = activeModel === 'auto';
                  return (
                    <button
                      onClick={() => switchModel('auto')}
                      style={{
                        display: 'flex', width: '100%', textAlign: 'left',
                        alignItems: 'center', justifyContent: 'space-between',
                        padding: '8px 12px', border: 'none', borderRadius: '4px',
                        background: isActive ? 'rgba(79, 140, 255,0.12)' : 'transparent',
                        color: isActive ? 'var(--accent-primary)' : 'var(--text-primary)',
                        cursor: 'pointer', fontSize: 'var(--font-xs)',
                        fontWeight: isActive ? 700 : 500,
                        borderBottom: '1px solid var(--border)',
                        marginBottom: '4px',
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(79, 140, 255,0.08)'}
                      onMouseLeave={(e) => e.currentTarget.style.background = isActive ? 'rgba(79, 140, 255,0.12)' : 'transparent'}
                    >
                      <span>{isActive ? '✓ ' : '  '}🤖 Auto</span>
                      <span style={{ fontSize: '10px', color: badge.color, fontWeight: 600 }}>{badge.label}</span>
                    </button>
                  );
                })()}

                {availableModels.length === 0 ? (
                  <div style={{ padding: '8px', color: 'var(--text-muted)', fontSize: 'var(--font-xs)' }}>
                    Aucun modèle détecté. Ollama est-il lancé ?
                  </div>
                ) : (
                  availableModels.map(model => {
                    const badge = getModelBadge(model);
                    return (
                      <button
                        key={model}
                        onClick={() => switchModel(model)}
                        style={{
                          display: 'flex', width: '100%', textAlign: 'left',
                          alignItems: 'center', justifyContent: 'space-between',
                          padding: '8px 12px', border: 'none', borderRadius: '4px',
                          background: model === activeModel ? 'var(--bg-glass-active)' : 'transparent',
                          color: model === activeModel ? 'var(--accent-primary)' : 'var(--text-primary)',
                          cursor: 'pointer', fontSize: 'var(--font-xs)',
                          fontWeight: model === activeModel ? 700 : 400,
                          transition: 'background 0.1s',
                        }}
                        onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-glass)'}
                        onMouseLeave={(e) => e.currentTarget.style.background = model === activeModel ? 'var(--bg-glass-active)' : 'transparent'}
                      >
                        <span>{model === activeModel ? '✓ ' : '  '}{model}</span>
                        {badge.label && <span style={{ fontSize: '10px', color: badge.color, fontWeight: 600 }}>{badge.label}</span>}
                      </button>
                    );
                  })
                )}
                <div style={{ borderTop: '1px solid var(--border)', marginTop: '8px', paddingTop: '8px' }}>
                  <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px', fontWeight: 600 }}>
                    ⬇️ Télécharger un modèle
                  </div>
                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginBottom: '6px' }}>
                    {['qwen2.5:7b', 'qwen2.5:3b', 'qwen2.5:14b', 'llava-phi3', 'qwen2.5-coder:7b'].filter(m => !availableModels.includes(m)).map(m => (
                      <button key={m} onClick={() => setPullModelName(m)} style={{
                        padding: '3px 8px', fontSize: '10px', borderRadius: '12px',
                        border: '1px solid var(--border)', background: pullModelName === m ? 'var(--accent-primary)' : 'var(--bg-glass)',
                        color: pullModelName === m ? 'white' : 'var(--text-secondary)', cursor: 'pointer',
                      }}>
                        {m}
                      </button>
                    ))}
                  </div>
                  <form onSubmit={pullModel} style={{ display: 'flex', gap: '4px' }}>
                    <input
                      type="text" value={pullModelName}
                      onChange={(e) => setPullModelName(e.target.value)}
                      placeholder="ex: hermes3:8b, qwen2.5:7b"
                      style={{
                        flex: 1, padding: '4px 8px', borderRadius: '4px',
                        border: '1px solid var(--border)', background: 'var(--bg-primary)',
                        color: 'var(--text-primary)', fontSize: '11px',
                      }}
                    />
                    <button type="submit" disabled={!pullModelName.trim() || pullStatus === 'downloading'} style={{
                      padding: '4px 10px', borderRadius: '4px', border: 'none',
                      background: 'var(--accent-gradient)', color: 'white',
                      cursor: pullModelName.trim() ? 'pointer' : 'not-allowed',
                      fontSize: '11px', fontWeight: 600, opacity: pullModelName.trim() ? 1 : 0.5,
                    }}>
                      {pullStatus === 'downloading' ? '⏳' : '⬇️'}
                    </button>
                  </form>
                  {pullStatus === 'started' && <div style={{ fontSize: '10px', color: '#22c55e', marginTop: '4px' }}>✅ Téléchargement lancé en arrière-plan !</div>}
                  {pullStatus === 'error' && <div style={{ fontSize: '10px', color: '#ef4444', marginTop: '4px' }}>❌ Erreur de téléchargement</div>}
                </div>
                <div style={{ borderTop: '1px solid var(--border)', marginTop: '8px', paddingTop: '8px' }}>
                  <a href="/settings" style={{ fontSize: 'var(--font-xs)', color: 'var(--accent-secondary)' }}>
                    ⚙️ Gérer les modèles...
                  </a>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Chat Container — key force la réinitialisation quand on change de conversation
            IMPORTANT : ne JAMAIS changer la key après un stream finish, sinon le composant
            se remonte et les messages affichés sont perdus (car initialMessages reste vide). */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <ChatContainer
            key={chatKey}
            conversationId={activeConversationId}
            initialMessages={initialMessages}
            activeModel={activeModel}
            onConversationCreated={(newId) => {
              if (newId) {
                setActiveConversationId(newId);
                // NE PAS changer chatKey ici — sinon le composant remonte et perd les messages.
                // Le conversationId prop est suffisant pour identifier la conversation.
              }
              fetchData();
            }}
            onStreamFinish={() => {
              // Rafraîchir la liste des conversations pour montrer le titre auto-généré
              fetchData();
            }}
          />
        </div>
      </div>

      {/* Fermer le dropdown quand on clique ailleurs */}
      {showModelDropdown && (
        <div
          onClick={() => setShowModelDropdown(false)}
          style={{ position: 'fixed', inset: 0, zIndex: 9 }}
        />
      )}
    </div>
  );
}

// ─── Composant conversation dans la sidebar (renommage inline + actions au survol) ───
function ConversationItem({ conv, isActive, onSelect, onDelete, onAssign, onRename, onTogglePin, projects }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conv.title || '');
  const [hover, setHover] = useState(false);
  const commit = () => { setEditing(false); const t = (draft || '').trim(); if (t && t !== conv.title) onRename?.(conv.id, t); };
  return (
    <div
      role="listitem"
      aria-current={isActive ? 'true' : undefined}
      onClick={() => !editing && onSelect(conv.id)}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        padding: '7px 8px 7px 10px', borderRadius: 'var(--radius-md)',
        cursor: 'pointer', fontSize: '13px',
        background: isActive ? 'rgba(79, 140, 255,0.08)' : (hover ? 'rgba(255,255,255,0.03)' : 'transparent'),
        color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
        borderLeft: `2px solid ${isActive ? 'var(--accent-primary)' : 'transparent'}`,
        display: 'flex', alignItems: 'center', gap: 6,
        transition: 'background 0.15s ease', marginBottom: '2px',
      }}
    >
      {!editing && !!conv.pinned && (
        <span title="Épinglée" style={{ fontSize: '11px', flexShrink: 0, opacity: 0.85 }}>📌</span>
      )}
      {editing ? (
        <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setEditing(false); setDraft(conv.title || ''); } }}
          onBlur={commit}
          style={{ flex: 1, minWidth: 0, padding: '3px 6px', borderRadius: 6, border: '1px solid var(--border-focus)', background: 'var(--bg-primary)', color: 'var(--text-primary)', fontSize: 12.5 }} />
      ) : (
        <span
          role="button"
          tabIndex={0}
          aria-label={`Ouvrir la conversation ${conv.title || 'Sans titre'}`}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              event.stopPropagation();
              onSelect(conv.id);
            }
          }}
          style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}
        >
          {conv.title || 'Sans titre'}
        </span>
      )}
      {!editing && (
        <div style={{ display: 'flex', gap: 2, alignItems: 'center', flexShrink: 0, opacity: hover || isActive || conv.pinned ? 1 : 0, transition: 'opacity 0.15s' }}>
          {projects.length > 0 && (
            <select value={conv.project_id || 'none'} onChange={(e) => onAssign(conv.id, e.target.value)} onClick={(e) => e.stopPropagation()} title="Ranger dans un projet"
              aria-label={`Ranger ${conv.title || 'cette conversation'} dans un projet`}
              style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text-muted)', fontSize: '10px', cursor: 'pointer', maxWidth: 54 }}>
              <option value="none">📁</option>
              {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
          <button type="button" onClick={(e) => onTogglePin?.(e, conv.id, conv.pinned)} title={conv.pinned ? 'Désépingler' : 'Épingler'}
            aria-label={`${conv.pinned ? 'Désépingler' : 'Épingler'} ${conv.title || 'cette conversation'}`}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px', color: conv.pinned ? 'var(--accent-primary)' : 'var(--text-muted)', padding: '2px' }}>{conv.pinned ? '📌' : '📍'}</button>
          <button type="button" onClick={(e) => { e.stopPropagation(); setDraft(conv.title || ''); setEditing(true); }} title="Renommer"
            aria-label={`Renommer ${conv.title || 'cette conversation'}`}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px', color: 'var(--text-muted)', padding: '2px' }}>✏️</button>
          <button type="button" onClick={(e) => onDelete(e, conv.id)} title="Supprimer"
            aria-label={`Supprimer ${conv.title || 'cette conversation'}`}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '14px', color: 'var(--danger)', padding: '2px' }}>×</button>
        </div>
      )}
    </div>
  );
}
