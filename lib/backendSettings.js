import { BACKEND_URL } from '@/lib/backend';


const SETTING_KEY = /^[a-z][a-z0-9_]{0,63}$/;

function requireKey(key) {
  if (typeof key !== 'string' || !SETTING_KEY.test(key)) {
    throw new TypeError('Clé de réglage invalide.');
  }
  return key;
}

export async function getBackendSetting(key, fallback = null) {
  const normalized = requireKey(key);
  const response = await fetch(
    `${BACKEND_URL}/api/settings/${encodeURIComponent(normalized)}`,
    { cache: 'no-store', signal: AbortSignal.timeout(5000) },
  );
  if (!response.ok) {
    throw new Error(`backend_setting_read_${response.status}`);
  }
  const payload = await response.json();
  return payload.value ?? fallback;
}

export async function setBackendSetting(key, value) {
  const normalized = requireKey(key);
  const response = await fetch(
    `${BACKEND_URL}/api/settings/${encodeURIComponent(normalized)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
      signal: AbortSignal.timeout(5000),
    },
  );
  if (!response.ok) {
    throw new Error(`backend_setting_write_${response.status}`);
  }
}
