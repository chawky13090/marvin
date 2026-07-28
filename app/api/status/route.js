// API de vérification de l'état des services
import { listOllamaModels } from '@/lib/ollama';
import { BACKEND_URL as BACKEND } from '@/lib/backend';
import { getBackendSetting } from '@/lib/backendSettings';

export async function GET() {
  // Charger le réglage, les modèles et les credentials en parallèle.
  const [selectedModel, models, credGroups] = await Promise.all([
    getBackendSetting('active_model', null).catch(() => null),
    listOllamaModels(),
    fetch(`${BACKEND}/api/credentials`, { signal: AbortSignal.timeout(3000) })
      .then(r => r.json())
      .then(d => d.groups || {})
      .catch(() => ({})),
  ]);

  // Choisir le modèle actif
  let activeModel = selectedModel;
  if (!activeModel && models.length > 0) {
    const preferences = [
      'hermes3:8b', 'hermes3:latest', 'qwen2.5:7b', 'qwen2.5:3b', 'qwen2.5:1.5b',
      'llama3.1:8b', 'llama3:8b', 'llama3.2:3b', 'llama3.2:latest',
      'qwen3:8b', 'qwen3:4b',
    ];
    activeModel = preferences.find(p => models.includes(p)) || models[0];
  }
  activeModel = activeModel || process.env.OLLAMA_MODEL || 'qwen3:8b';

  const googleConnected    = credGroups.google?.connected    || false;
  const microsoftConnected = credGroups.microsoft?.connected || false;
  const canvaConnected     = credGroups.canva?.connected     || false;
  const searchConnected    = credGroups.search?.connected    || false;
  const aiConnected        = credGroups.ai?.connected        || false;

  return Response.json({
    ollama: {
      connected:     models.length > 0,
      model:         activeModel,
      selectedModel,
      models,
    },
    email: {
      gmail:   { connected: googleConnected },
      outlook: { connected: microsoftConnected },
    },
    calendar: {
      google:  { connected: googleConnected },
      outlook: { connected: microsoftConnected },
    },
    integrations: {
      google:    { connected: googleConnected },
      microsoft: { connected: microsoftConnected },
      canva:     { connected: canvaConnected },
      search:    { connected: searchConnected },
      ai:        { connected: aiConnected },
    },
    demo: !googleConnected,
  });
}
