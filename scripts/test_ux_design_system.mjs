import fs from 'node:fs';
import assert from 'node:assert/strict';

const globalCss = fs.readFileSync('app/globals.css', 'utf8');
const home = fs.readFileSync('app/page.js', 'utf8');
const sidebar = fs.readFileSync('components/sidebar/Sidebar.module.css', 'utf8');

for (const [token, value] of [
  ['--fib-1', '3px'],
  ['--fib-2', '5px'],
  ['--fib-3', '8px'],
  ['--fib-4', '13px'],
  ['--fib-5', '21px'],
  ['--fib-6', '34px'],
  ['--fib-7', '55px'],
  ['--fib-8', '89px'],
]) {
  assert.match(globalCss, new RegExp(`${token}:\\s*${value}`));
}

assert.match(globalCss, /--golden-major:\s*61\.8%/);
assert.match(globalCss, /--golden-minor:\s*38\.2%/);
assert.match(globalCss, /:focus-visible\s*\{/);
assert.match(globalCss, /outline:\s*2px solid var\(--accent-primary-hover\)/);
assert.match(globalCss, /@media \(prefers-reduced-motion: reduce\)/);
assert.match(globalCss, /animation-duration:\s*0\.01ms !important/);
assert.doesNotMatch(globalCss, /fonts\.googleapis\.com/);
assert.match(home, /var\(--conversation-pane\)/);
assert.match(sidebar, /font-size:\s*var\(--font-md\)/);
assert.doesNotMatch(sidebar, /--font-size-/);

console.log('UX design system: 20 assertions passed.');
