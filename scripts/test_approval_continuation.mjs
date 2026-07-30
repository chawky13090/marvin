import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const context = fs.readFileSync(
  path.join(root, 'lib', 'contexts', 'ChatContext.jsx'),
  'utf8',
);
const container = fs.readFileSync(
  path.join(root, 'components', 'chat', 'ChatContainer.jsx'),
  'utf8',
);

if (!context.includes('continuationApprovalId: continuationApprovalId || null')) {
  throw new Error('Le contrat frontend de continuation approuvée est absent.');
}
if (!context.includes('internal\n      ? [...prev, assistantMsg]')) {
  throw new Error('La continuation interne ne doit pas créer un faux message utilisateur.');
}
if (!context.includes('messagesRef.current = updatedMessages')) {
  throw new Error("Le résultat approuvé doit précéder la reprise dans le contexte LLM.");
}
if (!context.includes("result: inv.state === 'result' ? inv.result : undefined")) {
  throw new Error("Le reçu d'outil approuvé n'est pas transmis au prochain tour LLM.");
}
if (!container.includes('continuationApprovalId: approvalId')) {
  throw new Error("L'approbation UI ne relance pas la mission.");
}
if (!container.includes('Poursuis maintenant la mission initiale')) {
  throw new Error('La consigne de reprise après approbation est absente.');
}

console.log('Approval Continuation UI OK - reprise invisible et liée à la preuve UI.');
