import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(path, 'utf8');
const input = read('components/chat/ChatInput.jsx');
const container = read('components/chat/ChatContainer.jsx');
const indicator = read('components/chat/TypingIndicator.module.css');
const welcome = read('components/chat/QuietWelcome.module.css');
const globals = read('app/globals.css');

assert.match(input, /rows=\{3\}/, 'Le composeur doit offrir au moins trois lignes dès son ouverture.');
assert.match(input, /flex: '1 0 100%'/, 'Le texte doit occuper une ligne complète.');
assert.match(input, /maximumHeight = variant === 'welcome' \? 220 : 180/, 'La croissance verticale doit rester bornée.');
assert.match(container, /className="marvin-steering-band"/, 'Le pilotage doit précéder visuellement le composeur.');
assert.match(container, /className="marvin-steering-band__stop"/, 'Le bandeau doit conserver un arrêt explicite.');
assert.match(container, /sendDirective\(\{ text, kind: directiveKind \}\)/, 'Les choix visuels doivent rester reliés aux directives actives.');
assert.match(indicator, /width: 76px;\s*height: 68px;/, 'Le robot de travail ne doit pas être réduit en mode étroit.');
assert.match(indicator, /\.density_compact \.activitySummary \{ display: grid; \}/, 'Le statut de travail reste lisible en mode compact.');
assert.match(welcome, /width: min\(1040px, 100%\)/, 'L’accueil doit exploiter la largeur disponible.');
assert.match(globals, /\.marvin-chat-container[\s\S]*?min-width: 0;[\s\S]*?overflow: hidden;/, 'La colonne chat doit céder proprement devant la sidebar.');
assert.match(globals, /@media \(max-width: 480px\)[\s\S]*?\.marvin-chat-composer__input[\s\S]*?min-height: 78px !important;/, 'La saisie mobile doit rester confortable.');

console.log('Composeur responsive Marvin OK');
