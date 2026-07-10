/**
 * Initialisation de la base de données SQLite.
 * Crée automatiquement le répertoire de données et les tables nécessaires.
 * Utilise better-sqlite3 pour des opérations synchrones performantes.
 */
import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

/** Chemin vers le fichier de base de données */
const DB_PATH = process.env.DATABASE_PATH || path.join(process.cwd(), 'data', 'secretary.db');

/**
 * Initialise et retourne l'instance de la base de données.
 * Crée le répertoire parent si nécessaire.
 * @returns {Database} Instance better-sqlite3
 */
function initializeDatabase() {
  // Créer le répertoire de données s'il n'existe pas
  const dbDir = path.dirname(DB_PATH);
  if (!fs.existsSync(dbDir)) {
    fs.mkdirSync(dbDir, { recursive: true });
  }

  const db = new Database(DB_PATH);

  // Activer le mode WAL pour de meilleures performances en lecture concurrente
  db.pragma('journal_mode = WAL');
  // Activer les clés étrangères pour l'intégrité référentielle
  db.pragma('foreign_keys = ON');

  // --- Création des tables ---

  // Table des projets
  db.exec(`
    CREATE TABLE IF NOT EXISTS projects (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Table des conversations
  db.exec(`
    CREATE TABLE IF NOT EXISTS conversations (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL DEFAULT 'Nouvelle conversation',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now')),
      project_id TEXT,
      FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
    )
  `);
  
  // Migration pour ajouter project_id si la table existait déjà sans cette colonne
  try {
    const tableInfo = db.pragma('table_info(conversations)');
    if (!tableInfo.some(column => column.name === 'project_id')) {
        db.exec(`ALTER TABLE conversations ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL`);
    }
  } catch (err) {
    console.error('Erreur migration conversations:', err);
  }

  // Table des messages (liés à une conversation)
  db.exec(`
    CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY,
      conversation_id TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
      content TEXT NOT NULL,
      tool_calls TEXT,
      tool_results TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
    )
  `);

  // Index pour accélérer la récupération des messages par conversation
  db.exec(`
    CREATE INDEX IF NOT EXISTS idx_messages_conversation 
    ON messages(conversation_id, created_at)
  `);

  // Table des tokens OAuth (un par fournisseur)
  db.exec(`
    CREATE TABLE IF NOT EXISTS oauth_tokens (
      provider TEXT PRIMARY KEY CHECK(provider IN ('google', 'microsoft')),
      access_token TEXT NOT NULL,
      refresh_token TEXT,
      token_type TEXT DEFAULT 'Bearer',
      scope TEXT,
      expires_at TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Journal des actions sur les fichiers (pour audit et annulation éventuelle)
  db.exec(`
    CREATE TABLE IF NOT EXISTS file_actions_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      action TEXT NOT NULL,
      source_path TEXT NOT NULL,
      destination_path TEXT,
      details TEXT,
      status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('completed', 'failed', 'reverted')),
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Index pour les recherches récentes dans le journal
  db.exec(`
    CREATE INDEX IF NOT EXISTS idx_file_actions_created 
    ON file_actions_log(created_at DESC)
  `);

  // Table des paramètres de l'application (clé-valeur)
  db.exec(`
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Table des souvenirs (mémoire personnelle de l'utilisateur)
  db.exec(`
    CREATE TABLE IF NOT EXISTS memories (
      id TEXT PRIMARY KEY,
      category TEXT NOT NULL CHECK(category IN ('user_profile', 'preference', 'fact', 'habit')),
      content TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Table des tâches (todo management)
  db.exec(`
    CREATE TABLE IF NOT EXISTS tasks (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      description TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'done', 'cancelled')),
      priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
      due_date TEXT,
      tags TEXT DEFAULT '[]',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Table des notes
  db.exec(`
    CREATE TABLE IF NOT EXISTS notes (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      content TEXT NOT NULL DEFAULT '',
      tags TEXT DEFAULT '[]',
      pinned INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Table des modèles d'email
  db.exec(`
    CREATE TABLE IF NOT EXISTS email_templates (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      subject TEXT NOT NULL,
      body TEXT NOT NULL,
      variables TEXT DEFAULT '[]',
      category TEXT DEFAULT 'general',
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Table des règles d'automatisation
  db.exec(`
    CREATE TABLE IF NOT EXISTS automation_rules (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      trigger_type TEXT NOT NULL,
      trigger_config TEXT DEFAULT '{}',
      action_type TEXT NOT NULL,
      action_config TEXT DEFAULT '{}',
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Historique d'exécution des outils
  db.exec(`
    CREATE TABLE IF NOT EXISTS tool_executions (
      id TEXT PRIMARY KEY,
      tool_name TEXT NOT NULL,
      args TEXT DEFAULT '{}',
      result TEXT,
      success INTEGER NOT NULL DEFAULT 1,
      duration_ms INTEGER,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);
  db.exec(`
    CREATE INDEX IF NOT EXISTS idx_tool_executions_created
    ON tool_executions(created_at DESC)
  `);
  db.exec(`
    CREATE INDEX IF NOT EXISTS idx_tool_executions_tool
    ON tool_executions(tool_name, created_at DESC)
  `);

  // Performance indexes for frequently queried tables
  db.exec(`CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at DESC)`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority, status)`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_notes_pinned ON notes(pinned DESC, updated_at DESC)`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category, created_at DESC)`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC)`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages(conversation_id, created_at)`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_cron_enabled ON cron_jobs(enabled, next_run)`);

  // Templates d'outils (configurations sauvegardées)
  db.exec(`
    CREATE TABLE IF NOT EXISTS tool_templates (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      tool_name TEXT NOT NULL,
      args TEXT DEFAULT '{}',
      description TEXT DEFAULT '',
      category TEXT DEFAULT 'general',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Jobs cron (tâches planifiées)
  db.exec(`
    CREATE TABLE IF NOT EXISTS cron_jobs (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      tool_name TEXT NOT NULL,
      args TEXT DEFAULT '{}',
      schedule TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1,
      last_run TEXT,
      next_run TEXT,
      run_count INTEGER NOT NULL DEFAULT 0,
      last_result TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // Connexions SSH sauvegardées
  db.exec(`
    CREATE TABLE IF NOT EXISTS ssh_connections (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      host TEXT NOT NULL,
      port INTEGER NOT NULL DEFAULT 22,
      username TEXT NOT NULL,
      password TEXT DEFAULT '',
      private_key TEXT DEFAULT '',
      last_used TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  return db;
}

/** Instance unique de la base de données (singleton) */
let dbInstance = null;

/**
 * Retourne l'instance de la base de données, en l'initialisant si nécessaire.
 * @returns {Database} Instance better-sqlite3
 */
export function getDb() {
  if (!dbInstance) {
    dbInstance = initializeDatabase();
  }
  return dbInstance;
}

/**
 * Ferme proprement la connexion à la base de données.
 * À appeler lors de l'arrêt du serveur.
 */
export function closeDb() {
  if (dbInstance) {
    dbInstance.close();
    dbInstance = null;
  }
}

export default getDb;
