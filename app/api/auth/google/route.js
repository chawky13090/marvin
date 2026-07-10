import { getAuthUrl } from '@/lib/services/gmailService';

export async function GET() {
  try {
    const url = getAuthUrl();
    return Response.redirect(url);
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 });
  }
}
