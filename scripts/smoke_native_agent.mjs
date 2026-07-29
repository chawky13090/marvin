#!/usr/bin/env node
"use strict";

const prompt = process.argv.slice(2).join(" ").trim();
const model = String(process.env.MARVIN_SMOKE_MODEL || "auto").trim();
const summaryOnly = String(process.env.MARVIN_SMOKE_SUMMARY || "") === "1";
if (!prompt) {
  console.error("Usage: node scripts/smoke_native_agent.mjs <prompt>");
  process.exit(2);
}

const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 180_000);
try {
  const response = await fetch("http://127.0.0.1:8005/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      messages: [{ role: "user", content: prompt }],
      model,
    }),
    signal: controller.signal,
  });
  const content = await response.text();
  if (!summaryOnly) {
    process.stdout.write(`${response.status}\n${content}`);
  } else {
    const events = content
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data: "))
      .map((line) => {
        try {
          return JSON.parse(line.slice(6));
        } catch {
          return null;
        }
      })
      .filter(Boolean);
    const text = events
      .filter((event) => event.type === "content" || event.type === "text")
      .map((event) => event.content || event.text || "")
      .join("");
    const compact = events
      .filter((event) => [
        "orchestration_mode",
        "capability_context",
        "model_info",
        "tool_start",
        "tool_end",
        "error",
        "done",
      ].includes(event.type))
      .map((event) => ({
        type: event.type,
        model: event.model,
        mode: event.mode || event.orchestration_mode,
        enabled: event.enabled,
        count: event.count,
        names: event.names,
        systemChars: event.system_chars,
        messageRoles: event.message_roles,
        messageChars: event.message_chars,
        tool: event.tool || event.name || event.tool_name,
        success: event.success,
        error: event.error || event.message,
        stopReason: event.stopReason || event.stop_reason,
      }));
    process.stdout.write(`${response.status}\n${JSON.stringify({ events: compact, text }, null, 2)}\n`);
  }
  if (!response.ok) process.exitCode = 1;
} finally {
  clearTimeout(timer);
}
