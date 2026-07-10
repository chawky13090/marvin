import { Client } from '@microsoft/microsoft-graph-client';
import { ConfidentialClientApplication } from '@azure/msal-node';
import { getDb } from '@/lib/database/init';

const SCOPES = ['https://graph.microsoft.com/Mail.Read', 'https://graph.microsoft.com/Mail.Send', 'https://graph.microsoft.com/Mail.ReadWrite'];

function getMsalApp() {
  return new ConfidentialClientApplication({
    auth: {
      clientId: process.env.MICROSOFT_CLIENT_ID || '',
      clientSecret: process.env.MICROSOFT_CLIENT_SECRET || '',
      authority: 'https://login.microsoftonline.com/common',
    },
  });
}

export function getAuthUrl() {
  const app = getMsalApp();
  return app.getAuthCodeUrl({
    scopes: SCOPES,
    redirectUri: process.env.MICROSOFT_REDIRECT_URI || 'http://localhost:3000/api/auth/microsoft/callback',
  });
}

export async function saveTokens(code) {
  const app = getMsalApp();
  const result = await app.acquireTokenByCode({
    code,
    scopes: SCOPES,
    redirectUri: process.env.MICROSOFT_REDIRECT_URI || 'http://localhost:3000/api/auth/microsoft/callback',
  });
  const db = getDb();
  db.prepare(`
    INSERT INTO oauth_tokens (provider, access_token, refresh_token, expires_at)
    VALUES ('microsoft', ?, ?, ?)
    ON CONFLICT(provider) DO UPDATE SET
      access_token = excluded.access_token,
      refresh_token = COALESCE(excluded.refresh_token, refresh_token),
      expires_at = excluded.expires_at,
      updated_at = datetime('now')
  `).run(result.accessToken, null, result.expiresOn?.toISOString() || null);
  return result;
}

export function isConnected() {
  const token = getDb().prepare("SELECT id FROM oauth_tokens WHERE provider = 'microsoft'").get();
  return !!token;
}

async function getGraphClient() {
  const db = getDb();
  const token = db.prepare("SELECT * FROM oauth_tokens WHERE provider = 'microsoft'").get();
  if (!token) throw new Error('Outlook non connecté. Utilisez /api/auth/microsoft pour vous authentifier.');
  return Client.init({ authProvider: (done) => done(null, token.access_token) });
}

export async function listInbox(maxResults = 10) {
  const client = await getGraphClient();
  const result = await client.api('/me/mailFolders/inbox/messages').top(maxResults).select('id,from,toRecipients,subject,receivedDateTime,isRead').get();
  return (result.value || []).map(m => ({
    id: m.id, from: m.from?.emailAddress?.address, subject: m.subject,
    date: m.receivedDateTime, read: m.isRead,
  }));
}

export async function readEmail(emailId) {
  const client = await getGraphClient();
  const m = await client.api(`/me/messages/${emailId}`).get();
  await client.api(`/me/messages/${emailId}`).patch({ isRead: true }).catch(() => {});
  return {
    id: m.id, from: m.from?.emailAddress?.address, subject: m.subject,
    date: m.receivedDateTime, body: m.body?.content?.replace(/<[^>]+>/g, '') || '',
  };
}

export async function sendEmail(to, subject, body) {
  const client = await getGraphClient();
  await client.api('/me/sendMail').post({
    message: {
      subject, body: { contentType: 'Text', content: body },
      toRecipients: [{ emailAddress: { address: to } }],
    }
  });
  return { success: true };
}
