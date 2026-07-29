"""Smoke navigateur réel de l'accès local et du jumelage LAN."""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.error
import urllib.request

from playwright.async_api import async_playwright


def _json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())


def _status_without_cookie(url: str) -> int:
    try:
        urllib.request.urlopen(url, timeout=10)
    except urllib.error.HTTPError as exc:
        return exc.code
    return 200


async def run(lan_host: str) -> None:
    local_status = _json("http://127.0.0.1:8005/api/auth/lan/status")
    pairing_code = str(local_status.get("pairing_code") or "")
    assert len(pairing_code) >= 12
    assert _status_without_cookie(f"http://{lan_host}:8005/api/tasks") == 401
    assert _status_without_cookie(f"http://{lan_host}:3000/api/tasks") == 401

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome")
        local = await browser.new_context(viewport={"width": 1280, "height": 900})
        local_page = await local.new_page()
        await local_page.goto(
            "http://127.0.0.1:3000/settings?tab=connections",
            wait_until="networkidle",
            timeout=45_000,
        )
        await local_page.get_by_text("Accès réseau protégé").wait_for(timeout=20_000)
        local_mutation = await local_page.evaluate(
            """async () => {
              const response = await fetch('http://127.0.0.1:8005/api/contract-only-test', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: '{}',
              });
              return response.status;
            }"""
        )
        assert local_mutation == 404
        await local.close()

        remote = await browser.new_context(viewport={"width": 390, "height": 844})
        remote_page = await remote.new_page()
        diagnostics: list[str] = []
        remote_page.on(
            "pageerror",
            lambda error: diagnostics.append(f"pageerror:{error}"),
        )
        remote_page.on(
            "console",
            lambda message: diagnostics.append(
                f"console:{message.type}:{message.text}"
            ),
        )
        remote_page.on(
            "requestfailed",
            lambda request: diagnostics.append(
                f"failed:{request.url}:{request.failure}"
            ),
        )
        remote_page.on(
            "response",
            lambda response: (
                diagnostics.append(f"response:{response.status}:{response.url}")
                if "/api/auth/lan/status" in response.url
                else None
            ),
        )
        await remote_page.goto(
            f"http://{lan_host}:3000/",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        field = remote_page.get_by_label("Code de jumelage")
        try:
            await field.wait_for(timeout=20_000)
        except Exception as exc:
            visible = (await remote_page.locator("body").inner_text())[:500]
            runtime = await remote_page.evaluate(
                """() => ({
                  readyState: document.readyState,
                  fetchBridge: Boolean(window.__marvinBackendFetchInstalled),
                  scripts: document.scripts.length,
                })"""
            )
            raise AssertionError(
                f"Écran de jumelage absent; contenu visible={visible!r}; "
                f"runtime={runtime!r}; diagnostic={diagnostics[:30]!r}"
            ) from exc
        await field.fill(pairing_code)
        await remote_page.get_by_role("button", name="Autoriser cet appareil").click()
        await field.wait_for(state="detached", timeout=20_000)
        await remote_page.get_by_text("Nouvelle conversation").first.wait_for(timeout=20_000)
        remote_status = await remote_page.evaluate(
            f"""async () => {{
              const response = await fetch('http://{lan_host}:8005/api/auth/lan/status', {{
                cache: 'no-store',
              }});
              return {{status: response.status, body: await response.json()}};
            }}"""
        )
        assert remote_status["status"] == 200
        assert remote_status["body"]["authenticated"] is True
        assert "pairing_code" not in remote_status["body"]
        next_proxy_status = await remote_page.evaluate(
            """async () => (await fetch('/api/tasks', {cache: 'no-store'})).status"""
        )
        assert next_proxy_status == 200
        await remote.close()

        restricted = await browser.new_context(viewport={"width": 390, "height": 844})
        restricted_page = await restricted.new_page()
        await restricted_page.goto(
            f"http://{lan_host}:3000/",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await restricted_page.get_by_label("Code de jumelage").fill(pairing_code)
        await restricted_page.get_by_label(
            "Niveau d’accès de cet appareil"
        ).select_option("read_only")
        await restricted_page.get_by_role(
            "button",
            name="Autoriser cet appareil",
        ).click()
        await restricted_page.get_by_label(
            "Code de jumelage"
        ).wait_for(state="detached", timeout=20_000)
        restricted_statuses = await restricted_page.evaluate(
            """async () => ({
              tasks: (await fetch('/api/tasks', {cache: 'no-store'})).status,
              settings: (await fetch('/api/settings', {cache: 'no-store'})).status,
            })"""
        )
        assert restricted_statuses == {"tasks": 200, "settings": 403}, (
            f"Profil lecture seule incorrect via Next: {restricted_statuses!r}"
        )
        await restricted.close()
        await browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lan-host", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.lan_host))
    print(
        "LAN Browser Smoke OK - local, anonyme, complet et lecture seule "
        "validés sur FastAPI/Next."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
