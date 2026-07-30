import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const bubble = fs.readFileSync(
  path.join(root, 'components', 'chat', 'MessageBubble.jsx'),
  'utf8',
);
const container = fs.readFileSync(
  path.join(root, 'components', 'chat', 'ChatContainer.jsx'),
  'utf8',
);

const checks = [
  [bubble.includes('/api/approvals/${encodeURIComponent(storedApprovalId)}'),
    'chaque carte doit relire son état autoritaire'],
  [bubble.includes("approvalState?.status === 'pending'"),
    'seul le statut pending doit activer les boutons'],
  [bubble.includes("approvalState?.active === true"),
    'le backend doit confirmer explicitement que la demande est active'],
  [bubble.includes("disabled={!approvalIsActive || !approvalResult?.approvalId}"),
    'les boutons doivent être fail-closed'],
  [bubble.includes("marvin:approval-state-changed"),
    'les cartes historiques doivent écouter les décisions voisines'],
  [bubble.includes('Demande remplacée par une plus récente'),
    'une demande remplacée doit avoir un libellé final lisible'],
  [container.includes("new CustomEvent('marvin:approval-state-changed'"),
    'une décision doit réveiller les autres cartes'],
];

for (const [condition, message] of checks) {
  if (!condition) throw new Error(`Approval lifecycle UI: ${message}`);
}

console.log(`Approval Lifecycle UI OK - ${checks.length} invariants.`);
