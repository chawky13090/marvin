import assert from 'node:assert/strict';
import fs from 'node:fs';

const hook = fs.readFileSync(new URL('../lib/hooks/useVoice.js', import.meta.url), 'utf8');
const context = fs.readFileSync(new URL('../lib/contexts/ChatContext.jsx', import.meta.url), 'utf8');
const input = fs.readFileSync(new URL('../components/chat/ChatInput.jsx', import.meta.url), 'utf8');
const avatar = fs.readFileSync(new URL('../app/avatar/page.jsx', import.meta.url), 'utf8');

assert.match(hook, /speakSeqRef\.current \+= 1/, 'arrêter doit invalider la génération active');
assert.match(hook, /mySeq !== speakSeqRef\.current/, 'une ancienne boucle doit refuser la nouvelle file');
assert.match(hook, /expectedSequence !== speakSeqRef\.current/, 'un fragment obsolète doit être ignoré');
assert.match(hook, /const beginSpeechStream = useCallback/, 'le streaming doit posséder une session exclusive');
assert.match(hook, /return runPlayer\(\);/, 'speak doit attendre la fin réelle de la lecture');
assert.match(hook, /ttsControllersRef\.current\.add\(controller\)/, 'chaque requête TTS doit être suivie');
assert.match(hook, /controller\.abort\(\)/, 'arrêter doit annuler les requêtes TTS devenues inutiles');
assert.match(context, /liveVoice\.beginSpeechStream\(\)/, 'le chat doit ouvrir une génération vocale par réponse');
assert.match(context, /enqueueSpeech\(m\[0\], voiceStream\.sequence\)/, 'chaque phrase doit porter le jeton du flux');
assert.match(context, /enqueueSpeech\(tail, voiceStream\.sequence\)/, 'le fragment final doit porter le même jeton');
assert.match(
  context,
  /if \(voiceStream\.active && event\.text\) \{\s*voiceStream\.text = event\.text;/,
  'une réponse Cloud answer_final doit alimenter le tampon vocal avant done',
);
assert.match(hook, /Synthèse vocale indisponible/, 'un échec HTTP TTS doit être visible');
assert.match(hook, /Lecture audio bloquée par le navigateur/, 'un refus autoplay doit être visible');
assert.match(hook, /Lecture audio impossible/, 'une panne de sortie audio doit être visible');
assert.doesNotMatch(hook, /if \(m === 'true'\) setVoiceMode\(true\)/, 'le mode mains libres ne doit jamais être restauré');
assert.match(hook, /localStorage\.removeItem\(VOICE_MODE_KEY\)/, 'la préférence active historique doit être purgée');
assert.doesNotMatch(hook, /localStorage\.setItem\(VOICE_MODE_KEY/, 'un état actif ne doit pas survivre à la session');
assert.doesNotMatch(avatar, /if \(!voice\.voiceMode\) voice\.toggleVoiceMode\(\)/, 'une dictée avatar ne doit pas activer les mains libres');
assert.match(input, /Mains libres actives pour cette session/, 'le statut vocal doit annoncer sa portée');
assert.match(input, /Quitter/, 'le contrôle vocal inférieur doit permettre une sortie explicite');

console.log('Voice frontend: 20 assertions réussies.');
