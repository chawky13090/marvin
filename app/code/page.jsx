'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import styles from './code.module.css';

const PHASES = ['planned', 'architected', 'implementing', 'reviewing', 'testing', 'repairing', 'accepted'];
const CODING_API = '/api/coding';
const STORAGE_API = '/api/storage';
const VM_LAB_API = '/api/vm-lab';

function Stat({ label, value, color }) {
  return <div className={styles.stat}><div className={styles.statLabel}>{label}</div><div className={styles.statValue} style={{ color }}>{value}</div></div>;
}

function shortDate(value) {
  if (!value) return 'N/D';
  try { return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)); }
  catch { return String(value); }
}

function statusColor(status) {
  if (status === 'completed' || status === 'current') return '#34d399';
  if (status === 'running') return '#60a5fa';
  if (status === 'queued' || status === 'interrupted' || status === 'blocked') return '#fbbf24';
  if (status === 'failed' || status === 'refresh_error' || status === 'stale') return '#fb7185';
  return '#a1a1aa';
}

export default function CodeWorkspacePage() {
  const [tab, setTab] = useState('projects');
  const [overview, setOverview] = useState(null);
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [draft, setDraft] = useState('');
  const [repositoryPath, setRepositoryPath] = useState('');
  const [repository, setRepository] = useState(null);
  const [autonomy, setAutonomy] = useState('autonomous');
  const [targetMode, setTargetMode] = useState('auto');
  const [creating, setCreating] = useState(false);
  const [hypervForm, setHypervForm] = useState({ vm_name: '', checkpoint_name: 'Marvin-Clean', guest_username: '', guest_password: '' });
  const [storage, setStorage] = useState(null);
  const [vmLab, setVmLab] = useState(null);
  const [vmLabJob, setVmLabJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requestRef = useRef(null);
  const tabsRef = useRef(null);

  const loadDetail = useCallback(async (id, preferredPath = '') => {
    const response = await fetch(`${CODING_API}/projects/${id}`, { signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('Projet de code indisponible');
    const detail = await response.json();
    setSelected(detail);
    const path = preferredPath || detail.manifest?.[0]?.path;
    if (path) {
      const fileResponse = await fetch(`${CODING_API}/projects/${id}/file?path=${encodeURIComponent(path)}`, { signal: AbortSignal.timeout(10000) });
      if (fileResponse.ok) setSelectedFile(await fileResponse.json());
    } else {
      setSelectedFile(null);
    }
  }, []);

  const load = useCallback(async () => {
    setError('');
    try {
      const [overviewResponse, projectsResponse] = await Promise.all([
        fetch(`${CODING_API}/overview`, { signal: AbortSignal.timeout(10000) }),
        fetch(`${CODING_API}/projects`, { signal: AbortSignal.timeout(10000) }),
      ]);
      if (!overviewResponse.ok || !projectsResponse.ok) throw new Error('API Coding Workspace indisponible');
      const overviewData = await overviewResponse.json();
      const projectData = await projectsResponse.json();
      setOverview(overviewData);
      setProjects(projectData.projects || []);
      if (!selected && projectData.projects?.[0]) {
        const requestedMission = typeof window !== 'undefined'
          ? new URLSearchParams(window.location.search).get('mission')
          : '';
        const initial = projectData.projects.find(item => item.id === requestedMission) || projectData.projects[0];
        await loadDetail(initial.id);
      }
    } catch (err) {
      setError(err.message || 'Chargement impossible');
    } finally {
      setLoading(false);
    }
  }, [loadDetail, selected]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    fetch(`${STORAGE_API}/layout`, { signal: AbortSignal.timeout(10000) })
      .then(response => response.ok ? response.json() : Promise.reject(new Error('Bibliothèque Marvin indisponible')))
      .then(setStorage)
      .catch(err => setError(err.message || 'Bibliothèque Marvin indisponible'));
  }, []);
  useEffect(() => {
    Promise.all([
      fetch(`${VM_LAB_API}/status`, { signal: AbortSignal.timeout(30000) }),
      fetch(`${VM_LAB_API}/install`, { signal: AbortSignal.timeout(10000) }),
    ])
      .then(async ([labResponse, jobResponse]) => {
        if (!labResponse.ok || !jobResponse.ok) throw new Error('VM Lab indisponible');
        setVmLab(await labResponse.json());
        setVmLabJob(await jobResponse.json());
      })
      .catch(err => setError(err.message || 'VM Lab indisponible'));
  }, []);
  useEffect(() => {
    if (!vmLabJob?.active) return undefined;
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`${VM_LAB_API}/install`, { signal: AbortSignal.timeout(10000) });
        if (response.ok) setVmLabJob(await response.json());
      } catch { /* Le prochain passage retentera sans masquer le job persistant. */ }
    }, 4000);
    return () => clearInterval(timer);
  }, [vmLabJob?.active]);
  useEffect(() => {
    const id = selected?.project?.id;
    const jobStatus = selected?.auto_job?.status;
    if (!id || (selected.project.status !== 'running' && !['queued', 'running', 'interrupted'].includes(jobStatus))) return undefined;
    let refreshTimer = null;
    let fallbackTimer = null;
    const refresh = () => {
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => loadDetail(id, selectedFile?.path).catch(() => {}), 200);
    };
    const source = new EventSource(
      `${CODING_API}/projects/${id}/events/stream`,
      { withCredentials: true },
    );
    source.addEventListener('mission', refresh);
    source.addEventListener('terminal', () => { refresh(); source.close(); });
    source.onerror = () => {
      if (!fallbackTimer) fallbackTimer = setInterval(refresh, 4000);
    };
    return () => {
      clearTimeout(refreshTimer);
      clearInterval(fallbackTimer);
      source.close();
    };
  }, [selected?.project?.id, selected?.project?.status, selected?.auto_job?.status, selectedFile?.path, loadDetail]);

  const certified = useMemo(() => (overview?.languages || []).filter(item => item.level === 'certified'), [overview]);
  const knowledge = overview?.knowledge?.sources || [];

  function prepareChat(text) {
    const value = String(text || '').trim();
    if (!value) return;
    window.sessionStorage.setItem('marvin:code-draft', value);
    window.location.assign('/');
  }

  async function inspectRepository() {
    setCreating(true);
    setError('');
    try {
      const response = await fetch(`${CODING_API}/repository/inspect`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: repositoryPath }), signal: AbortSignal.timeout(20000),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Analyse du dépôt impossible');
      setRepository(body);
    } catch (err) { setError(err.message || 'Analyse du dépôt impossible'); }
    finally { setCreating(false); }
  }

  async function launchMission() {
    setCreating(true);
    setError('');
    try {
      const response = await fetch(`${CODING_API}/projects`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request: draft.trim(), repository_path: repository?.root || '', autonomy,
          target_mode: targetMode, create_worktree: true,
          start_auto: autonomy === 'autonomous', confirmed: true,
          max_duration_minutes: 120, max_iterations: 12, max_files_changed: 50,
        }), signal: AbortSignal.timeout(120000),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Création de mission impossible');
      const id = body.project.id;
      setRepository(body.repository || repository);
      if (autonomy === 'autonomous') {
        setDraft('');
        await load();
        await loadDetail(id);
      } else {
        prepareChat(`Reprends la Coding Mission ${id} en mode supervisé. Travaille exclusivement dans le worktree ${body.workspace.worktree_root}. Respecte le contrat du dépôt et exécute Test Forge avant livraison.`);
      }
    } catch (err) { setError(err.message || 'Création de mission impossible'); }
    finally { setCreating(false); }
  }

  function activateFeature(feature) {
    if (feature === 'code') {
      requestRef.current?.focus();
      requestRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    setTab(feature === 'tests' ? 'tests' : 'knowledge');
    window.setTimeout(() => tabsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
  }

  async function controlJob(action) {
    const jobId = selected?.auto_job?.id;
    if (!jobId) return;
    setError('');
    try {
      const response = await fetch(`${CODING_API}/jobs/${jobId}/${action}`, { method: 'POST' });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || `Action ${action} impossible`);
      await loadDetail(project.id, selectedFile?.path);
    } catch (err) { setError(err.message || `Action ${action} impossible`); }
  }

  async function configureHyperV() {
    setCreating(true);
    setError('');
    try {
      const response = await fetch(`${CODING_API}/validation/windows/hyperv/configure`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...hypervForm, confirmed: true }), signal: AbortSignal.timeout(60000),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Configuration Hyper-V impossible');
      setHypervForm(previous => ({ ...previous, guest_password: '' }));
      await load();
    } catch (err) { setError(err.message || 'Configuration Hyper-V impossible'); }
    finally { setCreating(false); }
  }

  async function controlDebianResult(action) {
    setCreating(true);
    setError('');
    try {
      const session = overview?.test_forge?.debian_vm?.result_session;
      const response = await fetch(`${CODING_API}/validation/linux/hyperv/session`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, run_id: session?.run_id || '', confirmed: true }),
        signal: AbortSignal.timeout(240000),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Action Debian impossible');
      await load();
    } catch (err) { setError(err.message || 'Action Debian impossible'); }
    finally { setCreating(false); }
  }

  async function ensureStorage() {
    setCreating(true);
    setError('');
    try {
      const response = await fetch(`${STORAGE_API}/layout/ensure`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed: true }), signal: AbortSignal.timeout(60000),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Création de la bibliothèque impossible');
      setStorage(body);
    } catch (err) { setError(err.message || 'Création de la bibliothèque impossible'); }
    finally { setCreating(false); }
  }

  async function verifyLabIsos() {
    setCreating(true);
    setError('');
    try {
      const response = await fetch(`${VM_LAB_API}/verify-isos`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed: true }), signal: AbortSignal.timeout(180000),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Vérification ISO impossible');
      const statusResponse = await fetch(`${VM_LAB_API}/status`, { signal: AbortSignal.timeout(30000) });
      if (!statusResponse.ok) throw new Error('Actualisation VM Lab impossible');
      setVmLab(await statusResponse.json());
    } catch (err) { setError(err.message || 'Vérification ISO impossible'); }
    finally { setCreating(false); }
  }

  async function installLab(profile) {
    const selectedProfile = (vmLab?.profiles || []).find(item => item.id === profile);
    const vmName = selectedProfile?.vm_name || profile;
    if (!window.confirm(`Recréer entièrement ${vmName} et installer son système sans assistance ? La VM portant exactement ce nom sera remplacée.`)) return;
    setCreating(true);
    setError('');
    try {
      const response = await fetch(`${VM_LAB_API}/install`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile, confirmed: true }), signal: AbortSignal.timeout(60000),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Démarrage de l installation impossible');
      setVmLabJob(body);
    } catch (err) { setError(err.message || 'Démarrage de l installation impossible'); }
    finally { setCreating(false); }
  }

  const project = selected?.project;
  const history = project?.history || [];
  const completedPhases = new Set(history.map(item => item.phase));

  return <div className={styles.page}><div className={styles.shell}>
    <header className={styles.header}>
      <div><h1 className={styles.title}>Code Workspace</h1><p className={styles.subtitle}>
        Centre de supervision des projets générés par Marvin : contrat, fichiers, tests isolés, revues, documentation officielle et reprise des missions longues.
      </p></div>
      <div className={styles.status} aria-label="Accès rapides Code Workspace">
        <button className={styles.chipButton} onClick={() => activateFeature('code')}>Code Forge</button>
        <button className={styles.chipButton} onClick={() => activateFeature('tests')}>Test Forge</button>
        <button className={styles.chipButton} onClick={() => activateFeature('knowledge')}>Knowledge Radar</button>
      </div>
    </header>

    <section className={styles.launcher}>
      <div className={styles.launchFields}>
        <div className={styles.repoRow}>
          <input value={repositoryPath} onChange={event => { setRepositoryPath(event.target.value); setRepository(null); }} placeholder="Dépôt Git existant (optionnel). Laisse vide pour un nouveau projet isolé." />
          <button className={styles.secondary} disabled={!repositoryPath.trim() || creating} onClick={inspectRepository}>Analyser le dépôt</button>
        </div>
        <textarea ref={requestRef} value={draft} onChange={event => setDraft(event.target.value)} placeholder="Tape directement ta demande de code. Marvin créera au besoin un projet Git isolé, planifiera, codera, exécutera, testera et réparera avant livraison." />
        {repository && <div className={styles.repoContract}>
          <div><b>{repository.name}</b><span>{repository.root}</span></div>
          <div><b>{repository.file_count} fichiers</b><span>{repository.languages.join(', ') || 'langages à détecter'}</span></div>
          <div><b>{repository.git.branch}</b><span>{repository.git.dirty ? `${repository.git.changed_count} changement(s) locaux exclus du worktree` : 'dépôt propre'}</span></div>
          <div><b>{repository.instructions.length} règle(s)</b><span>{repository.instructions.map(item => item.path).join(', ') || 'aucun AGENTS.md/CLAUDE.md'}</span></div>
        </div>}
        {repository?.warnings?.map(warning => <div className={styles.warning} key={warning}>{warning}</div>)}
      </div>
      <div className={styles.launchActions}>
        <div className={styles.modeSwitch}>
          <button className={autonomy === 'autonomous' ? styles.modeActive : ''} onClick={() => setAutonomy('autonomous')}>Auto</button>
          <button className={autonomy === 'supervised' ? styles.modeActive : ''} onClick={() => setAutonomy('supervised')}>Supervisé</button>
        </div>
        <label className={styles.targetLabel}>Cible d’exécution
          <select value={targetMode} onChange={event => setTargetMode(event.target.value)}>
            <option value="auto">Auto selon la demande</option>
            <option value="linux">Linux / Debian</option>
            <option value="windows">Windows</option>
            <option value="both">Windows et Linux</option>
          </select>
        </label>
        <button className={styles.primary} disabled={!draft.trim() || (!!repositoryPath.trim() && !repository) || creating} onClick={launchMission}>{creating ? 'Préparation…' : autonomy === 'autonomous' ? 'Démarrer dans Code Workspace' : 'Préparer la mission supervisée'}</button>
        {!repositoryPath.trim() && <div className={styles.guardrail}>Nouveau projet : Marvin crée automatiquement un dépôt Git et un worktree isolés. Aucun dossier existant n’est nécessaire.</div>}
        <div className={styles.guardrail}>Auto : mission durable jusqu’au succès, par tranches de 120 min et 50 fichiers maximum. Tests exécutés obligatoires. Pause uniquement sur blocage réel ou confirmation requise.</div>
      </div>
    </section>

    {error && <div className={styles.error}>{error}</div>}
    {overview?.job_store?.degraded && <div className={overview.job_store.available ? styles.warning : styles.error}>
      {overview.job_store.available
        ? 'Le registre des missions Auto a été récupéré depuis sa dernière sauvegarde valide. La copie primaire sera réparée lors de la prochaine écriture.'
        : 'Le registre des missions Auto et sa sauvegarde sont illisibles. Marvin reste disponible, mais aucune mission Auto ne sera reprise avant réparation.'}
    </div>}
    <div className={styles.stats}>
      <Stat label="Projets" value={overview?.projects ?? '—'} color="#60a5fa" />
      <Stat label="En cours" value={overview?.running ?? '—'} color="#fbbf24" />
      <Stat label="Validés" value={overview?.completed ?? '—'} color="#34d399" />
      <Stat label="Langages certifiés" value={certified.length || '—'} color="#c084fc" />
      <Stat label="Sources officielles" value={overview?.knowledge?.source_count ?? '—'} color="#38bdf8" />
    </div>

    <nav className={styles.tabs} ref={tabsRef}>
      {[['projects', 'Projets'], ['tests', 'Test Forge'], ['capabilities', 'Capacités'], ['library', 'Bibliothèque'], ['windows', 'Windows VM'], ['knowledge', 'Documentation']].map(([id, label]) =>
        <button key={id} className={`${styles.tab} ${tab === id ? styles.tabActive : ''}`} onClick={() => setTab(id)}>{label}</button>)}
    </nav>

    {tab === 'projects' && <div className={styles.workspace}>
      <aside className={styles.panel}><div className={styles.panelHeader}>Coding Missions</div><div className={styles.projectList}>
        {projects.map(item => <button key={item.id} className={`${styles.project} ${project?.id === item.id ? styles.projectActive : ''}`} onClick={() => loadDetail(item.id)}>
          <div className={styles.projectTitle}>{item.request}</div>
          <div className={styles.meta}><span style={{ color: statusColor(item.status) }}>{item.status}</span> · {item.phase} · r{item.revision}</div>
          <div className={styles.meta}>{shortDate(item.updated_at)}</div>
        </button>)}
        {!projects.length && !loading && <div className={styles.empty}>Aucune Coding Mission. Prépare un premier projet ci-dessus.</div>}
      </div></aside>

      <main className={styles.panel}>{!project ? <div className={styles.empty}>{loading ? 'Chargement…' : 'Sélectionne un projet.'}</div> : <div className={styles.detail}>
        <div className={styles.detailHead}><div><div className={styles.meta}>MISSION {project.id} · RÉVISION {project.revision}</div><h2 style={{ margin: '7px 0 5px', fontSize: 18 }}>{project.request}</h2><div className={styles.meta}>Mode : {project.autonomy || 'supervised'} · Cibles : {(project.target_platforms || []).join(', ')} · mise à jour {shortDate(project.updated_at)}</div>{selected.workspace && <div className={styles.meta}>Worktree : {selected.workspace.worktree_root} · branche {selected.workspace.branch} · {selected.workspace.changed_count} changement(s)</div>}</div>
          <button className={styles.secondary} onClick={() => prepareChat(`Reprends la Coding Mission ${project.id}. Vérifie son dernier snapshot et poursuis la demande initiale sans recommencer depuis zéro.`)}>Reprendre dans le chat</button>
        </div>
        {selected.evidence_integrity && <div className={selected.evidence_integrity.integrity_level === 'tamper_evident' ? styles.guardrail : styles.warning}>
          {selected.evidence_integrity.integrity_level === 'tamper_evident'
            ? `Preuves vérifiables · ${selected.evidence_integrity.records} événement(s) chaîné(s) · conservation avec la mission`
            : selected.evidence_integrity.integrity_level === 'mixed_legacy_unsigned'
              ? `Registre cohérent · ${selected.evidence_integrity.signed_records} preuve(s) chaînée(s) · ${selected.evidence_integrity.legacy_records} événement(s) historiques non signés dont l’intégrité antérieure ne peut pas être attestée`
              : `Intégrité des preuves compromise · ${selected.evidence_integrity.corrupt_lines || 0} ligne(s) corrompue(s) · toute nouvelle livraison est bloquée`}
        </div>}
        <div className={styles.phases}>{PHASES.map(phase => <div key={phase} className={`${styles.phase} ${completedPhases.has(phase) || project.phase === phase ? styles.phaseDone : ''}`}>{phase}</div>)}</div>
        {selected.auto_job && <section className={styles.autoJob}>
          <div className={styles.autoHead}><div><div className={styles.panelHeader} style={{ padding: 0, border: 0 }}>Superviseur Auto · {project.completion_policy || 'until_success'}</div><div className={styles.meta}>{selected.auto_job.id} · tentative {selected.auto_job.attempts} · échecs consécutifs {selected.auto_job.consecutive_failures || 0} · {Math.round(selected.auto_job.elapsed_seconds || 0)} s consommées</div></div>
            <div className={styles.jobActions}>{['queued', 'running'].includes(selected.auto_job.status) && <button className={styles.secondary} onClick={() => controlJob('cancel')}>Arrêter</button>}{['interrupted', 'failed', 'cancelled', 'blocked'].includes(selected.auto_job.status) && <button className={styles.secondary} onClick={() => controlJob('resume')}>Reprendre</button>}</div>
          </div>
          <div className={styles.progressTrack}><span style={{ width: `${selected.auto_job.progress?.percent || 0}%` }} /></div>
          <div className={styles.jobStatus}><b style={{ color: statusColor(selected.auto_job.status) }}>{selected.auto_job.status}</b><span>{selected.auto_job.progress?.stage || 'queued'}</span><span>{selected.auto_job.error || 'Aucune erreur'}</span></div>
          {!!selected.auto_job.evidence_gaps?.length && <div className={styles.warning}>
            {selected.auto_job.evidence_gaps.length} preuve(s) d’exécution n’ont pas pu être
            enregistrées. L’étape n’a pas été rejouée automatiquement ; vérifiez l’état réel
            avant toute reprise.
          </div>}
        </section>}
        {selected.auto_job?.result?.definition_of_done && <section className={styles.autoJob}>
          <div className={styles.panelHeader} style={{ padding: 0, border: 0 }}>Definition of Done</div>
          <div className={styles.jobStatus}>
            {Object.entries(selected.auto_job.result.definition_of_done.checks || {}).map(([name, passed]) =>
              <span key={name} style={{ color: passed ? '#34d399' : '#fb7185' }}>{passed ? 'Réussi' : 'Refusé'} · {name.replaceAll('_', ' ')}</span>)}
          </div>
        </section>}
        {selected.delivery_pack && <section className={styles.autoJob}>
          <div className={styles.panelHeader} style={{ padding: 0, border: 0 }}>Delivery Pack</div>
          <div className={styles.jobStatus}>
            <b style={{ color: selected.delivery_pack.status === 'accepted' ? '#34d399' : '#fb7185' }}>{selected.delivery_pack.status}</b>
            <span>{selected.delivery_pack.manifest?.length || 0} fichier(s)</span>
            <span>{(selected.delivery_pack.targets || []).join(', ')}</span>
            <span>{selected.delivery_pack.documentation_manifest?.source_count || selected.delivery_pack.documentation_manifest?.sources?.length || 0} source(s) documentaire(s)</span>
          </div>
        </section>}
        <div className={styles.split}>
          <div className={styles.files}><div className={styles.panelHeader}>Dernier snapshot · {selected.manifest.length} fichier(s)</div>{selected.manifest.map(file => <button key={file.path} className={`${styles.file} ${selectedFile?.path === file.path ? styles.fileActive : ''}`} onClick={async () => {
            const response = await fetch(`${CODING_API}/projects/${project.id}/file?path=${encodeURIComponent(file.path)}`);
            if (response.ok) setSelectedFile(await response.json());
          }}>{file.path}<span className={styles.meta} style={{ display: 'block' }}>{file.bytes} octets · {file.sha256?.slice(0, 10)}</span></button>)}</div>
          <pre className={styles.code}>{selectedFile?.content || 'Aucun fichier disponible à cette phase.'}</pre>
        </div>
        <div className={styles.timeline}><div className={styles.panelHeader}>Chronologie et preuves</div>{history.slice().reverse().slice(0, 30).map(item => <div className={styles.event} key={item.revision}><span>{shortDate(item.at)}</span><b style={{ color: statusColor(item.phase === 'accepted' ? 'completed' : project.status) }}>{item.phase}</b><span>{item.state?.score != null ? `score ${item.state.score}/10 · ` : ''}{item.state?.test_production_ready != null ? `production ${item.state.test_production_ready ? 'validée' : 'refusée'} · ` : ''}{item.manifest?.length ? `${item.manifest.length} fichier(s)` : 'checkpoint'}</span></div>)}</div>
        {selected.repair_ledger?.length > 0 && <div className={styles.timeline}>
          <div className={styles.panelHeader}>Registre des réparations</div>
          {selected.repair_ledger.slice().reverse().slice(0, 20).map((item, index) => {
            const payload = item.payload || {};
            const repair = payload.repair_context || {};
            const failed = repair.failed_steps || payload.definition_of_done?.failures || [];
            return <div className={styles.event} key={`${item.sequence || item.at}-${index}`}>
              <span>{shortDate(item.at)}</span>
              <b>{item.type}</b>
              <span>{failed.length ? failed.join(', ') : repair.category || `tentative ${payload.attempt || '-'}`}</span>
            </div>;
          })}
        </div>}
      </div>}</main>
    </div>}

    {tab === 'tests' && <div className={styles.windowsGrid}>
      <article className={styles.card}>
        <div className={styles.cardTitle}>Debian 13 jetable</div>
        <div className={styles.check}><span>VM native systemd</span><b style={{ color: overview?.test_forge?.debian_vm?.ready ? '#34d399' : '#fbbf24' }}>{overview?.test_forge?.debian_vm?.ready ? 'prête' : 'non prête'}</b></div>
        <div className={styles.check}><span>Base saine</span><b>{overview?.test_forge?.debian_vm?.checkpoint_name || 'Marvin-Clean'}</b></div>
        <div className={styles.check}><span>Moteur Docker</span><b style={{ color: overview?.test_forge?.docker?.available ? '#34d399' : '#fb7185' }}>{overview?.test_forge?.docker?.available ? 'disponible' : 'indisponible'}</b></div>
        <div className={styles.check}><span>Image d’intégration</span><b className={styles.pathValue}>{overview?.test_forge?.debian_online_image || 'chargement'}</b></div>
        <div className={styles.check}><span>Contrôles rapides</span><b>conteneurs hors ligne</b></div>
        <div className={styles.check}><span>Installeurs et dépendances</span><b>Internet contrôlé obligatoire</b></div>
        {overview?.test_forge?.debian_vm?.error && <div className={styles.warning}>{overview.test_forge.debian_vm.error}</div>}
        {overview?.test_forge?.debian_vm?.result_session?.status === 'result_available' && <div className={styles.jobActions}>
          <button className={styles.primary} disabled={creating} onClick={() => controlDebianResult('open')}>Ouvrir le résultat dans la VM</button>
          <button className={styles.secondary} disabled={creating} onClick={() => controlDebianResult('restore')}>Supprimer le résultat</button>
        </div>}
        {overview?.test_forge?.debian_vm?.result_session?.status === 'manual_active' && <div className={styles.jobActions}>
          <button className={styles.primary} disabled={creating} onClick={() => controlDebianResult('restore')}>Restaurer la base saine</button>
        </div>}
        <div className={styles.guardrail}>Docker filtre rapidement la syntaxe et les tests simulés. Les scripts utilisant systemd ou des services passent ensuite dans la VM Debian restaurée avant et après exécution. Un snapshot temporaire du résultat peut être ouvert manuellement sans contaminer la base saine.</div>
      </article>
      <article className={styles.card}>
        <div className={styles.cardTitle}>Windows natif</div>
        <div className={styles.check}><span>Runner</span><b>{overview?.windows_validation?.backend || overview?.windows_validation?.hyperv?.backend || 'non configuré'}</b></div>
        <div className={styles.check}><span>État</span><b style={{ color: overview?.windows_validation?.production_ready || overview?.windows_validation?.hyperv?.ready ? '#34d399' : '#fbbf24' }}>{overview?.windows_validation?.production_ready || overview?.windows_validation?.hyperv?.ready ? 'prêt' : 'non prêt'}</b></div>
        <div className={styles.check}><span>Certification</span><b>exécution native exigée</b></div>
        <div className={styles.guardrail}>Une analyse statique ou une compilation croisée ne suffit jamais à certifier un livrable Windows. Le détail et la configuration du runner restent disponibles dans l’onglet Windows VM.</div>
      </article>
      <article className={styles.card}>
        <div className={styles.cardTitle}>Règle de preuve</div>
        <div className={styles.check}><span>Succès</span><b>reçu Test Forge explicite</b></div>
        <div className={styles.check}><span>Échec</span><b>bloque la livraison</b></div>
        <div className={styles.check}><span>Mission Auto</span><b>répare puis reteste</b></div>
        <div className={styles.guardrail}>Marvin ne doit plus transformer un résultat d’outil en échec en succès narratif. Les preuves restent visibles dans la chronologie de chaque Coding Mission.</div>
      </article>
    </div>}

    {tab === 'capabilities' && <div className={styles.grid}>{(overview?.languages || []).map(item => <article className={styles.card} key={item.language}>
      <div className={styles.cardTitle}>{item.language}<span className={styles.chip} style={{ float: 'right', color: statusColor(item.level === 'certified' ? 'completed' : '') }}>{item.level}</span></div>
      <div className={styles.meta}>{item.toolchain}</div>
      <div className={styles.check}><span>Cibles exécutées</span><b>{item.targets?.join(', ') || 'aucune'}</b></div>
      {!!item.cross_targets?.length && <div className={styles.check}><span>Cross-compilation</span><b>{item.cross_targets.join(', ')}</b></div>}
      <div className={styles.check}><span>Contrôles</span><b style={{ textAlign: 'right' }}>{item.checks?.join(', ') || 'planifiés'}</b></div>
    </article>)}</div>}

    {tab === 'library' && <div className={styles.windowsGrid}>
      <article className={styles.card}>
        <div className={styles.cardTitle}>Bibliothèque technique locale</div>
        <div className={styles.check}><span>Racine</span><b className={styles.pathValue}>{storage?.machine_root || 'chargement'}</b></div>
        <div className={styles.check}><span>Disque</span><b>{storage?.machine?.drive_type || 'inconnu'}</b></div>
        <div className={styles.check}><span>Espace libre</span><b>{storage?.machine?.free_bytes ? `${(storage.machine.free_bytes / 1073741824).toFixed(1)} Gio` : 'inconnu'}</b></div>
        <div className={styles.check}><span>ISO Windows</span><b className={styles.pathValue}>{storage?.directories?.iso_windows || 'chargement'}</b></div>
        <div className={styles.check}><span>ISO Linux</span><b className={styles.pathValue}>{storage?.directories?.iso_linux || 'chargement'}</b></div>
        <div className={styles.check}><span>VM Windows</span><b className={styles.pathValue}>{storage?.directories?.vm_windows || 'chargement'}</b></div>
        <div className={styles.check}><span>VM Linux</span><b className={styles.pathValue}>{storage?.directories?.vm_linux || 'chargement'}</b></div>
        <button className={styles.primary} style={{ minHeight: 42, marginTop: 12 }} disabled={creating || !storage?.machine?.valid} onClick={ensureStorage}>Créer ou vérifier les dossiers</button>
        {storage?.machine?.issues?.map(issue => <div className={styles.warning} key={issue}>{issue}</div>)}
      </article>
      <article className={styles.card}>
        <div className={styles.cardTitle}>Exports et inventaire</div>
        <div className={styles.check}><span>Documents utilisateur</span><b className={styles.pathValue}>{storage?.export_root || 'chargement'}</b></div>
        {(storage?.iso_inventory || []).map(iso => <div className={styles.check} key={iso.path}><span>{iso.category}</span><b className={styles.pathValue}>{iso.name} · {(iso.size_bytes / 1073741824).toFixed(2)} Gio</b></div>)}
        {!storage?.iso_inventory?.length && <div className={styles.empty}>Aucune ISO classée pour le moment.</div>}
        <div className={styles.guardrail}>Les ISO, VHDX, caches et worktrees restent sur un disque local fixe. Les documents, rapports et livrables destinés à l’utilisateur sont exportés séparément.</div>
      </article>
      <article className={styles.card}>
        <div className={styles.cardTitle}>VM Lab Hyper-V</div>
        <div className={styles.check}><span>Accès Hyper-V</span><b style={{ color: vmLab?.hyperv?.access ? '#34d399' : '#fb7185' }}>{vmLab?.hyperv?.access ? 'disponible' : 'indisponible'}</b></div>
        <div className={styles.check}><span>Réseau d’installation</span><b>{vmLab?.installation_switch || 'absent'}</b></div>
        <div className={styles.check}><span>Capacité combinée</span><b style={{ color: vmLab?.combined_capacity_ready ? '#34d399' : '#fbbf24' }}>{vmLab?.combined_capacity_ready ? 'suffisante' : 'insuffisante'}</b></div>
        {(vmLab?.profiles || []).map(profile => <div className={styles.check} key={profile.id}>
          <span>{profile.id}</span><b style={{ color: profile.iso_verified ? '#34d399' : '#fbbf24' }}>{profile.iso_present ? profile.iso_verified ? 'ISO vérifiée' : 'ISO à vérifier' : 'ISO absente'}</b>
        </div>)}
        <button className={styles.primary} style={{ minHeight: 42, marginTop: 12 }} disabled={creating} onClick={verifyLabIsos}>Vérifier les empreintes ISO</button>
        {(vmLab?.profiles || []).map(profile => <button key={`install-${profile.id}`} className={styles.primary} style={{ minHeight: 42, marginTop: 8 }} disabled={creating || vmLabJob?.active || !profile.iso_verified || !profile.capacity_ready} onClick={() => installLab(profile.id)}>
          {vmLabJob?.active && vmLabJob.profile === profile.id ? `Installation ${profile.id} en cours` : `Installer ou recréer ${profile.id}`}
        </button>)}
        {vmLabJob && <div className={styles.check} style={{ marginTop: 10 }}><span>Job VM Lab</span><b style={{ color: statusColor(vmLabJob.status) }}>{vmLabJob.status}{vmLabJob.profile ? ` · ${vmLabJob.profile}` : ''}</b></div>}
        {vmLabJob?.error && <div className={styles.warning}>{vmLabJob.error}</div>}
        {vmLabJob?.log_tail && <pre className={styles.code}>{vmLabJob.log_tail}</pre>}
        <div className={styles.guardrail} style={{ marginTop: 10 }}>Marvin pilote l’installation persistante et ne recrée que la VM explicitement confirmée. Le réseau physique de l’hôte reste inchangé ; seul l’accès réseau de l’invité est utilisé pendant l’installation.</div>
      </article>
    </div>}

    {tab === 'windows' && <div className={styles.windowsGrid}>
      <article className={styles.card}>
        <div className={styles.cardTitle}>Runner Windows natif</div>
        <div className={styles.check}><span>Backend</span><b>{overview?.windows_validation?.hyperv?.backend || 'hyperv_powershell_direct'}</b></div>
        <div className={styles.check}><span>État</span><b style={{ color: overview?.windows_validation?.hyperv?.ready ? '#34d399' : '#fbbf24' }}>{overview?.windows_validation?.hyperv?.ready ? 'prêt' : 'non prêt'}</b></div>
        <div className={styles.check}><span>VM</span><b>{overview?.windows_validation?.hyperv?.vm_name || 'non configurée'}</b></div>
        <div className={styles.check}><span>Checkpoint</span><b>{overview?.windows_validation?.hyperv?.checkpoint_name || 'non configuré'}</b></div>
        <div className={styles.check}><span>Secret invité</span><b>{overview?.windows_validation?.hyperv?.credential_present ? 'DPAPI présent' : 'absent'}</b></div>
        <div className={styles.check}><span>Réseau pendant les tests</span><b>déconnecté par l’hôte</b></div>
        {overview?.windows_validation?.hyperv?.error && <div className={styles.warning}>{overview.windows_validation.hyperv.error}</div>}
      </article>
      <article className={styles.card}>
        <div className={styles.cardTitle}>Associer une VM existante</div>
        <div className={styles.formStack}>
          <input value={hypervForm.vm_name} onChange={event => setHypervForm(value => ({ ...value, vm_name: event.target.value }))} placeholder="Nom exact de la VM Hyper-V" />
          <input value={hypervForm.checkpoint_name} onChange={event => setHypervForm(value => ({ ...value, checkpoint_name: event.target.value }))} placeholder="Checkpoint propre" />
          <input value={hypervForm.guest_username} onChange={event => setHypervForm(value => ({ ...value, guest_username: event.target.value }))} placeholder="Compte Windows invité non administrateur" autoComplete="username" />
          <input type="password" value={hypervForm.guest_password} onChange={event => setHypervForm(value => ({ ...value, guest_password: event.target.value }))} placeholder="Mot de passe invité — chiffré par DPAPI" autoComplete="new-password" />
          <button className={styles.primary} disabled={creating || !hypervForm.vm_name || !hypervForm.checkpoint_name || !hypervForm.guest_username || !hypervForm.guest_password} onClick={configureHyperV}>Enregistrer et vérifier</button>
        </div>
        <div className={styles.guardrail} style={{ marginTop: 10 }}>Le mot de passe n’est jamais retourné par l’API. Le runner exige un compte invité non administrateur et utilise PowerShell Direct, sans port réseau de contrôle.</div>
      </article>
    </div>}

    {tab === 'knowledge' && <div className={styles.grid}>
      {overview?.knowledge?.evidence_integrity && <div className={overview.knowledge.evidence_integrity.integrity_level === 'tamper_evident' ? styles.guardrail : styles.warning}>
        {overview.knowledge.evidence_integrity.integrity_level === 'tamper_evident'
          ? `Preuves Radar vérifiables · ${overview.knowledge.evidence_integrity.records} changement(s) chaîné(s)`
          : overview.knowledge.evidence_integrity.integrity_level === 'mixed_legacy_unsigned'
            ? `Registre Radar cohérent · ${overview.knowledge.evidence_integrity.signed_records} preuve(s) chaînée(s) · ${overview.knowledge.evidence_integrity.legacy_records} événement(s) historiques non signés`
            : `Intégrité des preuves Radar compromise · ${overview.knowledge.evidence_integrity.corrupt_lines || 0} ligne(s) corrompue(s)`}
      </div>}
      {knowledge.map(source => <article className={styles.card} key={source.id}>
      <div className={styles.cardTitle}>{source.title || source.id}</div><div className={styles.meta}>{source.language} · {source.kind}</div>
      <div className={styles.check}><span>Fraîcheur</span><b style={{ color: statusColor(source.freshness) }}>{source.freshness}</b></div>
      <div className={styles.check}><span>Actualisée</span><b>{shortDate(source.retrieved_at)}</b></div>
      <div className={styles.check}><span>SHA-256</span><b>{source.content_sha256?.slice(0, 14)}</b></div>
      <a href={source.url} target="_blank" rel="noreferrer" style={{ display: 'block', marginTop: 10, color: '#60a5fa', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis' }}>{source.url}</a>
    </article>)}{!knowledge.length && <div className={styles.empty}>Le Radar n’a pas encore actualisé ses sources.</div>}</div>}
  </div></div>;
}
