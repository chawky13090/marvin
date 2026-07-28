export async function GET() {
  return Response.json(
    {
      error: 'oauth_callback_moved',
      message: 'Reconnectez Microsoft depuis Paramètres > Connexions.',
    },
    { status: 410 },
  );
}
