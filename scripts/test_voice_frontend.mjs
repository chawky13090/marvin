import assert from 'node:assert/strict';
import fs from 'node:fs';

const hook = fs.readFileSync(new URL('../lib/hooks/useVoice.js', import.meta.url), 'utf8');
const context = fs.readFileSync(new URL('../lib/contexts/ChatContext.jsx', import.meta.url), 'utf8');

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

console.log('Voice frontend: 10 assertions réussies.');
