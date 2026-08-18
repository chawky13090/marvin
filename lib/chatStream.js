/** Transport SSE reprenable du chat Marvin, indépendant de React. */

function wait(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, milliseconds);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export class ChatStreamTransportError extends Error {
  constructor(cause, attempts) {
    super(
      `Connexion à Marvin interrompue après ${attempts} tentatives. `
      + 'La demande n’a pas été rejouée ; vérifiez l’état du backend puis reprenez la conversation.',
      { cause },
    );
    this.name = 'ChatStreamTransportError';
    this.attempts = attempts;
  }
}

class ChatStreamHttpError extends Error {
  constructor(status) {
    super(`HTTP ${status}`);
    this.name = 'ChatStreamHttpError';
    this.status = status;
  }
}

function retryable(error) {
  if (error?.name === 'AbortError') return false;
  if (error instanceof ChatStreamHttpError) {
    return error.status === 408 || error.status === 429 || error.status >= 500;
  }
  return true;
}

export async function* durableChatEvents({
  url,
  payload,
  signal,
  maxReconnects = 6,
  reconnectDelayMs = 250,
  maxReconnectDelayMs = 4000,
}) {
  let cursor = Number.isInteger(payload.afterEvent) ? payload.afterEvent : 0;
  let reconnects = 0;

  while (true) {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(payload.requestId ? { 'X-Request-ID': payload.requestId } : {}),
        },
        body: JSON.stringify({ ...payload, afterEvent: cursor }),
        signal,
      });
      if (!response.ok) throw new ChatStreamHttpError(response.status);
      if (!response.body) throw new Error('Flux SSE absent de la réponse backend.');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) return;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;
          let event;
          try { event = JSON.parse(raw); } catch { continue; }
          if (Number.isInteger(event.turnSeq)) {
            if (event.turnSeq <= cursor) continue;
            cursor = event.turnSeq;
          }
          yield event;
        }
      }
    } catch (error) {
      if (!retryable(error)) throw error;
      if (reconnects >= maxReconnects) {
        throw new ChatStreamTransportError(error, reconnects + 1);
      }
      reconnects += 1;
      const delay = Math.min(
        reconnectDelayMs * (2 ** (reconnects - 1)),
        maxReconnectDelayMs,
      );
      await wait(delay, signal);
    }
  }
}
