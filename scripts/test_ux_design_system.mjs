import fs from 'node:fs';
import assert from 'node:assert/strict';

const globalCss = fs.readFileSync('app/globals.css', 'utf8');
const home = fs.readFileSync('app/page.js', 'utf8');
const sidebar = fs.readFileSync('components/sidebar/Sidebar.module.css', 'utf8');
const sidebarComponent = fs.readFileSync('components/sidebar/Sidebar.jsx', 'utf8');
const conversationRow = fs.readFileSync('components/chat/sidebar/ConversationRow.jsx', 'utf8');
const chatInput = fs.readFileSync('components/chat/ChatInput.jsx', 'utf8');
const quietWelcome = fs.readFileSync('components/chat/QuietWelcome.jsx', 'utf8');
const quietWelcomeCss = fs.readFileSync('components/chat/QuietWelcome.module.css', 'utf8');
const contextBar = fs.readFileSync('components/layout/ContextBar.jsx', 'utf8');
const appFrame = fs.readFileSync('components/layout/AppFrame.jsx', 'utf8');
const historyPage = fs.readFileSync('app/historique/page.jsx', 'utf8');
const cortexControl = fs.readFileSync('components/chat/CortexControl.jsx', 'utf8');
const autonomyControl = fs.readFileSync('components/chat/AutonomyControl.jsx', 'utf8');
const chatContainer = fs.readFileSync('components/chat/ChatContainer.jsx', 'utf8');
const messageBubble = fs.readFileSync('components/chat/MessageBubble.jsx', 'utf8');
const messageBubbleCss = fs.readFileSync('components/chat/MessageBubble.module.css', 'utf8');

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
assert.match(globalCss, /--sidebar-collapsed:\s*72px/);
assert.match(globalCss, /--sidebar-expanded:\s*258px/);
assert.match(globalCss, /:focus-visible\s*\{/);
assert.match(globalCss, /outline:\s*2px solid var\(--accent-primary-hover\)/);
assert.match(globalCss, /@media \(prefers-reduced-motion: reduce\)/);
assert.match(globalCss, /animation-duration:\s*0\.01ms !important/);
assert.doesNotMatch(globalCss, /fonts\.googleapis\.com/);
assert.match(home, /var\(--conversation-pane\)/);
assert.match(home, /marvin:collapsed_projects:v1/);
assert.match(home, /aria-expanded=\{!collapsedProjectIds\.has/);
assert.match(home, /aria-label="Nouveau nom du projet"/);
assert.match(home, /Maximum 120 caractères/);
assert.match(sidebar, /font-size:\s*var\(--font-md\)/);
assert.doesNotMatch(sidebar, /--font-size-/);
assert.match(sidebarComponent, /from 'lucide-react'/);
assert.match(sidebarComponent, /aria-current=\{isActive \? 'page'/);
assert.match(sidebarComponent, /width: open \? '26px' : '48px'/);
assert.match(sidebarComponent, /display: 'block', width: '100%'/);
assert.match(conversationRow, /aria-expanded=\{menuOpen\}/);
assert.match(conversationRow, /Exporter en Markdown/);
assert.match(conversationRow, /Exporter en JSON/);
assert.match(conversationRow, /Archiver/);
assert.match(conversationRow, /Restaurer/);
assert.doesNotMatch(conversationRow, /opacity:\s*0/);
assert.match(home, /archived:\s*true/);
assert.match(home, /Conversation archivée/);

assert.match(chatInput, /marvin:open-command-palette/);
assert.match(chatInput, /variant === 'welcome'/);
assert.match(quietWelcome, /Modes de travail suggérés/);
assert.match(quietWelcome, /Recherche approfondie/);
assert.match(quietWelcome, /Council/);
assert.equal((quietWelcome.match(/id:\s*'/g) || []).length, 6);
assert.match(quietWelcome, /Sur quoi travaillons-nous aujourd’hui/);
assert.match(quietWelcomeCss, /prefers-reduced-motion/);
assert.match(contextBar, /Ouvrir la navigation Marvin/);
assert.match(contextBar, /marvin:open-command-palette/);
assert.match(contextBar, /Travail en cours/);
assert.match(contextBar, /id="marvin-conversation-toolbar-host"/);
assert.match(contextBar, /id="marvin-conversation-actions-host"/);
assert.match(appFrame, /<ContextBar \/>/);
assert.doesNotMatch(appFrame, /<NavigationModeControl/);
assert.match(home, /createPortal/);
assert.match(home, /getElementById\('marvin-conversation-actions-host'\)/);
assert.doesNotMatch(home, /id="marvin-conversation-toolbar-host"/);
assert.match(chatInput, /<CortexControl[\s\S]*compact/);
assert.match(chatInput, /Marvin travaille/);
assert.match(chatInput, /className="marvin-chat-composer"/);
assert.match(chatInput, /className="marvin-chat-composer__input"/);
assert.match(globalCss, /\.marvin-chat-composer__input/);
assert.match(chatInput, /<AutonomyControl disabled=\{isLoading\} \/>/);
assert.match(autonomyControl, /normal:[\s\S]*auto:[\s\S]*full:/);
assert.match(autonomyControl, /\/api\/autonomy/);
assert.match(chatContainer, /\/api\/approvals\/\$\{approvalId\}\/approve/);
assert.match(chatContainer, /\/api\/approvals\/\$\{approvalId\}\/deny/);
assert.match(messageBubble, /role="alertdialog"/);
assert.match(messageBubble, /Oui, autoriser/);
assert.match(messageBubble, /Non, refuser/);
assert.match(cortexControl, /cortex-control-trigger--compact/);
assert.match(cortexControl, /className="cortex-control-popover"/);
assert.match(globalCss, /\.cortex-control-popover/);
assert.match(messageBubble, /responseMetaRow/);
assert.match(messageBubble, /<CortexTrace message=\{message\} compact \/>/);
assert.match(messageBubbleCss, /\.responseMetaRow/);
assert.match(historyPage, /Historique des discussions/);
assert.match(historyPage, /toLocaleDateString\('fr-FR'/);
assert.match(chatContainer, /className="marvin-chat-scroll"/);
assert.match(chatContainer, /marvin-chat-stream/);
assert.match(chatInput, /marvin-chat-input-shell/);
assert.match(globalCss, /\.marvin-chat-stream\s*\{[\s\S]*?width:\s*min\(100%, 1120px\)[\s\S]*?margin-inline:\s*auto/);
assert.match(globalCss, /\.marvin-chat-input-shell:not\(\.marvin-chat-input-shell--welcome\)[\s\S]*?1120px[\s\S]*?margin:/);
assert.match(globalCss, /--bg-primary:\s*#0f0f10/);
assert.match(globalCss, /--accent-primary:\s*#b8bbc1/);
assert.doesNotMatch(globalCss, /#4f8cff|#38bdf8|rgba\(79,\s*140,\s*255/);

console.log('UX design system: 85 assertions passed.');
