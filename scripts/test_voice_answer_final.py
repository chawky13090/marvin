"""Régression navigateur : une réponse Cloud answer_final doit être vocalisée."""
from __future__ import annotations

import asyncio
import sys

from playwright.async_api import Route, async_playwright


BASE_URL = "http://127.0.0.1:3000"


async def main() -> int:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome")
        page = await browser.new_page(viewport={"width": 1100, "height": 850})
        await page.add_init_script(
            """
            localStorage.removeItem('marvin:last-conversation-id');
            window.__marvinVoiceRegression = { plays: 0, tts: 0 };
            class MarvinRegressionAudio {
              constructor() { this.onended = null; this.onerror = null; }
              play() {
                window.__marvinVoiceRegression.plays += 1;
                setTimeout(() => this.onended && this.onended(), 20);
                return Promise.resolve();
              }
              pause() {}
              set src(value) {}
            }
            window.Audio = MarvinRegressionAudio;
            URL.createObjectURL = () => 'blob:marvin-answer-final';
            URL.revokeObjectURL = () => {};
            """
        )

        async def route_chat(route: Route) -> None:
            body = (
                'data: {"type":"answer_final","text":"Réponse Cloud uniquement finale.",'
                '"turnSeq":1}\n\n'
                'data: {"type":"done","turnSeq":2}\n\n'
            )
            await route.fulfill(
                status=200,
                content_type="text/event-stream; charset=utf-8",
                body=body,
            )

        async def route_tts(route: Route) -> None:
            await page.evaluate("window.__marvinVoiceRegression.tts += 1")
            await route.fulfill(status=200, content_type="audio/mpeg", body=b"ID3")

        await page.route("**/api/chat", route_chat)
        await page.route("**/api/voice/speak", route_tts)
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(800)

        new_conversation = page.get_by_role("button", name="+ Nouvelle conversation")
        if await new_conversation.count() == 1:
            await new_conversation.click()

        voice_mode = page.locator('button[title^="Activer le mode vocal"]')
        await voice_mode.wait_for(state="visible", timeout=15_000)
        await voice_mode.click()

        editor = page.locator("textarea")
        if await editor.count() != 1:
            print("ECHEC: composeur vocal introuvable ou ambigu.")
            await browser.close()
            return 1
        await editor.fill("Réponds brièvement.")
        await editor.press("Enter")
        await page.get_by_text("Réponse Cloud uniquement finale.", exact=True).wait_for(
            state="visible",
            timeout=10_000,
        )
        await page.wait_for_timeout(250)
        stats = await page.evaluate("window.__marvinVoiceRegression")
        await browser.close()

    print(f"Answer-final vocal: {stats}")
    if stats["tts"] != 1 or stats["plays"] != 1:
        print("ECHEC: la réponse answer_final n'a pas été synthétisée et lue exactement une fois.")
        return 1
    print("OK: answer_final est synthétisé et lu une seule fois.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
