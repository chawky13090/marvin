import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import { getActiveModel, listOllamaModels } from '@/lib/ollama';
import { BACKEND_URL as BACKEND } from '@/lib/backend';
import { getBackendSetting, setBackendSetting } from '@/lib/backendSettings';


const MODEL_NAME = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/;

function validModelName(value) {
  return typeof value === 'string' && MODEL_NAME.test(value);
}

function reportFailure(action, error) {
  const incident = randomUUID();
  console.error(JSON.stringify({
    timestamp: new Date().toISOString(),
    level: 'error',
    component: 'next.settings',
    action,
    incident,
    error_type: error?.constructor?.name || 'Error',
  }));
  return incident;
}

// v2.107 — les actions mémoire (get/create/delete/clear) proxient désormais vers le
// backend Python (voir app/api/conversations/route.js pour le contexte général) : elles
// dupliquaient memory_save/memory_list/memory_delete, déjà des outils de chat Python
// écrivant dans le même data/secretary.db. La gestion de modèles Ollama (pull/delete/
// list/set_model) reste ici : elle n'a pas d'équivalent Python (spawn de processus local).
export async function GET() {
  try {
    const [selectedModel, models] = await Promise.all([
      getBackendSetting('active_model', null),
      listOllamaModels(),
    ]);
    const activeModel = await getActiveModel(selectedModel);
    return NextResponse.json({
      success: true,
      activeModel,
      selectedModel,
      models
    });
  } catch (error) {
    const incident = reportFailure('read', error);
    return NextResponse.json(
      { error: 'Réglages temporairement indisponibles.', incident },
      { status: 503 },
    );
  }
}

export async function POST(req) {
  try {
    const body = await req.json();
    const { action, modelName } = body;
    
    if (action === 'set_model') {
      if (!validModelName(modelName)) {
        return NextResponse.json({ error: 'modelName invalide' }, { status: 400 });
      }
      await setBackendSetting('active_model', modelName);
      return NextResponse.json({ success: true, message: `Modèle actif défini sur ${modelName}` });
    }
    
    if (action === 'pull_model') {
      if (!validModelName(modelName)) {
        return NextResponse.json({ error: 'modelName invalide' }, { status: 400 });
      }
      const { spawn } = await import('child_process');
      const process = spawn('ollama', ['pull', modelName], {
        detached: true,
        stdio: 'ignore'
      });
      process.unref();
      
      return NextResponse.json({ 
        success: true, 
        message: `Téléchargement du modèle "${modelName}" lancé en arrière-plan.` 
      });
    }

    if (action === 'list_models') {
      const models = await listOllamaModels();
      return NextResponse.json({ success: true, models });
    }

    if (action === 'delete_model') {
      if (!validModelName(modelName)) {
        return NextResponse.json({ error: 'modelName invalide' }, { status: 400 });
      }
      try {
        const ollamaURL = (process.env.OLLAMA_BASE_URL || 'http://127.0.0.1:11434/v1').replace(/\/v1$/, '').replace('localhost', '127.0.0.1');
        const res = await fetch(`${ollamaURL}/api/delete`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: modelName }),
        });
        if (res.ok) {
          return NextResponse.json({ success: true, message: `Modèle "${modelName}" supprimé.` });
        }
        return NextResponse.json({ error: 'Échec suppression' }, { status: 500 });
      } catch (error) {
        const incident = reportFailure('delete_model', error);
        return NextResponse.json(
          { error: 'Suppression impossible.', incident },
          { status: 503 },
        );
      }
    }

    if (action === 'get_memories') {
      const r = await fetch(`${BACKEND}/api/memories`, { signal: AbortSignal.timeout(8000) });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      const memories = await r.json();
      return NextResponse.json({ success: true, memories });
    }

    if (action === 'create_memory') {
      const { content, category } = body;
      if (!content) {
        return NextResponse.json({ error: 'content requis' }, { status: 400 });
      }
      const r = await fetch(`${BACKEND}/api/memories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, category: category || 'fact' }),
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      const memory = await r.json();
      return NextResponse.json({ success: true, memory });
    }

    if (action === 'delete_memory') {
      const { id } = body;
      if (!id) {
        return NextResponse.json({ error: 'id requis' }, { status: 400 });
      }
      const r = await fetch(`${BACKEND}/api/memories/${id}`, { method: 'DELETE', signal: AbortSignal.timeout(8000) });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      return NextResponse.json({ success: true, message: 'Souvenir supprimé.' });
    }

    if (action === 'clear_memories') {
      const r = await fetch(`${BACKEND}/api/memories`, { method: 'DELETE', signal: AbortSignal.timeout(8000) });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      return NextResponse.json({ success: true, message: 'Toute la mémoire a été effacée.' });
    }
    
    return NextResponse.json({ error: 'Action non reconnue' }, { status: 400 });
  } catch (error) {
    const incident = reportFailure('write', error);
    return NextResponse.json(
      { error: 'Action de réglage impossible.', incident },
      { status: 503 },
    );
  }
}
