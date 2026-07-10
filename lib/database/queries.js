/**
 * Requêtes préparées pour toutes les opérations de base de données.
 * Chaque fonction utilise des requêtes préparées pour la performance et la sécurité.
 *
 * v2.107 — élagué aux seules fonctions encore réellement appelées : `getSetting`
 * (app/api/settings, app/api/status) et `setSetting` (app/api/settings). Conversations,
 * messages, tasks, notes, projects, memories, tokens OAuth, journal fichiers et templates
 * email ont tous été retirés : remplacés par un proxy vers le backend Python (voir
 * app/api/conversations, app/api/notes, app/api/tasks, app/api/projects, l'action mémoire
 * dans app/api/settings), ou jamais appelés par aucune route/page (OAuth/journal/templates —
 * code mort préexistant, confirmé par grep avant suppression).
 */
import { getDb } from './init.js';

// ============================================
// PARAMÈTRES
// ============================================

/**
 * Récupère la valeur d'un paramètre.
 * @param {string} key - Clé du paramètre
 * @param {*} [defaultValue=null] - Valeur par défaut si le paramètre n'existe pas
 * @returns {*} La valeur du paramètre (parsée depuis JSON) ou la valeur par défaut
 */
export function getSetting(key, defaultValue = null) {
  const db = getDb();
  const stmt = db.prepare('SELECT value FROM settings WHERE key = ?');
  const row = stmt.get(key);
  if (!row) return defaultValue;
  try {
    return JSON.parse(row.value);
  } catch {
    return row.value;
  }
}

/**
 * Définit la valeur d'un paramètre (upsert).
 * @param {string} key - Clé du paramètre
 * @param {*} value - Valeur à stocker (sera sérialisée en JSON)
 */
export function setSetting(key, value) {
  const db = getDb();
  const serialized = typeof value === 'string' ? value : JSON.stringify(value);
  const stmt = db.prepare(`
    INSERT OR REPLACE INTO settings (key, value, updated_at)
    VALUES (?, ?, datetime('now'))
  `);
  stmt.run(key, serialized);
}
