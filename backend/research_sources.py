"""Normalisation, classement et déduplication des sources de recherche."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
}
_PRIMARY_HOST_MARKERS = (
    ".gov", ".gouv.fr", ".europa.eu", ".edu", "ietf.org", "rfc-editor.org",
    "w3.org", "docs.", "developer.", "learn.microsoft.com",
)


def canonical_url(value: object) -> str:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL HTTP(S) publique invalide.")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    port = parsed.port
    netloc = host
    if port and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS
    ))
    return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def content_fingerprint(text: object) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def content_signature(text: object) -> frozenset[str]:
    """Signature bornée pour repérer les reprises quasi identiques."""
    tokens = re.findall(r"[a-zà-ÿ0-9]{3,}", str(text or "").casefold())[:2_000]
    if len(tokens) < 3:
        return frozenset(tokens)
    return frozenset(
        " ".join(tokens[index:index + 3])
        for index in range(len(tokens) - 2)
    )


def source_type(url: str, title: str = "") -> str:
    host = urlsplit(url).hostname or ""
    folded = f"{host} {title}".casefold()
    if any(marker in folded for marker in _PRIMARY_HOST_MARKERS):
        return "primary"
    if any(marker in folded for marker in ("arxiv.org", "doi.org", "pubmed", "journal", "research")):
        return "academic"
    if any(marker in folded for marker in ("forum", "reddit.", "stackoverflow.")):
        return "community"
    return "secondary"


@dataclass(slots=True)
class ResearchSource:
    id: str
    url: str
    title: str
    text: str
    query_ids: list[str] = field(default_factory=list)
    source_type: str = "secondary"
    domain: str = ""
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    fingerprint: str = ""
    duplicate_of: str | None = None
    content_guard: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        value = asdict(self)
        if not include_text:
            value.pop("text", None)
            value.pop("content_guard", None)
        return value


class SourceIndex:
    def __init__(self, *, max_sources_per_domain: int = 20) -> None:
        self._by_url: dict[str, ResearchSource] = {}
        self._by_fingerprint: dict[str, ResearchSource] = {}
        self._domain_counts: dict[str, int] = {}
        self._signatures: dict[str, frozenset[str]] = {}
        self._max_sources_per_domain = max(1, min(int(max_sources_per_domain), 100))

    def add(
        self,
        *,
        url: object,
        title: object,
        text: object,
        query_id: str,
        content_guard: dict[str, Any] | None = None,
    ) -> tuple[ResearchSource, bool]:
        normalized_url = canonical_url(url)
        existing = self._by_url.get(normalized_url)
        if existing:
            if query_id not in existing.query_ids:
                existing.query_ids.append(query_id)
            return existing, False
        normalized_text = str(text or "").strip()
        if not normalized_text:
            raise ValueError("Une source vide ne peut pas être indexée.")
        fingerprint = content_fingerprint(normalized_text)
        duplicate = self._by_fingerprint.get(fingerprint)
        if duplicate:
            if query_id not in duplicate.query_ids:
                duplicate.query_ids.append(query_id)
            return duplicate, False
        signature = content_signature(normalized_text)
        if signature:
            for source_id, known in self._signatures.items():
                union = len(signature | known)
                similarity = len(signature & known) / union if union else 0.0
                if similarity >= 0.92:
                    near_duplicate = next(
                        source for source in self._by_url.values()
                        if source.id == source_id
                    )
                    if query_id not in near_duplicate.query_ids:
                        near_duplicate.query_ids.append(query_id)
                    return near_duplicate, False
        host = (urlsplit(normalized_url).hostname or "").lower()
        if self._domain_counts.get(host, 0) >= self._max_sources_per_domain:
            raise OverflowError("Concentration maximale atteinte pour ce domaine.")
        source = ResearchSource(
            id=f"source-{len(self._by_url) + 1}",
            url=normalized_url,
            title=" ".join(str(title or "").split())[:500],
            text=normalized_text,
            query_ids=[query_id],
            source_type=source_type(normalized_url, str(title or "")),
            domain=host,
            fingerprint=fingerprint,
            content_guard=dict(content_guard or {}),
        )
        self._by_url[normalized_url] = source
        self._by_fingerprint[fingerprint] = source
        self._signatures[source.id] = signature
        self._domain_counts[host] = self._domain_counts.get(host, 0) + 1
        return source, True

    def values(self) -> list[ResearchSource]:
        return list(self._by_url.values())

    def metrics(self) -> dict[str, Any]:
        values = self.values()
        type_counts: dict[str, int] = {}
        for source in values:
            type_counts[source.source_type] = type_counts.get(source.source_type, 0) + 1
        largest_domain = max(self._domain_counts.values(), default=0)
        return {
            "unique_sources": len(values),
            "unique_domains": len(self._domain_counts),
            "source_types": type_counts,
            "largest_domain_share": round(largest_domain / len(values), 4) if values else 0.0,
        }
