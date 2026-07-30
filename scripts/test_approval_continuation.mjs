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
if (
  !context.includes('const runGeneration = ++runGenerationRef.current')
  || !context.includes('if (isCurrentRun()) {')
  || !context.includes('abortRef.current = null')
) {
  throw new Error('Un ancien flux peut ecraser la continuation approuvee.');
}
if (!container.includes('continuationApprovalId: approvalId')) {
  throw new Error("L'approbation UI ne relance pas la mission.");
}
if (!container.includes('executionResult.needs_repair === true')) {
  throw new Error("La reprise ne distingue pas l'échec métier du succès HTTP.");
}
if (
  !container.includes("preuve est insuffisante")
  || !container.includes("avec computer_control, choisis une cible plus")
) {
  throw new Error("La reprise après échec ne force pas la boucle d'observation/réparation.");
}
if (
  !container.includes('sans redemander les choix que l\'utilisateur a ')
  || !container.includes('déjà délégués')
) {
  throw new Error("La reprise après succès oublie les choix déjà délégués.");
}

console.log('Approval Continuation UI OK - reprise invisible et liée à la preuve UI.');
