"""Deterministic contracts shared by Marvin tools and autonomous coding jobs."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from difflib import get_close_matches
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx


CONTRACT_VERSION = "1.0"
TERMINAL_STATES = {"succeeded", "failed", "blocked", "cancelled"}
_SECRET_MARKERS = ("password", "token", "secret", "authorization", "cookie", "api_key")
_HTTPS_URL = re.compile(r"https://[^\s'\"<>]+", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: Any, key: str = "") -> Any:
    if any(marker in key.casefold() for marker in _SECRET_MARKERS):
        return "***"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value[:200]]
    if isinstance(value, str):
        return value[:20_000]
    return value


def normalize_tool_result(tool_name: str, result: Any, *, duration_ms: int | None = None) -> Any:
    """Add a stable, non-breaking contract to every dictionary tool result."""
    if not isinstance(result, dict):
        return result
    normalized = dict(result)
    if normalized.get("requiresConfirmation"):
        status, retryable = "blocked", False
        error_code = "CONFIRMATION_REQUIRED"
    elif normalized.get("cancelled") or normalized.get("status") == "cancelled":
        status, retryable = "cancelled", False
        error_code = "CANCELLED"
    elif normalized.get("success") is False or normalized.get("error"):
        status = "failed"
        retryable = bool(normalized.get("retryable", True))
        error_code = str(normalized.get("error_code") or "TOOL_EXECUTION_FAILED")
    elif normalized.get("status") in {"queued", "running", "interrupted", "paused"}:
        status, retryable = "running", True
        error_code = None
    else:
        status, retryable = "succeeded", False
        error_code = None
    summary = normalized.get("message") or normalized.get("error") or normalized.get("summary")
    normalized["_contract"] = {
        "version": CONTRACT_VERSION,
        "tool": str(tool_name),
        "status": status,
        "success": status == "succeeded",
        "retryable": retryable,
        "error_code": error_code,
        "summary": str(summary or "")[:1_000],
        "duration_ms": max(0, int(duration_ms)) if duration_ms is not None else None,
        "evidence_count": len(normalized.get("evidence") or normalized.get("steps") or []),
        "artifact_count": len(normalized.get("artifacts") or normalized.get("files") or []),
        "next_actions": list(normalized.get("next_actions") or [])[:20],
        "rollback_available": bool(normalized.get("rollback")),
    }
    return normalized


def classify_failure(result: dict[str, Any]) -> dict[str, Any]:
    """Produce compact repair context from a rejected Code Forge result."""
    report = dict(result.get("test_report") or {})
    contract = dict(result.get("production_contract") or {})
    bundle = dict(result.get("bundle") or {})
    failed_steps = list(report.get("failed_steps") or [])
    step_diagnostics = []
    for step in report.get("steps") or []:
        if not isinstance(step, dict) or step.get("passed") is True:
            continue
        step_diagnostics.append({
            "name": str(step.get("name") or "")[:200],
            "exit_code": step.get("exit_code"),
            "error": str(step.get("error") or "")[-1_500:],
            "stderr": str(step.get("stderr") or "")[-2_500:],
            "stdout": str(step.get("stdout") or "")[-2_500:],
            "findings": list(step.get("findings") or [])[:20],
        })
    failures = list(contract.get("failures") or [])
    bundle_errors = list(bundle.get("errors") or [])
    error = str(result.get("error") or "")
    joined = " ".join([error, *map(str, failed_steps), *map(str, failures), *map(str, bundle_errors)]).casefold()
    if any(word in joined for word in ("timeout", "network", "connexion", "download")):
        category, retryable = "environment", True
    elif any(word in joined for word in ("dependency", "dépendance", "package", "lockfile")):
        category, retryable = "dependency", True
    elif any(word in joined for word in ("test", "assert", "bats", "pester", "unittest")):
        category, retryable = "test_or_code", True
    elif any(word in joined for word in ("confirmation", "secret", "credential")):
        category, retryable = "human_input", False
    else:
        category, retryable = "code_or_contract", True
    signature_payload = json.dumps({
        "category": category, "error": error[:500], "failed_steps": failed_steps[:30],
        "failures": failures[:30], "bundle_errors": bundle_errors[:30],
        "step_diagnostics": step_diagnostics[:20],
    }, ensure_ascii=False, sort_keys=True)
    return {
        "category": category,
        "retryable": retryable,
        "error": error[:1_000] or "Code Forge a refusé le livrable.",
        "failed_steps": failed_steps[:50],
        "contract_failures": failures[:50],
        "bundle_errors": bundle_errors[:50],
        "step_diagnostics": step_diagnostics[:20],
        "signature": hashlib.sha256(signature_payload.encode("utf-8")).hexdigest(),
        "instructions": (
            "Conserve les fichiers et contrôles déjà valides. Corrige uniquement les causes listées, "
            "ajoute un test de non-régression, puis réexécute les validations affectées et la suite complète."
        ),
    }


def diagnose_public_urls(files: dict[str, str], *, limit: int = 8) -> list[dict[str, Any]]:
    """Contrôle les URL HTTPS d'un candidat sans autoriser les réseaux privés.

    Les redirections ne sont pas suivies. Pour un artefact absent, l'index du
    répertoire parent est lu de façon bornée afin de suggérer des noms proches.
    """
    candidates: list[str] = []
    for content in files.values():
        for match in _HTTPS_URL.findall(str(content or "")):
            url = match.rstrip(".,);]}")
            if url not in candidates:
                candidates.append(url)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    diagnostics: list[dict[str, Any]] = []
    with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
        for raw_url in candidates:
            parsed = urlsplit(raw_url)
            hostname = (parsed.hostname or "").rstrip(".").casefold()
            display_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            item: dict[str, Any] = {"url": display_url, "status": None, "alternatives": []}
            if (
                parsed.scheme.casefold() != "https"
                or not hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in (None, 443)
            ):
                item["error"] = "URL refusée par la politique HTTPS publique."
                diagnostics.append(item)
                continue
            try:
                addresses = {
                    row[4][0]
                    for row in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
                }
                if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
                    item["error"] = "Destination non publique refusée."
                    diagnostics.append(item)
                    continue
                response = client.head(display_url)
                item["status"] = response.status_code
                item["content_type"] = str(response.headers.get("content-type") or "")[:200]
                item["content_length"] = str(response.headers.get("content-length") or "")[:50]
                if response.status_code in {301, 302, 303, 307, 308}:
                    item["location"] = str(response.headers.get("location") or "")[:1_000]
                if response.status_code in {404, 410}:
                    parent_url = urljoin(display_url, "./")
                    parent = client.get(parent_url, headers={"Range": "bytes=0-131071"})
                    if parent.status_code == 200:
                        names = [
                            unquote(value).rsplit("/", 1)[-1]
                            for value in re.findall(r'href=["\']([^"\']+)["\']', parent.text[:131_072], re.I)
                        ]
                        wanted = unquote(parsed.path.rsplit("/", 1)[-1])
                        close = get_close_matches(wanted, sorted(set(names)), n=5, cutoff=0.45)
                        item["alternatives"] = [urljoin(parent_url, name) for name in close]
            except (OSError, ValueError, httpx.HTTPError) as exc:
                item["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            diagnostics.append(item)
    return diagnostics


def definition_of_done(
    result: dict[str, Any], *, targets: set[str], windows_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute acceptance independently from the LLM narrative."""
    report = dict(result.get("test_report") or {})
    contract = dict(result.get("production_contract") or {})
    files = dict(result.get("files") or {})
    checks = {
        "files_present": bool(files),
        "forge_accepted": result.get("success") is True,
        "tests_executed": report.get("tests_executed") is True,
        "test_forge_production_ready": report.get("production_ready") is True,
        "production_contract": contract.get("success") is True,
        "no_critical_issues": int(result.get("critical_issues") or 0) == 0,
        "no_high_issues": int(result.get("high_issues") or 0) == 0,
    }
    if "windows" in targets:
        checks["windows_native_execution"] = bool(
            (windows_validation or {}).get("native_execution_validated")
        )
    if "linux" in targets:
        checks["linux_execution"] = report.get("production_ready") is True
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "version": CONTRACT_VERSION,
        "success": not failures,
        "checks": checks,
        "failures": failures,
        "evaluated_at": _now(),
    }


def delivery_pack(
    mission: dict[str, Any], result: dict[str, Any], done: dict[str, Any],
    *, workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files = dict(result.get("files") or {})
    manifest = [
        {"path": path, "bytes": len(content.encode("utf-8")),
         "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
        for path, content in sorted(files.items())
    ]
    return _redact({
        "schema": "marvin.delivery-pack/1.0",
        "mission_id": mission.get("id"),
        "request": mission.get("request"),
        "status": "accepted" if done.get("success") else "rejected",
        "created_at": _now(),
        "targets": mission.get("target_platforms") or [],
        "definition_of_done": done,
        "manifest": manifest,
        "workspace": workspace or {},
        "test_report": result.get("test_report") or {},
        "production_contract": result.get("production_contract") or {},
        "models_consulted": result.get("models_consulted") or [],
        "known_limitations": [] if done.get("success") else list(done.get("failures") or []),
    })


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
