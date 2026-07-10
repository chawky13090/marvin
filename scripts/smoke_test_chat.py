r"""
Smoke-test visuel du chat Marvin (v2.107).

Recharge quelques conversations réelles depuis la sidebar et vérifie :
  1. Aucune erreur console navigateur.
  2. Aucun JSON brut visible par défaut dans une carte de résultat d'outil
     (régression du bug winget_search corrigé en v2.107 — le fallback générique
     de MessageBubble.jsx doit passer par PrettyResult, pas par JSON.stringify).
  3. La page répond (le titre "Marvin" est visible).

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


async def check_conversation(page, title_snippet: str) -> dict:
    issues = []
    item = page.locator(f"text={title_snippet}").first
    try:
        await item.click(timeout=5000)
    except Exception as e:
        return {"title": title_snippet, "ok": False, "issues": [f"clic impossible : {e}"]}

    await page.wait_for_timeout(2000)

    body_text = await page.locator("body").inner_text()
    if RAW_JSON_RE.search(body_text):
        issues.append("JSON brut détecté dans le texte visible de la page")

    return {"title": title_snippet, "ok": not issues, "issues": issues}


async def main() -> int:
    console_errors: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        page = await browser.new_page(viewport={"width": 1280, "height": 1400})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))

        await page.goto(BASE_URL + "/", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1500)

        title_ok = "Marvin" in (await page.locator("body").inner_text())
        if not title_ok:
            print("ÉCHEC : la page d'accueil ne s'est pas chargée correctement.")
            await browser.close()
            return 1

        # Récupère les titres de conversation visibles dans la sidebar. Les lignes de
        # conversation n'ont pas de className (styles inline, cf. app/page.js) — repérées
        # par leur signature de style (div cliquable avec bordure gauche + son <span> titre).
        items = await page.locator(
            'div[style*="cursor: pointer"][style*="border-left"] span'
        ).all_inner_texts()
        titles = [t.strip() for t in items if t.strip()][:SAMPLE_SIZE]

        results = []
        for t in titles:
            results.append(await check_conversation(page, t))

        await browser.close()

    print(f"\n{'='*60}\nSMOKE TEST CHAT MARVIN\n{'='*60}")
    print(f"Conversations testées : {len(results)}")
    failed = [r for r in results if not r["ok"]]
    for r in results:
        status = "OK" if r["ok"] else "ECHEC"
        print(f"  [{status}] {r['title']}")
        for issue in r["issues"]:
            print(f"          -> {issue}")

    if console_errors:
        print(f"\nErreurs console navigateur ({len(console_errors)}) :")
        for e in console_errors[:10]:
            print(f"  - {e[:200]}")

    ok = not failed and not console_errors
    print(f"\nRésultat global : {'OK' if ok else 'ECHEC'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
