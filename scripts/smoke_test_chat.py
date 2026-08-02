r"""
Smoke-test visuel du chat Marvin (v2.107).

Recharge quelques conversations réelles depuis la sidebar et vérifie :
  1. Aucune erreur console navigateur.
  2. Aucun JSON brut visible par défaut dans une carte de résultat d'outil
     (régression du bug winget_search corrigé en v2.107 — le fallback générique
     de MessageBubble.jsx doit passer par PrettyResult, pas par JSON.stringify).
  3. La page répond (le composeur du chat est visible).

Usage (depuis la racine du projet, frontend déjà lancé sur :3000, PowerShell 5.1) :
    $env:PYTHONIOENCODING='utf-8'; backend\.venv\Scripts\python.exe scripts/smoke_test_chat.py

Ne PAS lancer un second `next dev` (verrouille le dossier .next, cf. CLAUDE.md §3) —
ce script se contente de piloter Chrome vers l'instance déjà démarrée par l'utilisateur.
Nécessite Playwright (déjà dans backend/.venv, channel="chrome").
"""
import asyncio
import re
import sys

from playwright.async_api import async_playwright

BASE_URL = "http://localhost:3000"
# Nombre de conversations de la sidebar à ouvrir (les plus récentes).
SAMPLE_SIZE = 5
# Un dump JSON brut (le bug qu'on veut attraper : PrettyResult/JSON.stringify visible par
# défaut) a PLUSIEURS paires clé:valeur séparées par des virgules — contrairement à une
# mention ponctuelle d'un seul paramètre dans une phrase (ex. un appel d'outil écrit en
# texte par le LLM, {"query":"..."} — problème distinct, déjà atténué par la température/
# top_p v2.106, pas ce que ce test cible).
RAW_JSON_RE = re.compile(
    r'\{\s*"[a-zA-Z_]+"\s*:\s*"?[\w.]+"?\s*,\s*"[a-zA-Z_]+"\s*:', re.DOTALL
)


async def check_conversation(page, title_snippet: str, conversation_id: str) -> dict:
    issues = []
    item = page.get_by_role(
        "button",
        name=f"Ouvrir la conversation {title_snippet}",
        exact=True,
    ).first
    try:
        await item.wait_for(state="visible", timeout=5000)
        await item.evaluate("(element) => element.click()")
    except Exception as e:
        return {
            "title": title_snippet,
            "conversation_id": conversation_id,
            "ok": False,
            "issues": [f"clic impossible : {e}"],
        }

    try:
        await page.wait_for_function(
            """conversationId => {
                const container = document.querySelector('[data-active-conversation-id]');
                return container
                    && container.dataset.activeConversationId === conversationId
                    && Number(container.dataset.messageCount || 0) > 0;
            }""",
            arg=conversation_id,
            timeout=25000,
        )
    except Exception:
        issues.append("conversation non matérialisée après 25 secondes")

    body_text = await page.locator("body").inner_text()
    active = page.locator(
        f'[data-active-conversation-id="{conversation_id}"]'
    )
    if await active.count() == 0 or int(await active.get_attribute("data-message-count") or 0) == 0:
        issues.append("conversation ouverte mais contenu absent (état vide affiché)")
        container = page.locator("[data-active-conversation-id]").first
        if await container.count():
            issues.append(
                "état observé : active=%s live=%s status=%s messages=%s"
                % (
                    await container.get_attribute("data-active-conversation-id"),
                    await container.get_attribute("data-live-conversation-id"),
                    await container.get_attribute("data-chat-status"),
                    await container.get_attribute("data-message-count"),
                )
            )
    if RAW_JSON_RE.search(body_text):
        issues.append("JSON brut détecté dans le texte visible de la page")

    return {
        "title": title_snippet,
        "conversation_id": conversation_id,
        "ok": not issues,
        "issues": issues,
    }


async def main() -> int:
    console_errors: list[str] = []
    http_errors: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        page = await browser.new_page(viewport={"width": 1280, "height": 1400})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))
        page.on(
            "response",
            lambda response: http_errors.append(
                f"HTTP {response.status} {response.url}"
            ) if response.status >= 400 else None,
        )

        # La page possède des pollers à 10/15 s : `networkidle` n'est donc pas
        # un contrat de disponibilité et devient aléatoire sous charge. Attendre
        # les éléments métier réellement nécessaires au parcours.
        await page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=30000)
        await page.locator("textarea").first.wait_for(state="visible", timeout=15000)
        await page.locator("[data-conversation-id]").first.wait_for(timeout=15000)

        if await page.locator("textarea:visible").count() == 0:
            print("ÉCHEC : la page d'accueil ne s'est pas chargée correctement.")
            await browser.close()
            return 1

        # Récupère les titres de conversation visibles dans la sidebar. Les lignes de
        # conversation n'ont pas de className (styles inline, cf. app/page.js) — repérées
        # par leur signature de style (div cliquable avec bordure gauche + son <span> titre).
        # Lire l'échantillon dans une seule évaluation DOM : la liste peut être
        # rafraîchie par les pollers pendant une succession de locators.
        raw_samples = await page.locator(
            "[data-conversation-id]:visible"
        ).evaluate_all(
            """(rows, limit) => rows.slice(0, limit).map(row => ({
                id: row.dataset.conversationId || '',
                title: row.querySelector('.conversation-row-main span')?.textContent?.trim() || '',
            }))""",
            SAMPLE_SIZE,
        )
        samples = []
        sampled_ids = set()
        for sample in raw_samples:
            conversation_id = sample.get("id")
            title = sample.get("title")
            if conversation_id and title and conversation_id not in sampled_ids:
                sampled_ids.add(conversation_id)
                samples.append((title, conversation_id))

        results = []
        for title, conversation_id in samples:
            await page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=30000)
            await page.locator("textarea").first.wait_for(state="visible", timeout=15000)
            await page.get_by_role(
                "button",
                name=f"Ouvrir la conversation {title}",
                exact=True,
            ).first.wait_for(state="visible", timeout=15000)
            results.append(await check_conversation(page, title, conversation_id))

        await browser.close()

    print(f"\n{'='*60}\nSMOKE TEST CHAT MARVIN\n{'='*60}")
    print(f"Conversations testées : {len(results)}")
    failed = [r for r in results if not r["ok"]]
    for r in results:
        status = "OK" if r["ok"] else "ECHEC"
        print(f"  [{status}] {r['title']} ({r['conversation_id']})")
        for issue in r["issues"]:
            print(f"          -> {issue}")

    if console_errors:
        print(f"\nErreurs console navigateur ({len(console_errors)}) :")
        for e in console_errors[:10]:
            print(f"  - {e[:200]}")
    if http_errors:
        print(f"\nRéponses HTTP en erreur ({len(http_errors)}) :")
        for error in http_errors[:20]:
            print(f"  - {error[:300]}")

    ok = not failed and not console_errors
    print(f"\nRésultat global : {'OK' if ok else 'ECHEC'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
