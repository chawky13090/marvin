function messageText(message) {
  const textParts = Array.isArray(message?.parts)
    ? message.parts.filter((part) => part?.type === 'text' && typeof part.text === 'string')
    : [];
  if (textParts.length > 0) return textParts.map((part) => part.text).join('');
  return typeof message?.content === 'string' ? message.content : '';
}

function messageTools(message) {
  if (Array.isArray(message?.toolInvocations) && message.toolInvocations.length > 0) {
    return message.toolInvocations;
  }
  if (!Array.isArray(message?.parts)) return [];
  return message.parts
    .filter((part) => part?.type === 'tool-invocation' && part.toolInvocation)
    .map((part) => part.toolInvocation);
}

function isToolOnlyAssistant(message) {
  return message?.role === 'assistant'
    && messageText(message).trim() === ''
    && messageTools(message).length > 0;
}

function pollingToolName(message) {
  if (message?.role !== 'assistant' || messageText(message).length > 500) return '';
  const tools = messageTools(message);
  if (tools.length !== 1) return '';
  const name = tools[0]?.toolName || '';
  return name === 'code_workspace_status' || name === 'long_task_status' || name.endsWith('_job_status')
    ? name
    : '';
}

/** Regroupe les messages techniques consécutifs sans modifier les originaux. */
export function groupConversationMessages(messages) {
  if (!Array.isArray(messages)) return [];
  const grouped = [];

  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    const pollingName = pollingToolName(message);
    if (pollingName) {
      const run = [message];
      while (index + 1 < messages.length && pollingToolName(messages[index + 1]) === pollingName) {
        run.push(messages[index + 1]);
        index += 1;
      }
      if (run.length > 1) {
        const last = run[run.length - 1];
        grouped.push({
          ...last,
          id: `status-activity:${run.map((item) => item.id || '').join(':')}`,
          content: messageText(last),
          parts: [],
          toolInvocations: run.flatMap(messageTools),
          groupedMessageCount: run.length,
        });
        continue;
      }
    }

    if (!isToolOnlyAssistant(message)) {
      grouped.push(message);
      continue;
    }

    const run = [message];
    while (index + 1 < messages.length && isToolOnlyAssistant(messages[index + 1])) {
      run.push(messages[index + 1]);
      index += 1;
    }
    if (run.length === 1) {
      grouped.push(message);
      continue;
    }

    const firstPosition = index - run.length + 1;
    const ids = run.map((item, itemIndex) => item.id || `position-${firstPosition + itemIndex}`);
    const last = run[run.length - 1];
    grouped.push({
      ...run[0],
      id: `activity:${ids.join(':')}`,
      content: '',
      parts: [],
      toolInvocations: run.flatMap(messageTools),
      modelInfo: last.modelInfo || run[0].modelInfo,
      cortexTrace: last.cortexTrace || run[0].cortexTrace,
      groupedMessageCount: run.length,
    });
  }
  return grouped;
}

const SENSITIVE_AUDIT_KEY = /(?:password|passwd|token|secret|api[_-]?key|authorization|cookie|credential)/i;

function sanitizeAuditValue(value, key = '', seen = new WeakSet()) {
  if (SENSITIVE_AUDIT_KEY.test(key)) return '[MASQUÉ]';
  if (value === null || typeof value !== 'object') return value;
  if (seen.has(value)) return '[RÉFÉRENCE CIRCULAIRE]';
  seen.add(value);
  if (Array.isArray(value)) return value.map((item) => sanitizeAuditValue(item, '', seen));
  return Object.fromEntries(
    Object.entries(value).map(([childKey, childValue]) => [
      childKey,
      sanitizeAuditValue(childValue, childKey, seen),
    ]),
  );
}

export function createConversationAudit(messages, exportedAt = new Date()) {
  const safeMessages = sanitizeAuditValue(Array.isArray(messages) ? messages : []);
  return {
    schema: 'marvin.conversation.audit.v1',
    exported_at: exportedAt.toISOString(),
    message_count: safeMessages.length,
    messages: safeMessages,
  };
}

export function conversationAuditToMarkdown(audit) {
  const lines = [
    '# Audit de conversation Marvin',
    '',
    `- Exporté le : ${audit.exported_at}`,
    `- Messages : ${audit.message_count}`,
    '- Secrets techniques connus : masqués automatiquement',
    '',
  ];

  for (const [index, message] of (audit.messages || []).entries()) {
    const role = message.role === 'user' ? 'Utilisateur' : message.role === 'assistant' ? 'Marvin' : 'Outil';
    lines.push(`## ${index + 1}. ${role}`, '');
    const text = messageText(message).trim();
    if (text) lines.push(text, '');
    const tools = messageTools(message);
    for (const tool of tools) {
      lines.push(`### Outil : ${tool.toolName || 'inconnu'}`, '');
      lines.push(`- État : ${tool.state || (tool.result !== undefined ? 'result' : 'pending')}`, '');
      if (tool.args !== undefined) {
        lines.push('#### Paramètres', '', '~~~~json', JSON.stringify(tool.args, null, 2), '~~~~', '');
      }
      if (tool.result !== undefined) {
        lines.push('#### Résultat', '', '~~~~json', JSON.stringify(tool.result, null, 2), '~~~~', '');
      }
    }
  }
  return `${lines.join('\n').trim()}\n`;
}
