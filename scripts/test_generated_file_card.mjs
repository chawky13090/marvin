import assert from 'node:assert/strict';
import fs from 'node:fs';

const bubblePath = new URL('../components/chat/MessageBubble.jsx', import.meta.url);
const cardPath = new URL('../components/chat/GeneratedFileCard.jsx', import.meta.url);
const bubble = fs.readFileSync(bubblePath, 'utf8');
const card = fs.existsSync(cardPath) ? fs.readFileSync(cardPath, 'utf8') : '';
const source = `${bubble}\n${card}`;

for (const extension of ['pdf', 'docx', 'xlsx', 'pptx', 'html', 'png', 'webp']) {
  assert.match(source, new RegExp(`['"]${extension}['"]`), `extension ${extension} absente`);
}
assert.match(source, /toolName:\s*['"]pc_open_file['"]/);
assert.match(source, /toolName:\s*['"]document_convert_format['"]/);
assert.match(source, /\/api\/files\/raw\?path=/);
assert.match(source, /securityWarning/);
assert.match(source, /noopener noreferrer|encodeURIComponent\(path\)/);
assert.match(bubble, /GeneratedFileCard/);
assert.match(bubble, /DOCUMENT_EXTENSIONS/);
assert.match(bubble, /IMAGE_EXTENSIONS/);

console.log('Generated file card characterization OK - preview, opening, conversion and warnings covered.');
