import { saveTokens } from '@/lib/services/outlookService';

export async function GET(req) {
  const { searchParams } = new URL(req.url);
  const code = searchParams.get('code');
  if (!code) return new Response('Code manquant', { status: 400 });
  try {
    await saveTokens(code);
    return new Response(
      `<html><body><script>window.close(); window.opener && window.opener.location.reload();</script><p>Outlook connecté ! Vous pouvez fermer cette fenêtre.</p></body></html>`,
      { headers: { 'Content-Type': 'text/html' } }
    );
  } catch (e) {
    return new Response(`Erreur: ${e.message}`, { status: 500 });
  }
}
