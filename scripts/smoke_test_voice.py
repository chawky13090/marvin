"""Smoke test navigateur de la sérialisation vocale du chat."""
from __future__ import annotations

import asyncio
import sys

from playwright.async_api import async_playwright


BASE_URL = "http://localhost:3000"


async def open_voice_ready_conversation(page) -> bool:
    conversation_id = await page.evaluate(
        """async () => {
            const listResponse = await fetch('/api/conversations');
            if (!listResponse.ok) return null;
            const payload = await listResponse.json();
            const conversations = Array.isArray(payload) ? payload : (payload.conversations || []);
            for (const conversation of conversations.slice(0, 20)) {
                const response = await fetch(`/api/conversations/${conversation.id}`);
                if (!response.ok) continue;
                const detail = await response.json();
                const assistants = (detail.messages || []).filter(message => message.role === 'assistant');
                if (assistants.length >= 2) return conversation.id;
            }
            return null;
        }"""
    )
    if not conversation_id:
        return False
    await page.evaluate(
        """conversationId => localStorage.setItem(
            'marvin:last-conversation-id',
            conversationId,
        )""",
        conversation_id,
    )
    await page.reload(wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(1_000)
    return True


async def main() -> int:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome")
        page = await browser.new_page(viewport={"width": 1280, "height": 1200})
        await page.add_init_script(
            """
            window.__marvinAudio = { active: 0, max: 0, plays: 0, pauses: 0 };
            class MarvinTestAudio {
              constructor() { this.onended = null; this.onerror = null; this._active = false; }
              play() {
                this._active = true;
                window.__marvinAudio.active += 1;
                window.__marvinAudio.plays += 1;
                window.__marvinAudio.max = Math.max(window.__marvinAudio.max, window.__marvinAudio.active);
                setTimeout(() => {
                  if (!this._active) return;
                  this._active = false;
                  window.__marvinAudio.active -= 1;
                  if (this.onended) this.onended();
                }, 350);
                return Promise.resolve();
              }
              pause() {
                window.__marvinAudio.pauses += 1;
                if (this._active) {
                  this._active = false;
                  window.__marvinAudio.active -= 1;
                }
              }
            }
            window.Audio = MarvinTestAudio;
            URL.createObjectURL = () => 'blob:marvin-voice-test';
            URL.revokeObjectURL = () => {};
            """
        )
        await page.route(
            "**/api/voice/speak",
            lambda route: route.fulfill(status=200, content_type="audio/mpeg", body=b"ID3"),
        )
        await page.goto(BASE_URL, wait_until="networkidle", timeout=30_000)
        await page.wait_for_timeout(1_000)

        listen = page.locator('button[title="\u00c9couter la r\u00e9ponse"]')
        if await listen.count() < 2:
            await open_voice_ready_conversation(page)
            try:
                await listen.nth(1).wait_for(state="visible", timeout=15_000)
            except Exception:
                pass

        count = await listen.count()
        if count < 2:
            print("ECHEC: aucune conversation avec deux réponses vocalisables.")
            await browser.close()
            return 1

        await listen.nth(0).click()
        await page.wait_for_timeout(80)
        await page.locator('a[href="/jour"]').click()
        await page.wait_for_url("**/jour", timeout=10_000)
        await page.wait_for_timeout(80)
        during_navigation = await page.evaluate("window.__marvinAudio")
        await page.locator('a[href="/"]').click()
        await page.wait_for_url(BASE_URL + "/", timeout=10_000)
        await page.wait_for_timeout(250)
        listen = page.locator('button[title="\u00c9couter la r\u00e9ponse"]')
        if await listen.count() < 1:
            await open_voice_ready_conversation(page)
            try:
                await listen.first.wait_for(state="visible", timeout=15_000)
            except Exception:
                pass
        # Le premier bouton change de titre pendant sa lecture; cliquer une autre réponse.
        await listen.nth(0).click()
        await page.wait_for_timeout(80)
        stop = page.locator('button[title="Arr\u00eater la lecture"]')
        if await stop.count():
            await stop.first.click()
        await page.wait_for_timeout(200)
        stats = await page.evaluate("window.__marvinAudio")
        await browser.close()

    print(f"Voix pendant navigation: {during_navigation}")
    print(f"Voix navigateur: {stats}")
    if (
        during_navigation["max"] > 1
        or during_navigation["active"] not in (0, 1)
        or during_navigation["pauses"] != 0
        or during_navigation["plays"] < 1
        or stats["plays"] < 1
        or stats["max"] > 1
        or stats["active"] != 0
        or stats["pauses"] < 1
    ):
        print("ECHEC: les réponses audio se chevauchent ou ne sont pas nettoyées.")
        return 1
    print("OK: navigation, interruption et lectures restent strictement sérialisées.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
