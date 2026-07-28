"""Auto-diagnostic borné d'un catalogue explicite d'outils en lecture seule."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Awaitable


ToolFunction = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class Probe:
    category: str
    tool: str
    arguments: Mapping[str, Any]
    requires_web: bool = False


SAFE_PROBES: tuple[Probe, ...] = (
    Probe("calcul", "calculator", {"expression": "2+2"}),
    Probe("date", "datetime_info", {}),
    Probe("conversion", "unit_convert", {"value": 1, "from_unit": "km", "to_unit": "m"}),
    Probe("crypto", "hash_compute", {"text": "x", "algorithm": "md5"}),
    Probe("texte", "json_tool", {"data": "{}", "operation": "format"}),
    Probe("système", "pc_system_info", {}),
    Probe("disque", "win_disk_info", {}),
    Probe("système", "win_uptime", {}),
    Probe("devis", "billing_catalog_list", {}),
    Probe("base IT", "it_kb_list", {}),
    Probe("base IT", "it_kb_recommend", {"need": "antivirus pme"}),
    Probe("mémoire", "memory_list", {}),
    Probe("notes", "note_list", {}),
    Probe("tâches", "task_list", {}),
    Probe("chemins", "pc_get_real_paths", {}),
    Probe("documentation", "doc_intervention_list", {}),
    Probe("réseau", "ip_info", {}, requires_web=True),
    Probe("réseau", "net_ping", {"host": "127.0.0.1", "count": 1}),
    Probe("système", "pc_process_list", {}),
    Probe("système", "pc_window_list", {}),
    Probe("système", "pc_installed_software", {}),
    Probe("système", "win_services_list", {}),
    Probe("système", "win_startup_programs", {}),
    Probe("système", "win_users_list", {}),
    Probe("système", "pc_gpu_status", {}),
    Probe("système", "pc_hardware_specs", {}),
    Probe("système", "win_update_status", {}),
    Probe("outils", "password_generate", {}),
    Probe("outils", "base64_tool", {"data": "test", "action": "encode"}),
    Probe("outils", "color_tool", {"color": "#ffffff"}),
    Probe("outils", "regex_tool", {"pattern": "a+", "text": "aaa", "action": "findall"}),
    Probe("outils", "text_stats", {"text": "Bonjour le monde."}),
    Probe("outils", "diff_text", {"text_a": "a", "text_b": "b"}),
    Probe("outils", "pc_clipboard_get", {}),
    Probe("agenda", "calendar_list", {}),
    Probe("email", "email_accounts", {}),
    Probe("mémoire", "memory_search", {"query": "test"}),
    Probe("recherche", "search_semantic", {"query": "test"}),
    Probe("devis", "billing_client_list", {}),
    Probe("devis", "billing_quote_list", {}),
    Probe("devis", "billing_invoice_list", {}),
    Probe("documentation", "doc_template_list", {}),
    Probe("ssh", "ssh_list", {}),
    Probe("web", "web_search", {"query": "test", "max_results": 2}, requires_web=True),
    Probe("météo", "weather", {"city": "Paris"}, requires_web=True),
)


_registry_provider: Callable[[], Mapping[str, ToolFunction]] | None = None
_probes: tuple[Probe, ...] = SAFE_PROBES
_PER_TOOL_TIMEOUT_SECONDS = 30.0
_MAX_CONCURRENCY = 4


def configure(
    *,
    registry_provider: Callable[[], Mapping[str, ToolFunction]],
    probes: Sequence[Probe] | None = None,
) -> None:
    global _registry_provider, _probes
    _registry_provider = registry_provider
    _probes = tuple(probes) if probes is not None else SAFE_PROBES


def _registry() -> Mapping[str, ToolFunction]:
    if _registry_provider is None:
        raise RuntimeError("Le domaine d'auto-diagnostic n'est pas configuré.")
    return _registry_provider()


def _selected_probes(category: str, include_web: bool) -> list[Probe]:
    return [
        probe
        for probe in _probes
        if (include_web or not probe.requires_web)
        and (
            not category
            or category in probe.category.casefold()
            or category in probe.tool.casefold()
        )
    ]


async def _run_probe(
    probe: Probe,
    *,
    registry: Mapping[str, ToolFunction],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    function = registry.get(probe.tool)
    if function is None:
        return {
            "tool": probe.tool,
            "category": probe.category,
            "status": "absent",
            "detail": "Outil absent du registre.",
            "ms": 0,
        }

    started = time.perf_counter()
    try:
        async with semaphore:
            result = await asyncio.wait_for(
                function(dict(probe.arguments)),
                timeout=_PER_TOOL_TIMEOUT_SECONDS,
            )
        elapsed_ms = int((time.perf_counter() - started) * 1_000)
        if isinstance(result, dict) and result.get("error"):
            return {
                "tool": probe.tool,
                "category": probe.category,
                "status": "erreur",
                "detail": str(result["error"])[:160],
                "ms": elapsed_ms,
            }
        return {
            "tool": probe.tool,
            "category": probe.category,
            "status": "ok",
            "detail": "",
            "ms": elapsed_ms,
        }
    except TimeoutError:
        return {
            "tool": probe.tool,
            "category": probe.category,
            "status": "timeout",
            "detail": f"Délai individuel dépassé ({_PER_TOOL_TIMEOUT_SECONDS:g} s).",
            "ms": int((time.perf_counter() - started) * 1_000),
        }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return {
            "tool": probe.tool,
            "category": probe.category,
            "status": "crash",
            "detail": str(exc)[:160],
            "ms": int((time.perf_counter() - started) * 1_000),
        }


async def run(args: dict[str, Any]) -> dict[str, Any]:
    """Teste un échantillon sûr avec timeout et concurrence bornée."""
    raw_category = args.get("category", "")
    if not isinstance(raw_category, str):
        return {"error": "'category' doit être une chaîne."}
    category = raw_category.strip().casefold()
    if len(category) > 80:
        return {"error": "'category' est limitée à 80 caractères."}
    include_web = args.get("include_web", False)
    if not isinstance(include_web, bool):
        return {"error": "'include_web' doit être un booléen."}

    registry = _registry()
    probes = _selected_probes(category, include_web)
    if not probes:
        categories = sorted({probe.category for probe in _probes})
        return {
            "error": "Aucun outil sûr ne correspond à cette catégorie.",
            "available_categories": categories,
        }

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    results = await asyncio.gather(
        *(
            _run_probe(probe, registry=registry, semaphore=semaphore)
            for probe in probes
        )
    )
    ok_count = sum(1 for result in results if result["status"] == "ok")
    failures = [result for result in results if result["status"] != "ok"]
    tested = len(results)
    return {
        "success": True,
        "registry_total": len(registry),
        "tested": tested,
        "ok": ok_count,
        "failed": len(failures),
        "failures": failures,
        "results": results,
        "policy": {
            "read_only_catalog": True,
            "include_web": include_web,
            "max_concurrency": _MAX_CONCURRENCY,
            "per_tool_timeout_seconds": _PER_TOOL_TIMEOUT_SECONDS,
        },
        "summary": (
            f"{ok_count}/{tested} outils testés avec succès "
            f"(registre total : {len(registry)})."
            if not failures
            else f"{ok_count}/{tested} réussis; {len(failures)} à vérifier : "
            + ", ".join(failure["tool"] for failure in failures)
        ),
    }
