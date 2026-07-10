r"""
Smoke-test de balayage de pages Marvin (v2.111).

Charge chaque page de l'application et vérifie l'absence d'erreur console navigateur.
Formalise un contrôle fait à la main plusieurs fois pendant la session v2.107-111
(consolidation JS/Python, migration du gestionnaire de fichiers) — à relancer après tout
changement transverse (nouvelle route API, changement de layout, migration de page).

Usage (depuis la racine du projet, frontend déjà lancé sur :3000, PowerShell 5.1) :
    $env:PYTHONIOENCODING='utf-8'; backend\.venv\Scripts\python.exe scripts/smoke_test_pages.py

Complémentaire à scripts/smoke_test_chat.py (qui vérifie spécifiquement l'absence de JSON
brut dans le rendu du chat) — celui-ci couvre la surface applicative entière mais seulement
au chargement (pas d'interaction). Ne PAS lancer un second `next dev` (verrouille le dossier
.next, cf. CLAUDE.md §3) — pilote Chrome vers l'instance déjà démarrée par l'utilisateur.
Nécessite Playwright (déjà dans backend/.venv, channel="chrome").
"""
import asyncio
import sys

from playwright.async_api import async_playwright

BASE_URL = "http://localhost:3000"

# Toutes les pages de premier niveau (app/*/page.jsx) — inclut les anciennes routes qui
# redirigent vers un hub (catharsis/codex/emporium/pantheon/sante/files/indexation/
# documents/vocal) : leur redirect doit rester silencieux, zéro erreur console.
PAGES = [
    "/", "/agents", "/calendar", "/catharsis", "/codex", "/cron", "/devis", "/docs",
    "/documents", "/emails", "/emporium", "/fichiers", "/files", "/indexation", "/jour",
    "/mcp", "/memoire", "/mobile", "/monitoring", "/notes", "/outils", "/pantheon",
    "/recherche", "/redaction", "/sante", "/settings", "/skills", "/ssh", "/systeme",
    "/tasks", "/technique", "/video", "/vocal", "/workflows",
]


async def check(browser, path: str) -> dict:
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    try:
        # 'load' plutôt que 'networkidle' : certaines pages (monitoring) font du polling
        # live et n'atteignent jamais l'inactivité réseau — faux négatif sinon.
        await page.goto(BASE_URL + path, wait_until="load", timeout=15000)
        await page.wait_for_timeout(1200)
        ok = True
    except Exception as e:
        errors.append(f"nav error: {e}")
        ok = False
    await page.close()
    return {"path": path, "ok": ok and not errors, "errors": errors[:5]}


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        results = [await check(browser, path) for path in PAGES]
        await browser.close()

    print(f"\n{'='*60}\nSMOKE TEST PAGES MARVIN\n{'='*60}")
    failed = [r for r in results if not r["ok"]]
    for r in results:
        status = "OK" if r["ok"] else "ECHEC"
        print(f"  [{status}] {r['path']}")
        for e in r["errors"]:
            print(f"          -> {e[:200]}")

    print(f"\nRésultat : {len(results) - len(failed)}/{len(results)} pages OK")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
