"""Hardware-aware local Ollama model selection backed by a versioned manifest."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).with_name("resources") / "local_model_catalog.json"
RUNTIME_ROLES = ("chat", "agent", "analysis", "vision")
PORTFOLIO_ROLES = (*RUNTIME_ROLES, "coding")
GIB = 1024 ** 3
MODEL_NAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}(?::[A-Za-z0-9][A-Za-z0-9._-]{0,63})?$"
)


class LocalModelPolicyError(RuntimeError):
    """The local model manifest is missing or malformed."""


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalModelPolicyError(
            f"Catalogue local illisible ({type(exc).__name__})."
        ) from exc
    return validate_catalog(payload)


def validate_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    """Valide aussi les noms avant toute utilisation en CLI Ollama."""
    entries = payload.get("entries")
    if payload.get("schema") != "marvin.local-model-catalog/1.0" or not isinstance(entries, list):
        raise LocalModelPolicyError("Schéma du catalogue local invalide.")
    seen: set[str] = set()
    for entry in entries:
        name = str(entry.get("name") or "")
        roles = entry.get("roles")
        if (
            not MODEL_NAME_RE.fullmatch(name) or name in seen or not isinstance(roles, dict)
            or int(entry.get("size_bytes") or 0) <= 0
            or not str(entry.get("source_url") or "").startswith("https://ollama.com/")
        ):
            raise LocalModelPolicyError("Entrée du catalogue local invalide.")
        if any(role not in PORTFOLIO_ROLES for role in roles):
            raise LocalModelPolicyError("Rôle inconnu dans le catalogue local.")
        seen.add(name)
    return payload


def canonical_name(name: str) -> str:
    value = str(name or "").strip()
    return value[:-7] if value.endswith(":latest") else value


def memory_budget_bytes(hardware: dict[str, Any]) -> int:
    """Reserve memory for KV cache, runtime, display and concurrent host activity."""
    vram = float(hardware.get("vram_gb") or 0)
    if vram > 0:
        reserve_gib = max(1.0, vram * 0.20)
        return max(512 * 1024 ** 2, int((vram - reserve_gib) * GIB))
    available = float(hardware.get("ram_available_gb") or hardware.get("ram_gb") or 0)
    total = float(hardware.get("ram_gb") or available)
    return max(512 * 1024 ** 2, int(min(available * 0.45, total * 0.35) * GIB))


def _installed_map(models: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in models:
        name = canonical_name(str(item.get("name") or ""))
        if not name or name.endswith(":cloud") or name.endswith("-cloud"):
            continue
        result[name] = {**item, "name": name, "size_bytes": int(item.get("size_bytes") or 0)}
    return result


def _supports_dynamic_role(item: dict[str, Any], role: str) -> bool:
    name = str(item.get("name") or "").casefold()
    capabilities = {
        str(capability).casefold()
        for capability in item.get("capabilities") or []
    }
    if "embedding" in capabilities or "embed" in name:
        return False
    if role == "vision":
        return "vision" in capabilities or any(
            marker in name
            for marker in ("vision", "llava", "minicpm", "bakllava", "glm-ocr")
        )
    if "vision" in capabilities or any(
        marker in name
        for marker in ("vision", "llava", "minicpm", "bakllava", "glm-ocr")
    ):
        return False
    if role == "coding":
        return any(
            marker in name
            for marker in ("coder", "code", "codestral", "devstral", "starcoder")
        )
    if role == "agent" and capabilities:
        return "tools" in capabilities
    return not capabilities or "completion" in capabilities


def _dynamic_candidate(
    installed: dict[str, dict[str, Any]],
    role: str,
    budget: int,
) -> dict[str, Any] | None:
    candidates = [
        item
        for item in installed.values()
        if 0 < int(item.get("size_bytes") or 0) <= budget
        and _supports_dynamic_role(item, role)
    ]
    candidates.sort(
        key=lambda item: (
            "tools" in set(item.get("capabilities") or []),
            "thinking" in set(item.get("capabilities") or []),
            int(item.get("context_tokens") or 0),
            int(item.get("size_bytes") or 0),
            item["name"],
        ),
        reverse=True,
    )
    if not candidates:
        return None
    selected = candidates[0]
    return {
        "name": selected["name"],
        "size_bytes": selected["size_bytes"],
        "context_tokens": int(selected.get("context_tokens") or 0),
        "roles": {role: 0},
        "capabilities": list(selected.get("capabilities") or ["unknown_legacy"]),
        "source_url": None,
        "selection_source": "ollama_runtime_metadata",
    }


def recommend(
    hardware: dict[str, Any],
    installed_models: list[dict[str, Any]],
    *,
    catalog_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = catalog_payload or load_catalog()
    entries = list(catalog["entries"])
    installed = _installed_map(installed_models)
    budget = memory_budget_bytes(hardware)
    disk_free = int(hardware.get("disk_free_bytes") or 0)
    disk_reserve = max(10 * GIB, int(disk_free * 0.20))

    portfolio: dict[str, dict[str, Any] | None] = {}
    chosen: dict[str, str] = {}
    downloads: list[dict[str, Any]] = []
    for role in PORTFOLIO_ROLES:
        candidates = [
            entry for entry in entries
            if role in entry["roles"] and int(entry["size_bytes"]) <= budget
        ]
        candidates.sort(
            key=lambda item: (
                int(item["roles"][role]),
                int(item.get("context_tokens") or 0),
                -int(item["size_bytes"]),
            ),
            reverse=True,
        )
        desired = candidates[0] if candidates else None
        installed_candidates = [
            entry for entry in candidates if canonical_name(entry["name"]) in installed
        ]
        selected = installed_candidates[0] if installed_candidates else None
        if selected is None:
            selected = _dynamic_candidate(installed, role, budget)
        portfolio[role] = {
            "recommended": desired["name"] if desired else None,
            "selected": selected["name"] if selected else None,
            "score": int((desired or {}).get("roles", {}).get(role, 0)),
            "source_url": (desired or {}).get("source_url"),
            "size_bytes": int((desired or {}).get("size_bytes") or 0),
            "context_tokens": int((desired or {}).get("context_tokens") or 0),
            "capabilities": list((desired or {}).get("capabilities") or []),
            "selected_capabilities": list((selected or {}).get("capabilities") or []),
            "selected_source": (
                "curated_catalog"
                if selected and not selected.get("selection_source")
                else (selected or {}).get("selection_source")
            ),
        }
        if selected and role in RUNTIME_ROLES:
            chosen[role] = selected["name"]
        if desired and canonical_name(desired["name"]) not in installed:
            downloads.append({
                "model": desired["name"],
                "size_bytes": int(desired["size_bytes"]),
                "roles": [role],
                "source_url": desired["source_url"],
            })

    merged: dict[str, dict[str, Any]] = {}
    for item in downloads:
        existing = merged.setdefault(item["model"], {**item, "roles": []})
        existing["roles"] = sorted(set(existing["roles"] + item["roles"]))
    ordered = sorted(merged.values(), key=lambda item: (item["size_bytes"], item["model"]))
    cumulative = 0
    for item in ordered:
        cumulative += item["size_bytes"]
        item["disk_ready"] = not disk_free or disk_free - cumulative >= disk_reserve

    return {
        "catalog_schema": catalog["schema"],
        "catalog_updated_at": catalog.get("updated_at"),
        "memory_budget_bytes": budget,
        "memory_budget_gb": round(budget / GIB, 2),
        "chosen": chosen,
        "portfolio": portfolio,
        "downloads": ordered,
        "installed": sorted(installed),
        "disk_free_bytes": disk_free,
        "disk_reserve_bytes": disk_reserve,
    }


def override_allowed(
    model: str,
    role: str,
    hardware: dict[str, Any],
    installed_models: list[dict[str, Any]],
) -> tuple[bool, str]:
    name = canonical_name(model)
    installed = _installed_map(installed_models)
    item = installed.get(name)
    if not item:
        return False, "modèle local absent"
    if int(item.get("size_bytes") or 0) > memory_budget_bytes(hardware):
        return False, "modèle trop volumineux pour le budget mémoire sûr"
    catalog_entry = next(
        (entry for entry in load_catalog()["entries"] if canonical_name(entry["name"]) == name),
        None,
    )
    if catalog_entry and role not in catalog_entry["roles"]:
        return False, f"capacité {role} non déclarée"
    return True, "override compatible"
