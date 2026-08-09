"""Smoke test réel et réversible des quatre profils de confidentialité Marvin.

Le script change temporairement les cinq réglages atomiques du profil, exécute
des calculs via le chat et restaure toujours l'état exact observé au départ.
Il ne contient et ne transmet aucun secret réel.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database as db  # noqa: E402


SETTING_KEYS = (
    "cloud_overrides",
    "cloud_enabled",
    "ultra_unrestricted",
    "local_only_lockdown",
    "privacy_preset",
)
FIXTURE_TITLE_PREFIX = "[SMOKE:privacy]"


@dataclass(frozen=True)
class Scenario:
    name: str
    preset: str
    prompt: str
    expected_provider: str


SCENARIOS = (
    Scenario(
        "normal_public",
        "normal",
        "Utilise exactement l'outil calculator avec l'expression 37*229, puis donne le résultat.",
        "any",
    ),
    Scenario(
        "normal_sensitive",
        "normal",
        "Le mot de passe fictif de test est DEMO-NON-SECRET. Utilise exactement l'outil calculator avec l'expression 37*229.",
        "ollama_local",
    ),
    Scenario(
        "hyper_public",
        "hyper",
        "Utilise exactement l'outil calculator avec l'expression 37*229, puis donne le résultat.",
        "ollama_local",
    ),
    Scenario(
        "cloud_max_public",
        "cloud_max",
        "Utilise exactement l'outil calculator avec l'expression 37*229, puis donne le résultat.",
        "ollama_cloud",
    ),
    Scenario(
        "cloud_max_sensitive",
        "cloud_max",
        "Le mot de passe fictif de test est DEMO-NON-SECRET. Utilise exactement l'outil calculator avec l'expression 37*229.",
        "ollama_local",
    ),
    Scenario(
        "ultra_sensitive",
        "ultra",
        "Le mot de passe fictif de test est DEMO-NON-SECRET. Utilise exactement l'outil calculator avec l'expression 37*229.",
        "ollama_cloud",
    ),
)


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 240,
) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} pour {path}")
        return response.read()


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    decoded = json.loads(_request(base_url, path, method=method, payload=payload, timeout=timeout))
    if not isinstance(decoded, dict):
        raise RuntimeError(f"Réponse JSON inattendue pour {path}")
    return decoded


def _setting(base_url: str, key: str) -> Any:
    return _json_request(base_url, f"/api/settings/{key}").get("value")


def _restore(base_url: str, state: dict[str, Any]) -> None:
    for key in SETTING_KEYS:
        _json_request(
            base_url,
            f"/api/settings/{key}",
            method="PUT",
            payload={"value": state.get(key)},
        )


def _events(raw: bytes) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            result.append(event)
    return result


def _execute_scenario(
    base_url: str,
    scenario: Scenario,
    conversation_id: str,
) -> dict[str, Any]:
    state = _json_request(
        base_url,
        "/api/settings/privacy-preset",
        method="PUT",
        payload={"preset": scenario.preset},
    )
    if state.get("privacy_preset") != scenario.preset:
        raise AssertionError(f"{scenario.name}: preset effectif inattendu")
    started = time.monotonic()
    raw = _request(
        base_url,
        "/api/chat",
        method="POST",
        payload={
            "conversationId": conversation_id,
            "requestId": f"smoke-privacy-{scenario.name}-{uuid4().hex}",
            "messages": [{"role": "user", "content": scenario.prompt}],
        },
        timeout=240,
    )
    elapsed = round(time.monotonic() - started, 2)
    events = _events(raw)
    errors = [event for event in events if event.get("type") == "error"]
    if errors:
        raise AssertionError(f"{scenario.name}: erreur SSE {errors[-1].get('message')}")
    models = [event for event in events if event.get("type") == "model_info"]
    if not models:
        raise AssertionError(f"{scenario.name}: provenance modèle absente")
    provider = str(models[-1].get("provider") or "")
    if scenario.expected_provider != "any" and provider != scenario.expected_provider:
        raise AssertionError(
            f"{scenario.name}: fournisseur {provider}, attendu {scenario.expected_provider}"
        )
    tool_ends = [
        event for event in events
        if event.get("type") == "tool_end" and event.get("toolName") == "calculator"
    ]
    if len(tool_ends) != 1:
        raise AssertionError(f"{scenario.name}: calculator exécuté {len(tool_ends)} fois")
    result = tool_ends[0].get("result") or {}
    if str(result.get("result")) not in {"8473", "8473.0"}:
        raise AssertionError(f"{scenario.name}: résultat outil inattendu {result.get('result')}")
    if not any(event.get("type") == "done" for event in events):
        raise AssertionError(f"{scenario.name}: événement done absent")
    return {
        "scenario": scenario.name,
        "preset": scenario.preset,
        "provider": provider,
        "model": str(models[-1].get("model") or ""),
        "duration_seconds": elapsed,
        "calculator_calls": len(tool_ends),
        "success": True,
    }


def _run_scenario(base_url: str, scenario: Scenario) -> dict[str, Any]:
    """Execute un scenario dans une conversation jetable, meme en cas d'echec."""
    conversation = db.create_conversation(
        f"{FIXTURE_TITLE_PREFIX} {scenario.name} {uuid4().hex}"
    )
    conversation_id = str(conversation["id"])
    try:
        return _execute_scenario(base_url, scenario, conversation_id)
    finally:
        db.delete_conversation(conversation_id)


def _cleanup_orphan_fixtures() -> int:
    """Supprime uniquement les fixtures identifiees d'un run interrompu brutalement."""
    candidates = db.search_conversations(FIXTURE_TITLE_PREFIX, limit=100)
    orphan_ids = [
        str(item["id"])
        for item in candidates
        if str(item.get("title") or "").startswith(FIXTURE_TITLE_PREFIX)
    ]
    for conversation_id in orphan_ids:
        db.delete_conversation(conversation_id)
    return len(orphan_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8005")
    args = parser.parse_args()
    base_url = str(args.base_url).rstrip("/")
    cleaned_orphans = _cleanup_orphan_fixtures()
    initial = {key: _setting(base_url, key) for key in SETTING_KEYS}
    reports: list[dict[str, Any]] = []
    failure: Exception | None = None
    try:
        for scenario in SCENARIOS:
            report = _run_scenario(base_url, scenario)
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False), flush=True)
    except (AssertionError, OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        failure = exc
    finally:
        _restore(base_url, initial)
        restored = {key: _setting(base_url, key) for key in SETTING_KEYS}
        if restored != initial:
            raise RuntimeError("La restauration exacte des paramètres de profil a échoué.")
    if failure is not None:
        raise failure
    print(json.dumps({
        "success": True,
        "scenarios": len(reports),
        "settings_restored": True,
        "orphan_fixtures_cleaned": cleaned_orphans,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
