import { getAuthUrl } from '@/lib/services/outlookService';

export async function GET() {
  try {
    const url = await getAuthUrl();
    return Response.redirect(url);
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 });
  }
}
