'use client';
import { useState } from 'react';

const STATUS_ICON = { done: '✓', running: '◌', error: '!' };

export default function CortexTrace({ message }) {
  const [open, setOpen] = useState(false);
  const contract = message?.cortex;
  const provenance = message?.cortexProvenance;
  const graph = message?.executionGraph || [];
  if (!contract && !provenance) return null;
  const tools = provenance?.tools || [];
  const reviewed = provenance?.reviewed;
  const privacy = provenance?.privacy_route || contract?.resolved?.privacy;
  const debt = provenance?.truth_ledger?.epistemic_debt;
  const flaggedSources = provenance?.truth_ledger?.source_firewall?.flagged_count || 0;

  return (
    <div style={{ marginLeft: 40, width: 'fit-content', maxWidth: 'calc(100% - 48px)', fontSize: 10, color: 'var(--text-muted)' }}>
      <button type="button" onClick={() => setOpen(v => !v)}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', borderRadius: 999,
          border: '1px solid rgba(56,189,248,.2)', background: 'rgba(56,189,248,.05)', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 10 }}>
        <span style={{ color: '#38bdf8' }}>✦ Cortex</span>
        <span>{contract?.summary || 'Auto'}</span>
        {reviewed && <span title="Révision indépendante effectuée">· vérifié</span>}
        {tools.length > 0 && <span>· {tools.length} outil{tools.length > 1 ? 's' : ''}</span>}
        <span>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div style={{ marginTop: 6, padding: 10, minWidth: 260, maxWidth: 620, borderRadius: 10,
          background: 'var(--bg-glass)', border: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: graph.length ? 9 : 0 }}>
            <span>🔒 {privacy || 'auto'}</span>
            <span>🧠 {provenance?.model || message?.modelInfo?.model || 'routage auto'}</span>
            <span>{reviewed ? '✓ révision effectuée' : 'réponse directe'}</span>
            {provenance?.evidence_coverage && <span>🔗 {provenance.evidence_coverage === 'cited' ? `${provenance.citations?.length || 0} citation(s)` : provenance.evidence_coverage === 'missing' ? 'preuves manquantes' : provenance.evidence_coverage === 'tool_evidence' ? 'preuves par outils' : 'preuves non demandées'}</span>}
            {debt && <span title="Part des affirmations insuffisamment étayées">Dette de preuve {Math.round((debt.score || 0) * 100)} %</span>}
            {flaggedSources > 0 && <span style={{ color: '#fbbf24' }}>{flaggedSources} source(s) filtrée(s)</span>}
          </div>
          {graph.length > 0 && <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
            {graph.map((node, index) => (
              <span key={`${node.id}-${index}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {index > 0 && <span style={{ opacity: .35 }}>→</span>}
                <span style={{ padding: '3px 6px', borderRadius: 6, background: node.status === 'running' ? 'rgba(251,191,36,.1)' : 'rgba(45,212,191,.07)', color: node.status === 'running' ? '#fbbf24' : 'var(--text-secondary)' }}>
                  {STATUS_ICON[node.status] || '·'} {node.label}
                </span>
              </span>
            ))}
          </div>}
          {provenance?.evidence_tools?.length > 0 && <div style={{ marginTop: 8 }}>Preuves : {provenance.evidence_tools.join(', ')}</div>}
        </div>
      )}
    </div>
  );
}
