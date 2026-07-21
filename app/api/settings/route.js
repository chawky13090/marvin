import { NextResponse } from 'next/server';
import { getSetting, setSetting } from '@/lib/database/queries';
import { getActiveModel, listOllamaModels } from '@/lib/ollama';
import { BACKEND_URL as BACKEND } from '@/lib/backend';

// v2.107 — les actions mémoire (get/create/delete/clear) proxient désormais vers le
// backend Python (voir app/api/conversations/route.js pour le contexte général) : elles
// dupliquaient memory_save/memory_list/memory_delete, déjà des outils de chat Python
// écrivant dans le même data/secretary.db. La gestion de modèles Ollama (pull/delete/
// list/set_model) reste ici : elle n'a pas d'équivalent Python (spawn de processus local).
export async function GET() {
  try {
    const activeModel = await getActiveModel();
    const selectedModel = getSetting('active_model') || null;
    const models = await listOllamaModels();
    return NextResponse.json({
      success: true,
      activeModel,
      selectedModel,
      models
    });
  } catch (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function POST(req) {
  try {
    const body = await req.json();
    const { action, modelName } = body;
    
    if (action === 'set_model') {
      if (!modelName) {
        return NextResponse.json({ error: 'modelName requis' }, { status: 400 });
      }
      setSetting('active_model', modelName);
      console.log('[API Settings] Nouveau modèle actif défini dans la BD :', modelName);
      return NextResponse.json({ success: true, message: `Modèle actif défini sur ${modelName}` });
    }
    
    if (action === 'pull_model') {
      if (!modelName) {
        return NextResponse.json({ error: 'modelName requis' }, { status: 400 });
      }
      const { spawn } = await import('child_process');
      console.log(`[API Settings] Téléchargement asynchrone du modèle : ${modelName}`);
      
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
      if (!modelName) {
        return NextResponse.json({ error: 'modelName requis' }, { status: 400 });
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
      } catch (err) {
        return NextResponse.json({ error: err.message }, { status: 500 });
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
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
