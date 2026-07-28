"""Curated official engineering documentation radar with change and freshness tracking."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

import evidence_fabric
import language_registry
import bug_log
from config import DATA_DIR
from durable_evidence_store import DurableEvidenceStore


ROOT = Path(DATA_DIR) / "engineering_radar"
STATE_PATH = ROOT / "state.json"
EVENTS_PATH = ROOT / "events.jsonl"
MAX_TEXT = 50_000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
FetchResult = dict[str, Any]
Fetcher = Callable[[dict[str, Any], dict[str, str]], Awaitable[FetchResult]]

SOURCES: tuple[dict[str, Any], ...] = (
    {"id": "python-whatsnew", "language": "python", "kind": "release",
     "url": "https://docs.python.org/3/whatsnew/index.html", "max_age_hours": 168},
    {"id": "python-packaging", "language": "python", "kind": "conventions",
     "url": "https://packaging.python.org/en/latest/specifications/", "max_age_hours": 336},
    {"id": "python-peps", "language": "python", "kind": "standards",
     "url": "https://peps.python.org/", "max_age_hours": 336},
    {"id": "node-releases", "language": "javascript", "kind": "release",
     "url": "https://nodejs.org/en/about/previous-releases", "max_age_hours": 168},
    {"id": "npm-cli", "language": "javascript", "kind": "conventions",
     "url": "https://docs.npmjs.com/cli/", "max_age_hours": 336},
    {"id": "go-releases", "language": "go", "kind": "release",
     "url": "https://go.dev/doc/devel/release", "max_age_hours": 72},
    {"id": "go-effective", "language": "go", "kind": "conventions",
     "url": "https://go.dev/doc/effective_go", "max_age_hours": 336},
    {"id": "powershell-whatsnew", "language": "powershell", "kind": "release",
     "url": "https://learn.microsoft.com/en-us/powershell/scripting/whats-new/overview", "max_age_hours": 168},
    {"id": "powershell-analyzer", "language": "powershell", "kind": "conventions",
     "url": "https://learn.microsoft.com/en-us/powershell/utility-modules/psscriptanalyzer/overview", "max_age_hours": 336},
    {"id": "bash-manual", "language": "bash", "kind": "conventions",
     "url": "https://www.gnu.org/software/bash/manual/bash.html", "max_age_hours": 720},
    {"id": "typescript-releases", "language": "typescript", "kind": "release",
     "url": "https://www.typescriptlang.org/docs/handbook/release-notes/overview.html", "max_age_hours": 168},
    {"id": "rust-releases", "language": "rust", "kind": "release",
     "url": "https://blog.rust-lang.org/releases/", "max_age_hours": 72},
    {"id": "rust-api-guidelines", "language": "rust", "kind": "conventions",
     "url": "https://rust-lang.github.io/api-guidelines/", "max_age_hours": 336},
    {"id": "dotnet-support", "language": "csharp", "kind": "release",
     "url": "https://learn.microsoft.com/en-us/dotnet/core/releases-and-support", "max_age_hours": 168},
    {"id": "dotnet-guidelines", "language": "csharp", "kind": "conventions",
     "url": "https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/", "max_age_hours": 336},
    {"id": "java-support-roadmap", "language": "java", "kind": "release",
     "url": "https://www.oracle.com/java/technologies/java-se-support-roadmap.html", "max_age_hours": 168},
    {"id": "java-learning", "language": "java", "kind": "conventions",
     "url": "https://dev.java/learn/", "max_age_hours": 336},
    {"id": "cpp-standard-status", "language": "cpp", "kind": "release",
     "url": "https://isocpp.org/std/status", "max_age_hours": 168},
    {"id": "cpp-core-guidelines", "language": "cpp", "kind": "conventions",
     "url": "https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines", "max_age_hours": 336},
)
ALLOWED_HOSTS = frozenset((urlparse(item["url"]).hostname or "").casefold() for item in SOURCES)
_EVENT_STORE: DurableEvidenceStore | None = None
_EVENT_STORE_PATH: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _load() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"version": 1, "sources": {}}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "sources": {}}
    return value if isinstance(value, dict) else {"version": 1, "sources": {}}


def _event_store() -> DurableEvidenceStore:
    global _EVENT_STORE, _EVENT_STORE_PATH
    resolved = str(EVENTS_PATH.resolve())
    if _EVENT_STORE is None or _EVENT_STORE_PATH != resolved:
        _EVENT_STORE = DurableEvidenceStore(
            resolved,
            stream_name="marvin.engineering_radar.events",
        )
        _EVENT_STORE_PATH = resolved
    return _EVENT_STORE


def _event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    event = {"at": _iso(), "type": event_type, "payload": payload}
    return _event_store().append(event)


def evidence_integrity() -> dict[str, Any]:
    return _event_store().verify()


def _due(source: dict[str, Any], current: dict[str, Any] | None, *, force: bool) -> bool:
    if force or not current or not current.get("retrieved_at"):
        return True
    try:
        retrieved = datetime.fromisoformat(str(current["retrieved_at"]).replace("Z", "+00:00"))
    except ValueError:
        return True
    return _now() >= retrieved.astimezone(timezone.utc) + timedelta(hours=int(source["max_age_hours"]))


def _extract_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(str(html or ""), "lxml")
    for node in soup.select("script,style,noscript,svg,nav,footer,form"):
        node.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = re.sub(r"\n{3,}", "\n\n", root.get_text("\n", strip=True))[:MAX_TEXT]
    return title[:300], text


def _validate_fetch_url(url: str, expected_host: str) -> str:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host != expected_host or host not in ALLOWED_HOSTS:
        raise ValueError("Redirection hors domaine officiel attendu.")
    if parsed.port not in (None, 443):
        raise ValueError("Port non standard interdit pour une source documentaire.")
    if parsed.username or parsed.password:
        raise ValueError("Identifiants interdits dans une URL documentaire.")
    return parsed.geturl()


async def _fetch_with_client(
    source: dict[str, Any],
    headers: dict[str, str],
    client: httpx.AsyncClient,
) -> FetchResult:
    source_host = (urlparse(source["url"]).hostname or "").casefold()
    current_url = _validate_fetch_url(source["url"], source_host)
    for redirect_count in range(6):
        async with client.stream("GET", current_url, headers=headers) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                if redirect_count >= 5:
                    raise ValueError("Trop de redirections documentaires.")
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirection documentaire sans destination.")
                current_url = _validate_fetch_url(
                    urljoin(current_url, location),
                    source_host,
                )
                continue
            if response.status_code == 304:
                return {
                    "status": 304,
                    "url": current_url,
                    "body": "",
                    "headers": {
                        key.casefold(): value for key, value in response.headers.items()
                    },
                }
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError("Documentation officielle trop volumineuse.")
            encoding = response.encoding or "utf-8"
            return {
                "status": response.status_code,
                "url": current_url,
                "body": bytes(body).decode(encoding, errors="replace"),
                "headers": {
                    key.casefold(): value for key, value in response.headers.items()
                },
            }
    raise ValueError("Redirections documentaires invalides.")


async def _http_fetch(source: dict[str, Any], headers: dict[str, str]) -> FetchResult:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=8.0),
        follow_redirects=False,
        headers={"User-Agent": "Marvin-Engineering-Radar/1.0"},
    ) as client:
        return await _fetch_with_client(source, headers, client)


async def refresh(
    languages: list[str] | None = None,
    *,
    force: bool = False,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    selected = {language_registry.normalize(item) for item in (languages or []) if str(item).strip()}
    sources = [item for item in SOURCES if not selected or item["language"] in selected]
    state = _load()
    records = dict(state.get("sources") or {})
    fetch = fetcher or _http_fetch
    updated, unchanged, skipped, errors = [], [], [], []

    for source in sources:
        current = records.get(source["id"])
        if not _due(source, current, force=force):
            skipped.append(source["id"])
            continue
        conditional: dict[str, str] = {}
        if current and current.get("etag"):
            conditional["If-None-Match"] = str(current["etag"])
        if current and current.get("last_modified"):
            conditional["If-Modified-Since"] = str(current["last_modified"])
        try:
            result = await fetch(source, conditional)
            status = int(result.get("status") or 0)
            if status == 304 and current:
                current["retrieved_at"] = _iso()
                current["status"] = "current"
                records[source["id"]] = current
                unchanged.append(source["id"])
                continue
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            result_url = _validate_fetch_url(
                str(result.get("url") or source["url"]),
                (urlparse(source["url"]).hostname or "").casefold(),
            )
            title, text = _extract_text(str(result.get("body") or ""))
            if len(text) < 200:
                raise RuntimeError("Documentation officielle vide ou trop courte.")
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            changed = not current or current.get("content_sha256") != digest
            headers = {str(k).casefold(): str(v) for k, v in dict(result.get("headers") or {}).items()}
            record = {
                "id": source["id"], "language": source["language"], "kind": source["kind"],
                "title": title or source["id"], "url": result_url,
                "retrieved_at": _iso(), "max_age_hours": source["max_age_hours"],
                "content_sha256": digest, "etag": headers.get("etag"),
                "last_modified": headers.get("last-modified"), "status": "current",
                "changed": changed, "content_guard": evidence_fabric.scan_untrusted_content(text),
                "text": text,
            }
            if changed:
                previous_state = deepcopy(state)
                previous_records = deepcopy(records)
                records[source["id"]] = record
                next_state = {"version": 1, "updated_at": _iso(), "sources": records}
                _atomic_write(STATE_PATH, next_state)
                try:
                    _event("official_source_changed", {
                        "id": source["id"],
                        "language": source["language"],
                        "sha256": digest,
                        "url": record["url"],
                    })
                except Exception:
                    records = previous_records
                    state = previous_state
                    _atomic_write(STATE_PATH, previous_state)
                    raise
                state = next_state
                updated.append(source["id"])
            else:
                records[source["id"]] = record
                unchanged.append(source["id"])
        except Exception as exc:  # errors are persisted and never block Marvin startup
            error_type = type(exc).__name__
            errors.append({"id": source["id"], "error": error_type})
            bug_log.log_bug(
                "engineering_radar_refresh",
                "Actualisation d'une source officielle impossible.",
                context={"source_id": source["id"], "error_type": error_type},
            )
            if current:
                current["status"] = "refresh_error"
                current["last_error"] = error_type
                records[source["id"]] = current
    state = {"version": 1, "updated_at": _iso(), "sources": records}
    _atomic_write(STATE_PATH, state)
    return {"updated": updated, "unchanged": unchanged, "skipped": skipped, "errors": errors,
            "source_count": len(records)}


def detect_languages(request: str) -> list[str]:
    text = str(request or "").casefold()
    detected = []
    for item in language_registry.matrix():
        if item["language"] == "go":
            if re.search(
                r"\bgolang\b|\b(?:langage|language|code|script|programme|service|module|projet|application)\s+"
                r"(?:en\s+)?go\b|\bgo\s+(?:1\.\d+|module|package|test|build)\b|\.go\b",
                text,
            ):
                detected.append("go")
            continue
        candidates = [item["language"], *item.get("aliases", [])]
        if any(re.search(rf"(?<!\w){re.escape(alias.casefold())}(?!\w)", text) for alias in candidates):
            detected.append(item["language"])
    return list(dict.fromkeys(detected))


def context(languages: list[str], *, max_chars: int = 18_000) -> dict[str, Any]:
    selected = {language_registry.normalize(item) for item in languages}
    state = _load()
    records = [item for item in dict(state.get("sources") or {}).values() if item.get("language") in selected]
    blocks, consumed = [], 0
    public_sources = []
    for item in sorted(records, key=lambda row: (row.get("language", ""), row.get("kind", ""))):
        source = next((row for row in SOURCES if row["id"] == item.get("id")), None)
        stale = _due(source, item, force=False) if source else True
        freshness = "stale" if stale else str(item.get("status") or "unknown")
        block = (
            f"BEGIN_UNTRUSTED_OFFICIAL_DOCUMENTATION [{item['id']}]\n"
            f"URL: {item['url']}\nSHA256: {item['content_sha256']}\n"
            f"RETRIEVED_AT: {item['retrieved_at']}\nFRESHNESS: {freshness}\n"
            f"{str(item.get('text') or '')[:7000]}\n"
            f"END_UNTRUSTED_OFFICIAL_DOCUMENTATION [{item['id']}]"
        )
        if consumed + len(block) > max_chars:
            break
        blocks.append(block)
        consumed += len(block)
        public = {key: item.get(key) for key in (
            "id", "language", "kind", "title", "url", "retrieved_at", "content_sha256", "status", "changed"
        )}
        public["freshness"] = freshness
        public_sources.append(public)
    return {"languages": sorted(selected), "context": "\n\n".join(blocks), "sources": public_sources,
            "source_count": len(public_sources), "available": bool(blocks)}


async def ensure_for_request(request: str) -> dict[str, Any]:
    languages = detect_languages(request)
    if not languages:
        return {"languages": [], "context": "", "sources": [], "source_count": 0, "available": False}
    await refresh(languages)
    return context(languages)


async def background_worker() -> None:
    while True:
        try:
            await refresh()
        except Exception as exc:
            error_type = type(exc).__name__
            bug_log.log_bug(
                "engineering_radar_background",
                "Actualisation globale du radar impossible.",
                context={"error_type": error_type},
            )
            print(
                "[Marvin] Engineering Knowledge Radar : actualisation échouée "
                f"({error_type})."
            )
        await asyncio.sleep(6 * 60 * 60)
