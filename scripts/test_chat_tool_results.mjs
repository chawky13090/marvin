import assert from 'node:assert/strict';
import fs from 'node:fs';

const bubble = fs.readFileSync(new URL('../components/chat/MessageBubble.jsx', import.meta.url), 'utf8');
const rendererUrl = new URL('../components/chat/ToolResultContent.jsx', import.meta.url);
const renderer = fs.existsSync(rendererUrl) ? fs.readFileSync(rendererUrl, 'utf8') : '';
const source = `${bubble}\n${renderer}`;

for (const contract of [
  'web_deep_research', 'ai_research_swarm', 'ai_model_council', 'ai_adaptive_team',
  'ai_code_forge', 'ai_test_forge', 'system_search', 'file_find', 'file_list',
  'file_search_text', 'file_read', 'email_list_inbox', 'pc_system_info',
  'calendar_list_events', 'pc_run_command', 'pc_clipboard_get', 'win_system_report',
  'pc_hardware_temps', 'pc_disk_smart_health', 'pc_event_log_errors',
]) assert.match(source, new RegExp(contract), `rendu ${contract} absent`);

assert.match(source, /GeneratedFileCard/);
assert.match(source, /CodingMissionTracker/);
assert.match(source, /FileExplorerCard/);
assert.match(source, /PrettyResult/);
assert.match(source, /renderToolResult/);
assert.match(source, /noopener noreferrer|renderSafeMarkdown/);

console.log('Chat tool results characterization OK - specialized renderers and safe fallback covered.');
