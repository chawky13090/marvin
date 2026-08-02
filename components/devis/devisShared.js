import { BACKEND_URL as BACKEND } from '@/lib/backend';

export const card = {
  background: 'var(--bg-glass)',
  border: '1px solid var(--border)',
  borderRadius: '12px',
  padding: '16px 20px',
};

export const input = {
  width: '100%', padding: '8px 12px',
  background: 'var(--bg-primary)', border: '1px solid var(--border)',
  borderRadius: '6px', color: 'var(--text-primary)', fontSize: '13px',
  outline: 'none', boxSizing: 'border-box',
};

export const btn = (variant = 'default') => ({
  padding: '8px 16px', borderRadius: '6px', border: 'none',
  cursor: 'pointer', fontSize: '13px', fontWeight: 600,
  transition: 'all 0.15s',
  background: variant === 'primary' ? 'linear-gradient(135deg,#4f8cff,#38bdf8)'
            : variant === 'danger'  ? 'rgba(239,68,68,0.15)'
            : 'rgba(255,255,255,0.05)',
  color: variant === 'primary' ? '#111'
       : variant === 'danger'  ? '#f87171'
       : 'var(--text-primary)',
  border: variant === 'danger' ? '1px solid rgba(239,68,68,0.3)' : '1px solid transparent',
});

export async function api(path, opts = {}) {
  const res = await fetch(`${BACKEND}${path}`, opts);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})).then((data) => data.detail || '');
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export async function tool(name, args) {
  const res = await fetch(`${BACKEND}/api/tools`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toolName: name, args }),
  });
  const data = await res.json();
  return data.result || {};
}
