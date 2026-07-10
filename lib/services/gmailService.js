import { google } from 'googleapis';
import { getDb } from '@/lib/database/init';

const SCOPES = [
  'https://www.googleapis.com/auth/gmail.readonly',
  'https://www.googleapis.com/auth/gmail.send',
  'https://www.googleapis.com/auth/gmail.modify',
  'https://www.googleapis.com/auth/gmail.compose',
  // Calendrier : lecture + création/modification d'événements sur Google Agenda
  'https://www.googleapis.com/auth/calendar',
  'https://www.googleapis.com/auth/calendar.events',
];

export function getOAuth2Client() {
  return new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET,
    process.env.GOOGLE_REDIRECT_URI || 'http://localhost:3000/api/auth/google/callback'
  );
}

export function getAuthUrl() {
  return getOAuth2Client().generateAuthUrl({
    access_type: 'offline',
    scope: SCOPES,
    prompt: 'consent',
  });
}

export async function saveTokens(code) {
  const client = getOAuth2Client();
  const { tokens } = await client.getToken(code);
  const db = getDb();
  db.prepare(`
    INSERT INTO oauth_tokens (provider, access_token, refresh_token, expires_at)
    VALUES ('google', ?, ?, ?)
    ON CONFLICT(provider) DO UPDATE SET
      access_token = excluded.access_token,
      refresh_token = COALESCE(excluded.refresh_token, refresh_token),
      expires_at = excluded.expires_at,
      updated_at = datetime('now')
  `).run(
    tokens.access_token,
    tokens.refresh_token || null,
    tokens.expiry_date ? new Date(tokens.expiry_date).toISOString() : null
  );
  return tokens;
}

export async function getGmailClient() {
  const db = getDb();
  const token = db.prepare("SELECT * FROM oauth_tokens WHERE provider = 'google'").get();
  if (!token) throw new Error('Gmail non connecté. Utilisez /api/auth/google pour vous authentifier.');
  const client = getOAuth2Client();
  client.setCredentials({
    access_token: token.access_token,
    refresh_token: token.refresh_token,
    expiry_date: token.expires_at ? new Date(token.expires_at).getTime() : null,
  });
  client.on('tokens', (tokens) => {
    if (tokens.access_token) {
      db.prepare(`UPDATE oauth_tokens SET access_token = ?, expires_at = ?, updated_at = datetime('now') WHERE provider = 'google'`)
        .run(tokens.access_token, tokens.expiry_date ? new Date(tokens.expiry_date).toISOString() : null);
    }
  });
  return google.gmail({ version: 'v1', auth: client });
}

export function isConnected() {
  const db = getDb();
  const token = db.prepare("SELECT id FROM oauth_tokens WHERE provider = 'google'").get();
  return !!token;
}

function decodeBase64(data) {
  return Buffer.from(data.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8');
}

function getEmailBody(payload) {
  if (payload.body?.data) return decodeBase64(payload.body.data);
  if (payload.parts) {
    const textPart = payload.parts.find(p => p.mimeType === 'text/plain');
    if (textPart?.body?.data) return decodeBase64(textPart.body.data);
    const htmlPart = payload.parts.find(p => p.mimeType === 'text/html');
    if (htmlPart?.body?.data) return decodeBase64(htmlPart.body.data).replace(/<[^>]+>/g, '');
  }
  return '';
}

export async function listInbox(maxResults = 10) {
  const gmail = await getGmailClient();
  const list = await gmail.users.messages.list({ userId: 'me', maxResults, labelIds: ['INBOX'] });
  if (!list.data.messages) return [];
  const emails = await Promise.all(
    list.data.messages.map(async ({ id }) => {
      const msg = await gmail.users.messages.get({ userId: 'me', id, format: 'metadata', metadataHeaders: ['From', 'To', 'Subject', 'Date'] });
      const headers = msg.data.payload?.headers || [];
      const get = (name) => headers.find(h => h.name === name)?.value || '';
      return {
        id,
        from: get('From'), to: get('To'), subject: get('Subject'), date: get('Date'),
        read: !msg.data.labelIds?.includes('UNREAD'),
        threadId: msg.data.threadId,
      };
    })
  );
  return emails;
}

export async function readEmail(emailId) {
  const gmail = await getGmailClient();
  const msg = await gmail.users.messages.get({ userId: 'me', id: emailId });
  const headers = msg.data.payload?.headers || [];
  const get = (name) => headers.find(h => h.name === name)?.value || '';
  // Mark as read
  await gmail.users.messages.modify({ userId: 'me', id: emailId, requestBody: { removeLabelIds: ['UNREAD'] } }).catch(() => {});
  return {
    id: emailId,
    from: get('From'), to: get('To'), subject: get('Subject'), date: get('Date'),
    body: getEmailBody(msg.data.payload),
    threadId: msg.data.threadId,
  };
}

export async function searchEmails(query, maxResults = 10) {
  const gmail = await getGmailClient();
  const list = await gmail.users.messages.list({ userId: 'me', q: query, maxResults });
  if (!list.data.messages) return [];
  return Promise.all(list.data.messages.map(async ({ id }) => {
    const msg = await gmail.users.messages.get({ userId: 'me', id, format: 'metadata', metadataHeaders: ['From', 'Subject', 'Date'] });
    const headers = msg.data.payload?.headers || [];
    const get = (name) => headers.find(h => h.name === name)?.value || '';
    return { id, from: get('From'), subject: get('Subject'), date: get('Date') };
  }));
}

function buildMimeMessage({ to, subject, body, replyToMessageId, threadId }) {
  const headers = [
    `To: ${to}`,
    `Subject: ${subject}`,
    'Content-Type: text/plain; charset=utf-8',
    'MIME-Version: 1.0',
  ];
  if (replyToMessageId) headers.push(`In-Reply-To: ${replyToMessageId}`, `References: ${replyToMessageId}`);
  const message = headers.join('\r\n') + '\r\n\r\n' + body;
  return Buffer.from(message).toString('base64url');
}

export async function sendEmail(to, subject, body) {
  const gmail = await getGmailClient();
  const raw = buildMimeMessage({ to, subject, body });
  const result = await gmail.users.messages.send({ userId: 'me', requestBody: { raw } });
  return { success: true, messageId: result.data.id };
}

export async function replyToEmail(emailId, body) {
  const gmail = await getGmailClient();
  const original = await readEmail(emailId);
  const subject = original.subject.startsWith('Re:') ? original.subject : `Re: ${original.subject}`;
  const raw = buildMimeMessage({ to: original.from, subject, body, replyToMessageId: emailId, threadId: original.threadId });
  const result = await gmail.users.messages.send({ userId: 'me', requestBody: { raw, threadId: original.threadId } });
  return { success: true, messageId: result.data.id };
}

export async function createDraft(to, subject, body) {
  const gmail = await getGmailClient();
  const raw = buildMimeMessage({ to, subject, body });
  const result = await gmail.users.drafts.create({ userId: 'me', requestBody: { message: { raw } } });
  return { success: true, draftId: result.data.id };
}
