// Configuration du client Ollama via l'API compatible OpenAI
import { createOpenAI } from '@ai-sdk/openai';

// 127.0.0.1 (IPv4) plutôt que "localhost" : évite la latence/échec de résolution IPv6 (::1)
// sous Windows quand Ollama n'écoute qu'en IPv4 — cause fréquente de "Ollama offline" à tort.
const ollamaBaseURL = process.env.OLLAMA_BASE_URL || 'http://127.0.0.1:11434/v1';

const ollamaProvider = createOpenAI({
  baseURL: ollamaBaseURL,
  apiKey: 'ollama',
});

/**
 * Retourne le provider Ollama pour un modèle donné.
 * Utilise .chat() pour forcer le format Chat Completions (/v1/chat/completions)
 * au lieu du Responses API (/v1/responses) qui génère des item_reference non supportés par Ollama.
 */
function ollama(modelName) {
  return ollamaProvider.chat(modelName);
}

export default ollama;

// Cache pour la liste des modèles (évite de spammer l'API Ollama)
let modelsCache = { models: [], lastFetch: 0 };
const CACHE_TTL = 30000; // 30 secondes

/**
 * Liste les modèles installés sur Ollama (avec cache de 30s)
 */
export async function listOllamaModels() {
  const now = Date.now();
  if (now - modelsCache.lastFetch < CACHE_TTL && modelsCache.models.length > 0) {
    return modelsCache.models;
  }
  
  try {
    // .replace('localhost','127.0.0.1') au cas où OLLAMA_BASE_URL contiendrait encore "localhost".
    // Timeout 8 s : Ollama peut être occupé (chargement de modèle, inférence) et /api/tags se met en file.
    const apiURL = ollamaBaseURL.replace(/\/v1$/, '').replace('localhost', '127.0.0.1') + '/api/tags';
    const res = await fetch(apiURL, { signal: AbortSignal.timeout(8000) });
    if (res.ok) {
      const data = await res.json();
      const names = data.models?.map(m => m.name) || [];
      modelsCache = { models: names, lastFetch: now };
      return names;
    }
  } catch {
    // Ollama non disponible
  }
  return modelsCache.models; // retourner le cache même expiré
}

/**
 * Retourne le modèle actif (BD > auto-détection > défaut)
 */
export async function getActiveModel(selectedModel = null) {
  const defaultModel = process.env.OLLAMA_MODEL || 'qwen3:8b';

  // 1. Priorité absolue : valeur fournie par l'unique propriétaire FastAPI.
  if (typeof selectedModel === 'string' && selectedModel) {
    return selectedModel;
  }

  // 2. Auto-détection parmi les modèles installés
  // Préférer les modèles SANS thinking mode pour compatibilité multi-step Ollama
  const models = await listOllamaModels();
  if (models.length > 0) {
    const preferences = [
      // Hermes3 : meilleur pour le function calling / tool use
      'hermes3:8b', 'hermes3:latest',
      // Qwen2.5 : excellent multilingue + tool use, sans thinking mode
      'qwen2.5:7b', 'qwen2.5:3b', 'qwen2.5:1.5b',
      // Llama3
      'llama3.1:8b', 'llama3:8b', 'llama3.2:3b', 'llama3.2:latest',
      // Qwen3 en dernier (thinking mode peut causer des lenteurs)
      'qwen3:8b', 'qwen3:4b',
    ];
    for (const pref of preferences) {
      const match = models.find(n => n === pref);
      if (match) return match;
    }
    return models[0]; // Premier modèle disponible
  }
  
  return defaultModel;
}
