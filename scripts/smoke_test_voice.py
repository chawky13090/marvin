"""Smoke test navigateur de la sérialisation vocale du chat."""
from __future__ import annotations

import asyncio
import sys

from playwright.async_api import async_playwright


BASE_URL = "http://localhost:3000"


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

        listen = page.locator('button[title="Écouter la réponse"]')
        if await listen.count() < 2:
            conversations = page.locator('div[style*="cursor: pointer"][style*="border-left"] span')
            for index in range(min(await conversations.count(), 8)):
                await conversations.nth(index).click()
                await page.wait_for_timeout(500)
                if await listen.count() >= 2:
                    break

        count = await listen.count()
        if count < 2:
            print("ECHEC: aucune conversation avec deux réponses vocalisables.")
            await browser.close()
            return 1

        await listen.nth(0).click()
        await page.wait_for_timeout(80)
        # Le premier bouton change de titre pendant sa lecture; cliquer une autre réponse.
        await listen.nth(0).click()
        await page.wait_for_timeout(500)
        stop = page.locator('button[title="Arrêter la lecture"]')
        if await stop.count():
            await stop.first.click()
        await page.wait_for_timeout(200)
        stats = await page.evaluate("window.__marvinAudio")
        await browser.close()

    print(f"Voix navigateur: {stats}")
    if stats["plays"] < 2 or stats["max"] > 1 or stats["active"] != 0 or stats["pauses"] < 1:
        print("ECHEC: les réponses audio se chevauchent ou ne sont pas nettoyées.")
        return 1
    print("OK: deux lectures rapides restent strictement sérialisées.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
