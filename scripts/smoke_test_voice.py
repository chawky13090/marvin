"""Smoke test navigateur de la sérialisation vocale du chat."""
from __future__ import annotations

import asyncio
import atexit
import sys
import uuid
from pathlib import Path

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database as db  # noqa: E402
from smoke_run_lock import browser_smoke_lock  # noqa: E402


BASE_URL = "http://localhost:3000"
VOICE_FIXTURE_PREFIX = "[SMOKE:voice:"


async def navigate_with_marvin_menu(page, label: str, path: str) -> None:
    """Suit la navigation adaptative sans dépendre de l'ancienne sidebar."""
    opener = page.get_by_role("button", name="Ouvrir la navigation Marvin")
    await opener.wait_for(state="visible", timeout=15_000)
    await opener.click()
    # Le composition root peut conserver une navigation "full" montée pendant
    # l'ouverture du tiroir. Cibler explicitement l'overlay évite un locator
    # ambigu sans affaiblir le test du parcours utilisateur réel.
    navigation = page.locator('.adaptive-nav--overlay:visible')
    link = navigation.get_by_role("link", name=label, exact=True)
    await link.wait_for(state="visible", timeout=10_000)
    await link.click()
    await page.wait_for_url(BASE_URL + path, timeout=10_000)


def create_voice_fixture(run_id: str) -> str:
    """Cree une conversation bornee, sans LLM ni donnee utilisateur."""
    conversation = db.create_conversation(
        f"{VOICE_FIXTURE_PREFIX}{run_id}] Test temporaire de serialisation vocale"
    )
    conversation_id = str(conversation["id"])
    db.create_message(conversation_id, "user", "Test audio temporaire.")
    db.create_message(conversation_id, "assistant", "Premiere reponse de test.")
    db.create_message(conversation_id, "assistant", "Deuxieme reponse de test.")
    return conversation_id


async def open_voice_ready_conversation(page, conversation_id: str) -> bool:
    await page.goto(
        f"{BASE_URL}/?conversation={conversation_id}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.wait_for_timeout(1_000)
    return True


async def main() -> int:
    # Chaque run possede sa ressource. Ne jamais balayer les fixtures des autres
    # processus : les smokes peuvent etre lances en parallele par la CI.
    fixture_id = create_voice_fixture(uuid.uuid4().hex)
    atexit.register(db.delete_conversation, fixture_id)
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
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(1_000)

        listen = page.locator('button[title="\u00c9couter la r\u00e9ponse"]')
        await open_voice_ready_conversation(page, fixture_id)
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
        await navigate_with_marvin_menu(page, "Mon jour", "/jour")
        await page.wait_for_timeout(80)
        during_navigation = await page.evaluate("window.__marvinAudio")
        await navigate_with_marvin_menu(page, "Chat", "/")
        await page.wait_for_timeout(250)
        listen = page.locator('button[title="\u00c9couter la r\u00e9ponse"]')
        if await listen.count() < 1:
            await open_voice_ready_conversation(page, fixture_id)
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
    with browser_smoke_lock():
        sys.exit(asyncio.run(main()))
