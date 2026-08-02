'use client';
import { useMemo, useState } from 'react';
import FileExplorerCard from './FileExplorerCard';
import PrettyResult from './PrettyResult';
import CodingMissionTracker from './CodingMissionTracker';
import GeneratedFileCard, { DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS } from './GeneratedFileCard';
import { CircleGauge, BarRow, StatCard } from '@/components/ui/DashboardKit';
import { renderSafeMarkdown } from '@/lib/chat/markdown';

function CollapsibleDetail({ label, children }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: '8px' }}>
      <div
        onClick={() => setOpen(!open)}
        style={{ cursor: 'pointer', userSelect: 'none', fontSize: '11px', color: 'var(--accent-primary)', fontWeight: 600 }}
      >
        {open ? '▲' : '▼'} {label}
      </div>
      {open && <div style={{ marginTop: '6px' }}>{children}</div>}
    </div>
  );
}

function MarkdownBlock({ text }) {
  const html = useMemo(() => renderSafeMarkdown(text), [text]);
  return <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-primary)', lineHeight: 1.5 }} dangerouslySetInnerHTML={{ __html: html }} />;
}

// ─── Rendu structuré des résultats d'outils ───
export function renderToolResult(toolName, result) {
  if (!result) return null;
  if (typeof result === 'string') {
    try { result = JSON.parse(result); } catch { return <span>{result}</span>; }
  }

  // Désencapsuler le format du SDK ( { type: 'json', value: ... } )
  if (result && typeof result === 'object' && result.type === 'json' && result.value !== undefined) {
    result = result.value;
  }

  // Erreur
  if (result.error) {
    return (
      <div style={{ color: 'var(--danger)', display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span>❌</span> {typeof result.error === 'string' ? result.error : JSON.stringify(result.error)}
      </div>
    );
  }

  if (['code_workspace_start', 'code_workspace_status', 'code_workspace_control'].includes(toolName)) {
    return <CodingMissionTracker result={result} />;
  }

  // ── Image inline (screenshot embed, infographic) ─────
  if (result.image && result.image.startsWith('data:image/')) {
    return (
      <div>
        {result.message && (
          <div style={{ fontSize: 'var(--font-xs)', color: 'var(--success)', marginBottom: '8px' }}>✅ {result.message}</div>
        )}
        <img
          src={result.image}
          alt="Capture"
          style={{ maxWidth: '100%', maxHeight: '400px', borderRadius: '8px', border: '1px solid var(--border)', cursor: 'pointer' }}
          onClick={() => window.open(result.image, '_blank')}
        />
      </div>
    );
  }

  // ── web_deep_research (v2.142) ─────
  if (toolName === 'web_deep_research' && result.answer) {
    const coverage = result.source_coverage || {};
    return (
      <div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 9 }}>
          <span style={{ fontSize: 10, padding: '3px 7px', borderRadius: 999, background: 'rgba(20,184,166,.12)', color: '#5eead4' }}>
            {result.engine_version === 'v3' ? 'Recherche vérifiée v3' : 'Recherche approfondie'}
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            {coverage.queries_executed ?? result.rounds ?? 1} requête(s)
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            {coverage.pages_read ?? (result.sources || []).length} page(s) lue(s)
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            {(result.sources || []).length} source(s) unique(s)
          </span>
          {coverage.pages_rejected != null && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              {coverage.pages_rejected} rejet(s)
            </span>
          )}
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.sources || []).length > 0 && (
          <CollapsibleDetail label={`Sources (${result.sources.length})`}>
            {result.sources.map((s, i) => (
              <div key={i} style={{ fontSize: '11px', marginBottom: '4px' }}>
                <a href={s.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)' }}>
                  [{i + 1}] {s.title || s.url}
                </a>
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  if (toolName === 'ai_research_swarm' && result.answer) {
    const coverage = result.source_coverage || {};
    const forge = result.forge || {};
    return (
      <div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 9 }}>
          <span style={{ fontSize: 10, padding: '3px 7px', borderRadius: 999, background: 'rgba(20,184,166,.12)', color: '#5eead4' }}>
            {result.engine_version === 'v3' ? 'Recherche adaptative v3' : 'Research Swarm v2'}
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{(result.sources || []).length} sources</span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{coverage.unique_domains || 0} domaines</span>
          {forge.citation_validity != null && (
            <span style={{ fontSize: 10, color: forge.gate_passed ? '#34d399' : '#fbbf24' }}>
              {Math.round(forge.citation_validity * 100)} % de citations valides
            </span>
          )}
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.sources || []).length > 0 && (
          <CollapsibleDetail label={`Sources et preuves (${result.sources.length})`}>
            {result.sources.map((source, index) => (
              <div key={source.url || index} style={{ fontSize: 11, marginBottom: 6 }}>
                <a href={source.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)' }}>
                  [{source.id || source.citation || index + 1}] {source.title || source.url}
                </a>
                {source.source_type && <span style={{ marginLeft: 6, color: 'var(--text-muted)' }}>{source.source_type}</span>}
              </div>
            ))}
          </CollapsibleDetail>
        )}
        {(result.queries || []).length > 0 && (
          <CollapsibleDetail label={`Trajectoire de recherche (${result.queries.length})`}>
            {result.queries.map((query, index) => (
              <div key={query.id || index} style={{ fontSize: 11, marginBottom: 5, color: 'var(--text-secondary)' }}>
                {index + 1}. {query.query} · {query.accepted_sources || 0} source(s) retenue(s)
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  // ── ai_model_council (v2.141) — Panel d'experts IA ─────
  if (toolName === 'ai_model_council' && result.answer) {
    return (
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
          🧑‍🤝‍🧑 {(result.models_consulted || []).length} modèle(s) consulté(s) en parallèle
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.individual_answers || []).length > 0 && (
          <CollapsibleDetail label="Voir les réponses individuelles">
            {result.individual_answers.map((a, i) => (
              <div key={i} style={{ padding: '8px 10px', marginBottom: '6px', background: 'var(--bg-tertiary)', borderRadius: '6px', borderLeft: '3px solid var(--accent-primary)' }}>
                <div style={{ fontWeight: 600, fontSize: '11px', color: 'var(--accent-primary)', marginBottom: '4px', fontFamily: 'monospace' }}>{a.model}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{a.answer}</div>
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  if (toolName === 'ai_adaptive_team' && result.answer) {
    return (
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
          Équipe adaptative · {(result.stages || []).filter(stage => stage.success).length}/{(result.stages || []).length} étape(s)
          {(result.models_consulted || []).length ? ` · ${result.models_consulted.length} modèle(s)` : ''}
          {result.evidence_quality?.epistemic_debt != null ? ` · dette de preuve ${Math.round(result.evidence_quality.epistemic_debt * 100)} %` : ''}
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.stages || []).length > 0 && (
          <CollapsibleDetail label="Voir le raisonnement de l’équipe">
            {result.stages.map((stage, index) => (
              <div key={`${stage.name}-${index}`} style={{ padding: '8px 10px', marginBottom: 6, borderRadius: 7, background: 'var(--bg-tertiary)', borderLeft: `3px solid ${stage.success ? '#34d399' : '#f87171'}` }}>
                <div style={{ fontWeight: 700, fontSize: 11 }}>{index + 1}. {stage.name} · {stage.success ? 'réussi' : 'échoué'}</div>
                {stage.error && <div style={{ color: '#f87171', fontSize: 11, marginTop: 4 }}>{stage.error}</div>}
                {stage.answer && <div style={{ color: 'var(--text-secondary)', fontSize: 11, marginTop: 5, whiteSpace: 'pre-wrap', maxHeight: 180, overflowY: 'auto' }}>{stage.answer}</div>}
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  if (toolName === 'ai_code_forge' && result.answer) {
    const validation = result.validation || {};
    const testReport = result.test_report || {};
    return (
      <div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
          Code Forge · {result.language || 'langage détecté'}
          {validation.syntax_valid === true ? ' · syntaxe validée' : validation.syntax_valid === false ? ' · syntaxe invalide' : ' · analyseur indisponible'}
          {` · ${result.critical_issues || 0} critique(s) restante(s)`}
          {result.final_review?.score != null ? ` · gate final ${result.final_review.score}/10` : ''}
          {testReport.production_ready === true ? ' · tests isolés réussis' : ' · tests isolés non validés'}
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.reviews || []).length > 0 && (
          <CollapsibleDetail label="Voir les revues indépendantes">
            {result.reviews.map((review, index) => (
              <div key={index} style={{ padding: '8px 10px', marginBottom: 6, background: 'var(--bg-tertiary)', borderRadius: 7 }}>
                <div style={{ fontWeight: 700, fontSize: 11 }}>{review.model || `Reviewer ${index + 1}`} · {review.score}/10</div>
                {(review.issues || []).map((issue, issueIndex) => (
                  <div key={issueIndex} style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 5 }}>
                    [{issue.severity}] {issue.problem}
                  </div>
                ))}
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  if (toolName === 'ai_test_forge' && Array.isArray(result.steps)) {
    return (
      <div>
        <div style={{ fontSize: 11, color: result.production_ready ? '#34d399' : '#f87171', marginBottom: 8, fontWeight: 700 }}>
          Test Forge · {result.language || 'langage inconnu'} · {result.production_ready ? 'prêt production' : 'refusé'}
        </div>
        {(result.steps || []).map((step, index) => (
          <div key={`${step.name}-${index}`} style={{ padding: '7px 9px', marginBottom: 6, borderRadius: 7, background: 'var(--bg-tertiary)', borderLeft: `3px solid ${step.passed ? '#34d399' : '#f87171'}` }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>{step.name} · {step.passed ? 'réussi' : 'échoué'} · code {step.exit_code}</div>
            {step.stderr && <div style={{ marginTop: 4, color: 'var(--text-secondary)', fontSize: 10, whiteSpace: 'pre-wrap', maxHeight: 120, overflowY: 'auto' }}>{step.stderr}</div>}
          </div>
        ))}
        {result.error && <div style={{ color: '#f87171', fontSize: 11 }}>{result.error}</div>}
      </div>
    );
  }

  // ── ai_subagents_run (v2.145) — sous-tâches parallèles ─────
  if (toolName === 'ai_subagents_run' && result.answer) {
    return (
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
          🧩 {(result.subtasks || []).length} sous-tâche(s) traitée(s) en parallèle
        </div>
        <MarkdownBlock text={result.answer} />
        {(result.subtask_results || []).length > 0 && (
          <CollapsibleDetail label="Voir le détail par sous-tâche">
            {result.subtask_results.map((s, i) => (
              <div key={i} style={{ padding: '8px 10px', marginBottom: '6px', background: 'var(--bg-tertiary)', borderRadius: '6px', borderLeft: '3px solid var(--accent-primary)' }}>
                <div style={{ fontWeight: 600, fontSize: '11px', color: 'var(--text-primary)', marginBottom: '4px' }}>{s.subtask}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{s.result}</div>
              </div>
            ))}
          </CollapsibleDetail>
        )}
      </div>
    );
  }

  // ── long_task_start (v2.145) — checklist de la tâche longue ─────
  if (toolName === 'long_task_start' && Array.isArray(result.steps)) {
    return (
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
          🗂️ {result.steps.length} étape(s) — reprise automatique toutes les 5 min
        </div>
        {result.steps.map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', fontSize: '11px', marginBottom: '4px', color: 'var(--text-secondary)' }}>
            <span>☐</span><span>{s}</span>
          </div>
        ))}
      </div>
    );
  }

  // ── long_task_status (v2.145) — avancement des tâches longues ─────
  if (toolName === 'long_task_status' && Array.isArray(result.groups)) {
    if (result.groups.length === 0) {
      return <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>Aucune tâche longue en cours.</span>;
    }
    return (
      <div>
        {result.groups.map((g, gi) => (
          <div key={gi} style={{ marginBottom: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              <span>{g.tag}</span>
              <span>{g.done}/{g.total}</span>
            </div>
            <div style={{ height: '4px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden', marginBottom: '6px' }}>
              <div style={{ height: '100%', width: `${g.total ? (g.done / g.total) * 100 : 0}%`, background: 'var(--success)' }} />
            </div>
            {(g.steps || []).map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', fontSize: '11px', marginBottom: '2px', color: s.status === 'done' ? 'var(--text-muted)' : 'var(--text-secondary)', textDecoration: s.status === 'done' ? 'line-through' : 'none' }}>
                <span>{s.status === 'done' ? '☑' : '☐'}</span><span>{s.title}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    );
  }

  // ── web_search ─────
  if (toolName === 'web_search' && result.results) {
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          🔍 {result.count || result.results.length} résultat(s) — {result.provider || 'Web'}
        </div>
        {result.results.map((r, i) => (
          <div key={i} style={{ padding: '6px 10px', marginBottom: '6px', background: 'var(--bg-tertiary)', borderRadius: '6px', borderLeft: '3px solid var(--accent-primary)' }}>
            <div style={{ fontWeight: 600, fontSize: 'var(--font-xs)', color: 'var(--accent-primary)' }}>
              <a href={r.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)', textDecoration: 'none' }}>{r.title}</a>
            </div>
            {r.snippet && <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>{r.snippet}</div>}
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', wordBreak: 'break-all' }}>{r.url}</div>
          </div>
        ))}
      </div>
    );
  }

  // ── web_browse ─────
  if (toolName === 'web_browse' && result.content) {
    return (
      <div>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '4px' }}>
          🌐 <a href={result.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)' }}>{result.title || result.url}</a>
        </div>
        <pre style={{ background: 'var(--bg-tertiary)', padding: '8px 12px', borderRadius: '6px', fontSize: '11px', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-family)', color: 'var(--text-secondary)', maxHeight: '200px', overflowY: 'auto' }}>
          {result.content.substring(0, 2000)}{result.content.length > 2000 && '\n...'}
        </pre>
      </div>
    );
  }

  // ── Google Drive / OneDrive list ─────
  if ((toolName.startsWith('google_drive') || toolName.startsWith('onedrive')) && result.files) {
    const icon = toolName.startsWith('google') ? '🔴' : '🔵';
    return (
      <div style={{ maxHeight: '250px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>{icon} {result.count || result.files.length} fichier(s)</div>
        {result.files.map((f, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 'var(--font-xs)' }}>
            <span>{f.type === 'dossier' ? '📁' : '📄'}</span>
            <span style={{ color: 'var(--text-primary)', flex: 1 }}>{f.name}</span>
            {f.size > 0 && <span style={{ color: 'var(--text-muted)' }}>{(f.size / 1024).toFixed(0)} Ko</span>}
          </div>
        ))}
      </div>
    );
  }

  // ── system_search (Windows index, ULTRA-FAST) ─────
  if (toolName === 'system_search' && Array.isArray(result.results)) {
    return (
      <FileExplorerCard
        title={`🚀 Recherche "${result.query || ''}"`}
        items={result.results}
        method={result.method}
        elapsedMs={result.elapsed_ms}
      />
    );
  }

  // ── file_find (glob search) ─────
  if (toolName === 'file_find' && Array.isArray(result.results)) {
    return (
      <FileExplorerCard
        title={`🔭 Motif "${result.pattern || ''}" dans ${result.root || result.scope || 'le système'}`}
        items={result.results}
        method={result.method}
      />
    );
  }

  // ── file_list ─────
  if (toolName === 'file_list' && (result.files || result.entries)) {
    const items = (result.files || result.entries || []).map(f => ({
      name: f.name,
      path: f.path || `${result.currentDir || result.path || ''}\\${f.name}`,
      is_dir: f.type === 'dossier' || f.type === 'folder' || f.is_dir,
      size: f.size_bytes || (typeof f.size === 'number' ? f.size : 0),
      extension: f.extension || '',
    }));
    return (
      <FileExplorerCard
        title={`📂 ${result.currentDir || result.path || 'Dossier'}`}
        items={items}
        directory={result.currentDir || result.path}
        nextOffset={result.has_more ? result.next_offset : null}
        totalCount={result.total_count ?? result.count ?? items.length}
      />
    );
  }

  // ── file_search / file_search_text ─────
  if ((toolName === 'file_search' || toolName === 'file_search_text') && (result.results || result.files)) {
    const items = result.results || result.files || [];
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          🔍 {result.count || items.length} résultat(s) trouvé(s)
        </div>
        {items.slice(0, 20).map((item, i) => (
          <div key={i} style={{
            padding: '6px 10px', marginBottom: '4px',
            background: 'var(--bg-tertiary)', borderRadius: '6px',
            borderLeft: '3px solid var(--accent-secondary)',
          }}>
            <div style={{ fontWeight: 600, fontSize: 'var(--font-xs)', color: 'var(--text-primary)' }}>
              📄 {item.name}
            </div>
            {item.snippet && (
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px', fontStyle: 'italic' }}>
                "{item.snippet}"
              </div>
            )}
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
              {item.path}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // ── file_read ─────
  if (toolName === 'file_read' && result.content) {
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '4px' }}>
          📖 Contenu de : {result.path || 'fichier'}
        </div>
        <pre style={{
          background: 'var(--bg-tertiary)', padding: '8px 12px', borderRadius: '6px',
          fontSize: '12px', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-family)',
          color: 'var(--text-primary)', border: '1px solid var(--border)',
          maxHeight: '250px', overflowY: 'auto',
        }}>
          {result.content.substring(0, 3000)}
          {result.content.length > 3000 && '\n\n... (contenu tronqué)'}
        </pre>
      </div>
    );
  }

  // ── email_list_inbox ─────
  if (toolName === 'email_list_inbox' && result.emails) {
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          📧 {result.count || result.emails.length} email(s) {result.mode === 'demo' ? '(mode démo)' : ''}
        </div>
        {result.emails.slice(0, 15).map((email, i) => (
          <div key={i} style={{
            padding: '8px 12px', marginBottom: '4px',
            background: 'var(--bg-tertiary)', borderRadius: '6px',
            borderLeft: `3px solid ${email.read ? 'var(--text-muted)' : 'var(--accent-primary)'}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: email.read ? 400 : 700, fontSize: 'var(--font-xs)', color: 'var(--text-primary)' }}>
                {email.subject}
              </span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{email.date}</span>
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              De : {email.from}
            </div>
            {email.preview && (
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                {email.preview}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  // ── pc_system_info ─────
  if (toolName === 'pc_system_info' && result.memory) {
    return (
      <div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-xs)' }}>
          <tbody>
            {[
              ['🖥️ Système', `${result.platform} ${result.release} (${result.arch})`],
              ['⏱️ Uptime', result.uptime],
              ['💾 RAM totale', result.memory.total],
              ['📗 RAM libre', result.memory.free],
              ['📕 RAM utilisée', result.memory.used],
              ['📂 Sandbox', result.sandbox],
            ].map(([label, val], i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '4px 8px', fontWeight: 600, color: 'var(--text-primary)' }}>{label}</td>
                <td style={{ padding: '4px 8px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{val}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // ── calendar_list_events ─────
  if (toolName === 'calendar_list_events' && result.events) {
    return (
      <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          📅 {result.count || result.events.length} événement(s)
        </div>
        {result.events.map((evt, i) => (
          <div key={i} style={{
            padding: '8px 12px', marginBottom: '4px',
            background: 'var(--bg-tertiary)', borderRadius: '6px',
            borderLeft: '3px solid var(--accent-primary)',
          }}>
            <div style={{ fontWeight: 600, fontSize: 'var(--font-xs)', color: 'var(--text-primary)' }}>
              {evt.title}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              {evt.start} → {evt.end} {evt.location ? `📍 ${evt.location}` : ''}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // ── Plusieurs fichiers générés (v2.142 — code_python peut écrire plusieurs
  // graphiques/CSV en une seule exécution) — une carte par fichier reconnu.
  if (result.success && Array.isArray(result.files) && result.files.length > 1) {
    const cards = result.files
      .filter(p => typeof p === 'string')
      .map(p => (p.split(/[\\/]/).pop() || '').split('.').pop().toLowerCase())
      .map((ext, i) => ({ ext, path: result.files[i] }))
      .filter(({ ext }) => DOCUMENT_EXTENSIONS.has(ext) || IMAGE_EXTENSIONS.has(ext));
    if (cards.length > 0) {
      return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          {cards.map(({ path }, i) => <GeneratedFileCard key={i} path={path} />)}
        </div>
      );
    }
  }

  // ── Document/fichier généré (PDF/Word/Excel/PPT/texte/image) — clic pour ouvrir ─────
  if (result.success && typeof result.path === 'string') {
    const ext = (result.path.split(/[\\/]/).pop() || '').split('.').pop().toLowerCase();
    if (DOCUMENT_EXTENSIONS.has(ext) || IMAGE_EXTENSIONS.has(ext)) {
      return <GeneratedFileCard path={result.path} message={result.message} securityWarning={result.security_warning} />;
    }
  }

  // ── Succès générique ─────
  if (result.success && result.message) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--success)' }}>
        <span>✅</span> {result.message}
      </div>
    );
  }

  // ── pc_run_command ─────
  if (toolName === 'pc_run_command' && (result.stdout || result.stderr)) {
    return (
      <div style={{ maxHeight: '250px', overflowY: 'auto' }}>
        {result.stdout && result.stdout !== 'Aucune sortie standard.' && (
          <pre style={{
            background: 'var(--bg-tertiary)', padding: '8px 12px', borderRadius: '6px',
            fontSize: '12px', whiteSpace: 'pre-wrap', fontFamily: 'monospace',
            color: 'var(--success)', border: '1px solid var(--border)',
          }}>
            {result.stdout.substring(0, 3000)}
          </pre>
        )}
        {result.stderr && result.stderr !== 'Aucune erreur signalée.' && (
          <pre style={{
            background: 'var(--danger-bg)', padding: '8px 12px', borderRadius: '6px',
            fontSize: '12px', whiteSpace: 'pre-wrap', fontFamily: 'monospace',
            color: 'var(--danger)', marginTop: '4px',
          }}>
            {result.stderr.substring(0, 2000)}
          </pre>
        )}
        {result.success && <div style={{ color: 'var(--success)', fontSize: 'var(--font-xs)', marginTop: '4px' }}>✅ Commande exécutée avec succès</div>}
      </div>
    );
  }

  // ── Clipboard ─────
  if (toolName === 'pc_clipboard_get' && result.text !== undefined) {
    return (
      <div>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '4px' }}>📋 Contenu du presse-papiers :</div>
        <pre style={{
          background: 'var(--bg-tertiary)', padding: '8px 12px', borderRadius: '6px',
          fontSize: '12px', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-family)',
          color: 'var(--text-primary)', border: '1px solid var(--border)',
        }}>
          {result.text || '(vide)'}
        </pre>
      </div>
    );
  }

  // ── win_system_report (v2.134) — jauges CPU/RAM + barres disques au lieu d'un
  // tableau markdown brut. Réutilise DashboardKit (déjà éprouvé sur Monitoring/Santé).
  if (toolName === 'win_system_report' && result.cpu_percent !== undefined) {
    return (
      <div>
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginBottom: '10px' }}>
          <CircleGauge value={result.cpu_percent} label="CPU" size={90} />
          <CircleGauge value={result.ram_percent} label="RAM" size={90} color="#b8bbc1" />
        </div>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          {result.os} · {result.hostname} · uptime {result.uptime}
        </div>
        {(result.disks || []).map((d, i) => (
          <BarRow key={i} label={d.drive} used={d.total_gb - d.free_gb} total={d.total_gb} color={d.used_pct >= 90 ? '#ef4444' : '#b8bbc1'} />
        ))}
        {result.alerts && result.alerts.length > 0 && (
          <div style={{ marginTop: '8px', color: 'var(--danger)', fontSize: 'var(--font-xs)' }}>
            {result.alerts.map((a, i) => <div key={i}>⚠️ {a}</div>)}
          </div>
        )}
        <div style={{ marginTop: '6px', fontSize: 'var(--font-xs)', color: 'var(--success)' }}>{result.health}</div>
      </div>
    );
  }

  // ── pc_hardware_temps (v2.134) — capteurs réels, jamais une supposition.
  if (toolName === 'pc_hardware_temps' && (result.cpu_temp_available !== undefined || result.gpu_temp_available !== undefined)) {
    return (
      <div>
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
          <StatCard label="CPU" value={result.cpu_temp_available ? result.cpu_temp_c : 'N/D'} unit={result.cpu_temp_available ? '°C' : ''}
                    color={result.cpu_temp_available && result.cpu_temp_c >= 85 ? 'var(--danger)' : 'var(--text-primary)'} icon="🌡️" />
          <StatCard label="GPU" value={result.gpu_temp_available ? result.gpu_temp_c : 'N/D'} unit={result.gpu_temp_available ? '°C' : ''}
                    color={result.gpu_temp_available && result.gpu_temp_c >= 83 ? 'var(--danger)' : 'var(--text-primary)'} icon="🌡️" />
        </div>
        {result.message && <div style={{ marginTop: '6px', fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>{result.message}</div>}
        {(result.warnings || []).map((w, i) => <div key={i} style={{ color: 'var(--danger)', fontSize: 'var(--font-xs)', marginTop: '4px' }}>{w}</div>)}
      </div>
    );
  }

  // ── pc_disk_smart_health (v2.134) ─────
  if (toolName === 'pc_disk_smart_health' && Array.isArray(result.disks)) {
    return (
      <div style={{ maxHeight: '260px', overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-xs)' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              <th style={{ textAlign: 'left', padding: '4px 8px' }}>Disque</th>
              <th style={{ textAlign: 'left', padding: '4px 8px' }}>État</th>
              <th style={{ textAlign: 'left', padding: '4px 8px' }}>Usure</th>
              <th style={{ textAlign: 'left', padding: '4px 8px' }}>Erreurs non corrigées</th>
            </tr>
          </thead>
          <tbody>
            {result.disks.map((d, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '4px 8px', color: 'var(--text-primary)' }}>{d.FriendlyName} ({d.MediaType})</td>
                <td style={{ padding: '4px 8px', color: d.HealthStatus === 'Healthy' ? 'var(--success)' : 'var(--danger)' }}>{d.HealthStatus}</td>
                <td style={{ padding: '4px 8px', color: (d.Wear ?? 0) >= 80 ? 'var(--danger)' : 'var(--text-secondary)' }}>{d.Wear != null ? `${d.Wear}%` : 'N/D'}</td>
                <td style={{ padding: '4px 8px', color: (d.ReadErrorsUncorrected ?? 0) > 0 ? 'var(--danger)' : 'var(--text-secondary)' }}>{d.ReadErrorsUncorrected ?? 'N/D'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(result.warnings || []).map((w, i) => <div key={i} style={{ color: 'var(--danger)', fontSize: 'var(--font-xs)', marginTop: '6px' }}>{w}</div>)}
      </div>
    );
  }

  // ── pc_event_log_errors (v2.134) ─────
  if (toolName === 'pc_event_log_errors' && Array.isArray(result.events)) {
    return (
      <div style={{ maxHeight: '260px', overflowY: 'auto' }}>
        <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          {result.count} événement(s) sur {result.period_days} jour(s)
        </div>
        {(result.recurring_sources || []).length > 0 && (
          <div style={{ marginBottom: '6px', fontSize: 'var(--font-xs)', color: 'var(--danger)' }}>
            🔁 Sources récurrentes : {result.recurring_sources.join(', ')}
          </div>
        )}
        {result.events.map((e, i) => (
          <div key={i} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', fontSize: '11px' }}>
            <span style={{ color: 'var(--text-muted)' }}>{e.TimeCreated}</span>{' '}
            <span style={{ color: 'var(--danger)', fontWeight: 600 }}>{e.LevelDisplayName}</span>{' '}
            <span style={{ color: 'var(--accent-primary)' }}>{e.ProviderName}</span>
            <div style={{ color: 'var(--text-secondary)' }}>{e.Message}</div>
          </div>
        ))}
      </div>
    );
  }

  // ── Fallback générique : rendu lisible (JSON uniquement sur demande, via le
  // bouton « { } Voir en JSON » intégré à PrettyResult) — tout outil sans rendu
  // spécifique ci-dessus (ex. winget_search, la plupart des outils win_*/billing_*)
  // passait auparavant en JSON brut par défaut, corrigé v2.107.
  return <PrettyResult result={result} />;
}
