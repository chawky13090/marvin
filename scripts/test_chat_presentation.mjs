import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  conversationAuditToMarkdown,
  createConversationAudit,
  groupConversationMessages,
} from '../lib/chatPresentation.mjs';

const firstTool = {
  id: 'assistant-1',
  role: 'assistant',
  content: '',
  toolInvocations: [{ toolCallId: 'call-1', toolName: 'web_search', state: 'result', result: { results: [] } }],
};
const secondTool = {
  id: 'assistant-2',
  role: 'assistant',
  parts: [{ type: 'tool-invocation', toolInvocation: { toolCallId: 'call-2', toolName: 'web_browse', state: 'result', result: { success: true } } }],
};
const answer = { id: 'assistant-3', role: 'assistant', content: 'Réponse finale' };
const user = { id: 'user-1', role: 'user', content: 'Question' };
const input = [user, firstTool, secondTool, answer];
const output = groupConversationMessages(input);

assert.equal(output.length, 3, 'les outils consécutifs doivent former une activité');
assert.equal(output[1].toolInvocations.length, 2, 'tous les appels doivent être conservés');
assert.equal(output[1].groupedMessageCount, 2, 'le nombre de messages regroupés doit rester traçable');
assert.equal(output[2], answer, 'la réponse humaine doit rester inchangée');
assert.equal(firstTool.toolInvocations.length, 1, 'la fonction ne doit pas modifier les messages sources');

const separated = groupConversationMessages([firstTool, answer, secondTool]);
assert.equal(separated.length, 3, 'une réponse textuelle doit interrompre le regroupement');

const statusUpdates = [1, 2, 3].map((percent) => ({
  id: `status-${percent}`,
  role: 'assistant',
  content: `Progression ${percent} %`,
  toolInvocations: [{ toolCallId: `status-call-${percent}`, toolName: 'code_workspace_status', state: 'result', result: { percent } }],
}));
const compactStatus = groupConversationMessages(statusUpdates);
assert.equal(compactStatus.length, 1, 'les interrogations répétitives de statut doivent être regroupées');
assert.equal(compactStatus[0].content, 'Progression 3 %', 'seul le statut humain le plus récent doit rester visible');
assert.equal(compactStatus[0].toolInvocations.length, 3, 'les preuves de chaque interrogation doivent être conservées');

const audit = createConversationAudit([{
  role: 'assistant',
  content: 'Résultat vérifié',
  toolInvocations: [{
    toolName: 'example_tool',
    state: 'result',
    args: { token: 'secret-token', path: 'C:/safe' },
    result: { success: true, nested: { password: 'secret-password' } },
  }],
}], new Date('2026-07-18T00:00:00.000Z'));
assert.equal(audit.messages[0].toolInvocations[0].args.token, '[MASQUÉ]', 'les tokens doivent être masqués');
assert.equal(audit.messages[0].toolInvocations[0].result.nested.password, '[MASQUÉ]', 'les mots de passe imbriqués doivent être masqués');
assert.equal(audit.messages[0].toolInvocations[0].args.path, 'C:/safe', 'les données non sensibles doivent être conservées');
const markdownAudit = conversationAuditToMarkdown(audit);
const messageBubbleSource = fs.readFileSync(new URL('../components/chat/MessageBubble.jsx', import.meta.url), 'utf8');
const fileExplorerSource = fs.readFileSync(new URL('../components/chat/FileExplorerCard.jsx', import.meta.url), 'utf8');
const typingIndicatorSource = fs.readFileSync(new URL('../components/chat/TypingIndicator.jsx', import.meta.url), 'utf8');
const typingIndicatorCss = fs.readFileSync(new URL('../components/chat/TypingIndicator.module.css', import.meta.url), 'utf8');
assert.match(
  messageBubbleSource,
  /nextOffset=\{result\.has_more \? result\.next_offset : null\}/,
  'la pagination file_list doit etre transmise au composant du chat',
);
assert.match(
  fileExplorerSource,
  /remainingOffset[\s\S]*Afficher la suite/,
  'le navigateur de fichiers doit pouvoir charger toutes les pages',
);
assert.match(typingIndicatorSource, /marvin-activity-robot\.png/, 'la carte d’activité doit afficher le robot Marvin');
assert.match(typingIndicatorSource, /robotMode/, 'le robot doit réagir à l’étape réelle de la mission');
assert.match(typingIndicatorSource, /data-layout=\{compact \? 'standalone' : 'composer'\}/, 'l’activité principale doit être intégrée au composeur');
assert.match(typingIndicatorSource, /marvin-thinking\.png/, 'le robot doit changer visuellement lorsque Marvin réfléchit');
assert.match(typingIndicatorSource, /aria-label="Arrêter la tâche de Marvin"/, 'la tête du robot doit être un bouton d’arrêt accessible');
assert.match(typingIndicatorCss, /\.density_compact[\s\S]*\.activitySummary \{ display: none; \}/, 'le robot doit se compacter lorsque la sidebar réduit le chat');
assert.match(
  messageBubbleSource,
  /tool\.result !== undefined && isCodingMissionTool[\s\S]*?<CodingMissionTracker result=\{tool\.result\}/,
  'une Coding Mission doit afficher son suivi directement dans le chat',
);
assert.match(
  messageBubbleSource,
  /tool\.result !== undefined && !isCodingMissionTool/,
  'le suivi de mission ne doit pas etre enferme dans les details techniques',
);
assert.match(
  messageBubbleSource,
  /privacyMode === 'ultra_cloud'[\s\S]*?'Cloud strict'/,
  'la provenance Ultra Cloud doit être visible dans le chat',
);
assert.match(
  messageBubbleSource,
  /privacyMode === 'sensitive_local'[\s\S]*?'Local · contenu sensible'/,
  'le repli confidentiel local doit être visible dans le chat',
);
const trackerSource = fs.readFileSync(new URL('../components/chat/CodingMissionTracker.jsx', import.meta.url), 'utf8');
assert.match(trackerSource, /setInterval\(refresh, 3000\)/, 'le suivi doit continuer si le flux SSE est interrompu');
assert.match(trackerSource, /Tu peux changer de page/, 'la persistance apres navigation doit etre expliquee');
console.log('Chat mission tracker: 4 assertions reussies.');
assert.match(markdownAudit, /Audit de conversation Marvin/, 'le Markdown doit être identifiable');
assert.doesNotMatch(markdownAudit, /secret-token|secret-password/, 'le Markdown ne doit réintroduire aucun secret masqué');

console.log('Chat presentation: 14 assertions réussies.');
