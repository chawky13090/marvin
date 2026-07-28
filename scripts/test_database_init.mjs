/** Regression de l'initialiseur SQLite historique cote Next.js. */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';


const tempDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'marvin-db-init-'));
process.env.DATABASE_PATH = path.join(tempDirectory, 'secretary.db');

try {
  const { getDb, closeDb } = await import('../lib/database/init.js');
  const database = getDb();
  assert.equal(database.pragma('quick_check', { simple: true }), 'ok');
  assert.ok(
    database.prepare(
      "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_cron_enabled'",
    ).get(),
  );
  const tables = new Set(
    database.prepare("SELECT name FROM sqlite_master WHERE type = 'table'").all()
      .map(({ name }) => name),
  );
  for (const name of ['projects', 'conversations', 'messages', 'cron_jobs', 'settings']) {
    assert.ok(tables.has(name), `Table absente sur base neuve : ${name}`);
  }
  const oauthColumns = new Set(
    database.prepare('PRAGMA table_info(oauth_tokens)').all().map(({ name }) => name),
  );
  assert.deepEqual(
    oauthColumns,
    new Set(['provider', 'token_type', 'scope', 'expires_at', 'migrated_at']),
  );
  assert.ok(!oauthColumns.has('access_token'));
  assert.ok(!oauthColumns.has('refresh_token'));
  closeDb();
  console.log('Initialiseur SQLite Next.js OK - base neuve et index cron.');
} finally {
  fs.rmSync(tempDirectory, { recursive: true, force: true });
}
