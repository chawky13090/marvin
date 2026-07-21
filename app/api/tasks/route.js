import { NextResponse } from 'next/server';
import { BACKEND_URL as BACKEND } from '@/lib/backend';

// v2.107 — proxy pur vers le backend Python (voir app/api/conversations/route.js).
// Interface externe (POST {action, ...}) conservée à l'identique pour ne pas toucher
// app/tasks/page.jsx.
export async function GET(req) {
  const { searchParams } = new URL(req.url);
  const status = searchParams.get('status');
  const priority = searchParams.get('priority');
  try {
    const url = new URL(`${BACKEND}/api/tasks`);
    if (status) url.searchParams.set('status', status);
    if (priority) url.searchParams.set('priority', priority);
    const r = await fetch(url, { signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw new Error(`Backend ${r.status}`);
    const tasks = await r.json();
    return NextResponse.json({ tasks, count: tasks.length });
  } catch (e) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}

export async function POST(req) {
  const body = await req.json();
  const { action, ...data } = body;
  try {
    if (action === 'create') {
      const r = await fetch(`${BACKEND}/api/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: data.title,
          description: data.description || '',
          priority: data.priority || 'medium',
          due_date: data.due_date || null,
          tags: data.tags || [],
        }),
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      const task = await r.json();
      return NextResponse.json({ success: true, task });
    }
    if (action === 'update') {
      const { id, ...updates } = data;
      const r = await fetch(`${BACKEND}/api/tasks/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      const task = await r.json();
      return NextResponse.json({ success: true, task });
    }
    if (action === 'delete') {
      const r = await fetch(`${BACKEND}/api/tasks/${data.id}`, { method: 'DELETE', signal: AbortSignal.timeout(8000) });
      if (!r.ok) throw new Error(`Backend ${r.status}`);
      return NextResponse.json(await r.json());
    }
    return NextResponse.json({ error: 'Action inconnue' }, { status: 400 });
  } catch (e) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
