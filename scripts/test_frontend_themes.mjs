import assert from 'node:assert/strict';
import fs from 'node:fs';

const layout = fs.readFileSync('app/layout.js', 'utf8');
const css = fs.readFileSync('app/globals.css', 'utf8');
const control = fs.readFileSync('components/layout/ThemeControl.jsx', 'utf8');
const contextBar = fs.readFileSync('components/layout/ContextBar.jsx', 'utf8');
const chatInput = fs.readFileSync('components/chat/ChatInput.jsx', 'utf8');

const themes = ['dark', 'light', 'manga', 'medieval', 'cyberpunk'];
for (const theme of themes) {
  assert.match(control, new RegExp(`id: '${theme}'`), `Thème absent du sélecteur : ${theme}`);
  if (theme !== 'dark') {
    assert.match(css, new RegExp(`html\\[data-theme='${theme}'\\]`), `Tokens CSS absents : ${theme}`);
  }
}

assert.match(layout, /data-theme="dark"/, 'Le thème sombre doit rester le défaut SSR.');
assert.match(layout, /localStorage\.getItem\('marvin_theme'\)/, 'Le thème doit être restauré avant hydratation.');
assert.match(control, /localStorage\.setItem\(STORAGE_KEY, safeTheme\)/, 'Le choix doit être persistant.');
assert.match(control, /aria-haspopup="menu"/);
assert.match(control, /role="menuitemradio"/);
assert.match(control, /event\.key === 'Escape'/, 'Le menu doit être refermable au clavier.');
assert.match(contextBar, /<ThemeControl \/>/, 'Le sélecteur doit rester accessible dans l’en-tête.');
assert.match(css, /@media \(max-width: 640px\)[\s\S]*\.theme-control__trigger span/, 'Le contrôle doit se compacter sur mobile.');
assert.match(chatInput, /variant === 'welcome' \? 'var\(--input-background\)'/, 'Le composeur d’accueil doit suivre le fond du thème.');
assert.match(css, /\.marvin-chat-input-shell:not\([\s\S]*?background: var\(--input-background\) !important;/, 'Le composeur actif doit suivre le fond du thème.');
assert.match(css, /\.marvin-steering-band \{[\s\S]*?background: var\(--bg-glass\);/, 'Le bandeau de pilotage doit suivre le thème.');
assert.doesNotMatch(chatInput, /background: variant === 'welcome' \? 'rgba\(24, 24, 29/, 'Un fond noir fixe rend le texte des thèmes clairs illisible.');
assert.doesNotMatch(layout, /theme==='medieval'\)\?'dark'/, 'Le thème médiéval utilise des surfaces claires.');

console.log('Frontend Themes OK - sombre par défaut, cinq thèmes persistants et contrôle responsive.');
