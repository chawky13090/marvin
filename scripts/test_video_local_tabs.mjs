import assert from 'node:assert/strict';
import fs from 'node:fs';

const paths = [
  '../app/video/page.jsx',
  '../components/video/VideoShared.jsx',
  '../components/video/LocalVideoTabs.jsx',
];
const source = paths
  .map((path) => new URL(path, import.meta.url))
  .filter((path) => fs.existsSync(path))
  .map((path) => fs.readFileSync(path, 'utf8'))
  .join('\n');

for (const contract of [
  /function LocalVideoTab|export function LocalVideoTab/,
  /function TextAnimationTab|export function TextAnimationTab/,
  /\/api\/video\/local\/models/,
  /\/api\/video\/local\/generate/,
  /\/api\/video\/local\/generate\/image/,
  /\/api\/video\/local\/cancel/,
  /\/api\/video\/enhance-prompt/,
  /\/api\/video\/text-animation/,
  /new AbortController\(\)/,
  /EventSource|body\.getReader\(\)/,
  /<DropZone/,
  /<VideoResult/,
  /<LocalVideoTab\s*\/>/,
  /<TextAnimationTab\s*\/>/,
]) {
  assert.match(source, contract);
}

assert.match(source, /status === ['"]processing['"]/);
assert.match(source, /genStatus === ['"]error['"]|genError/);
assert.match(source, /output_format:\s*format/);
assert.match(source, /setGalleryKey\(k => k \+ 1\)/);

console.log('Video local tabs characterization OK - models, generation, cancellation, progress and text animation covered.');
