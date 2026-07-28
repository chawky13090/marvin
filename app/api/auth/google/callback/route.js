export async function GET() {
  return Response.json(
    {
      error: 'oauth_callback_moved',
      message: 'Reconnectez Google depuis Paramètres > Connexions.',
    },
    { status: 410 },
  );
}
