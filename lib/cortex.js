export const DEFAULT_CORTEX_CONTRACT = Object.freeze({
  effort: 'auto', evidence: 'auto', review: 'auto', autonomy: 'auto', privacy: 'auto', output: 'auto', pinned: false,
});

export const CORTEX_AXES = [
  { key: 'effort', label: 'Effort', options: [['auto', 'Auto'], ['instant', 'Instantané'], ['standard', 'Standard'], ['deep', 'Approfondi'], ['mission', 'Mission autonome']] },
  { key: 'evidence', label: 'Preuves', options: [['auto', 'Auto'], ['none', 'Aucune'], ['memory', 'Mémoire locale'], ['web', 'Web'], ['primary', 'Sources primaires'], ['connected', 'Sources connectées']] },
  { key: 'review', label: 'Révision', options: [['auto', 'Auto'], ['none', 'Simple'], ['verify', 'Vérifiée'], ['council_if_disagreement', 'Council si désaccord'], ['team', 'Équipe adaptative'], ['council5', 'Council 5 forcé'], ['search', 'Cortex Search'], ['swarm', 'Research Swarm']] },
  { key: 'autonomy', label: 'Autonomie', options: [['auto', 'Auto'], ['advise', 'Conseiller'], ['prepare', 'Préparer'], ['execute', 'Exécuter avec confirmations'], ['mission', 'Mission suivie']] },
  { key: 'privacy', label: 'Confidentialité', options: [['auto', 'Auto'], ['local', 'Local strict'], ['hybrid_redacted', 'Hybride expurgé'], ['cloud', 'Cloud autorisé']] },
  { key: 'output', label: 'Livrable', options: [['auto', 'Auto'], ['chat', 'Chat'], ['brief', 'Synthèse'], ['report', 'Rapport'], ['document', 'Document'], ['table', 'Tableau'], ['workflow', 'Workflow']] },
];

const LABELS = Object.fromEntries(CORTEX_AXES.flatMap(axis => axis.options));

export function cortexSummary(contract = DEFAULT_CORTEX_CONTRACT) {
  const selected = CORTEX_AXES.filter(axis => contract[axis.key] && contract[axis.key] !== 'auto')
    .map(axis => LABELS[contract[axis.key]]);
  return selected.length ? selected.join(' · ') : 'Auto adaptatif';
}

export function resetOneShot(contract) {
  return contract?.pinned ? contract : { ...DEFAULT_CORTEX_CONTRACT };
}
