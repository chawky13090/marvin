import { BACKEND_URL } from '@/lib/backend';

export async function GET() {
  return Response.redirect(`${BACKEND_URL}/api/oauth/microsoft/start`);
}
