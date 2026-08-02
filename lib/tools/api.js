import { BACKEND_URL } from '@/lib/backend';

export async function callBackendTool(toolName, args) {
  try {
    const response = await fetch(`${BACKEND_URL}/api/tools`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ toolName, args }),
    });
    return (await response.json()).result || {};
  } catch (error) {
    return { error: String(error) };
  }
}
