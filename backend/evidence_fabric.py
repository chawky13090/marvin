"""Evidence Fabric: claim-level provenance, source hygiene and epistemic debt.

This module is deterministic and does not call an LLM. Observed content is always
treated as untrusted data: detected instructions are reported, never executed.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse


_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
_REF_RE = re.compile(r"\[([A-Za-z0-9_-]{1,80})\]")
_INJECTION_PATTERNS = (
    ("instruction_override", re.compile(r"\bignore (?:all |any )?(?:previous|prior|system) instructions?\b", re.I)),
    ("instruction_override", re.compile(r"\bdisregard (?:all |any )?(?:previous|prior|system) instructions?\b", re.I)),
    ("prompt_extraction", re.compile(r"\b(system prompt|developer message|hidden instructions?)\b", re.I)),
    ("secret_exfiltration", re.compile(r"\b(exfiltrate|reveal|print|send)\b.{0,50}\b(token|secret|password|cookie|api key)\b", re.I)),
    ("tool_execution_request", re.compile(r"\b(call|invoke|execute|run)\b.{0,50}\b(tool|command|powershell|shell)\b", re.I)),
)
_STOPWORDS = {
    "avec", "dans", "pour", "sans", "sous", "sur", "une", "des", "les", "leur", "leurs",
    "cette", "cela", "comme", "plus", "moins", "être", "est", "sont", "the", "and", "for",
    "from", "that", "this", "with", "dans", "par", "aux", "qui", "que", "quoi",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(value: str) -> str:
    raw = str(value or "").strip().rstrip(".,;:")
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw
    host = parsed.netloc.casefold()
    if host.endswith(":80") and parsed.scheme == "http":
        host = host[:-3]
    elif host.endswith(":443") and parsed.scheme == "https":
        host = host[:-4]
    return urlunparse((parsed.scheme.casefold(), host, parsed.path or "/", "", parsed.query, ""))


def split_claims(text: str, *, limit: int = 100) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return []
    parts = re.split(r"(?<=[.!?])\s+|(?=\s*(?:[-*]|\d+[.)])\s+)", clean)
    return [part.strip() for part in parts if len(part.strip()) >= 25][: max(1, min(limit, 500))]


def source_authority(url: str) -> dict[str, Any]:
    host = (urlparse(url).hostname or "").casefold()
    path = (urlparse(url).path or "").casefold()
    official_markers = ("docs.", "developer.", "learn.", "support.", "help.")
    primary_markers = ("/docs", "/documentation", "/reference", "/standards", "/rfc", "/research")
    if host.endswith((".gov", ".gouv.fr", ".europa.eu", ".int")):
        return {"level": "authoritative", "score": 1.0, "reason": "institution publique"}
    if host.endswith((".edu", ".ac.uk")):
        return {"level": "primary", "score": 0.9, "reason": "institution académique"}
    if host.startswith(official_markers) or any(marker in path for marker in primary_markers):
        return {"level": "primary", "score": 0.85, "reason": "documentation ou publication primaire probable"}
    if host:
        return {"level": "secondary", "score": 0.55, "reason": "source web sans autorité établie automatiquement"}
    return {"level": "unknown", "score": 0.25, "reason": "origine non identifiable"}


def source_freshness(published_at: str | None, *, max_age_days: int = 730) -> dict[str, Any]:
    if not published_at:
        return {"status": "unknown", "age_days": None, "max_age_days": max_age_days}
    value = str(published_at).strip().replace("Z", "+00:00")
    try:
        published = datetime.fromisoformat(value)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    except ValueError:
        return {"status": "invalid", "age_days": None, "max_age_days": max_age_days}
    age_days = max(0, (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).days)
    return {
        "status": "current" if age_days <= max_age_days else "stale",
        "age_days": age_days,
        "max_age_days": max_age_days,
    }


def scan_untrusted_content(text: str) -> dict[str, Any]:
    value = str(text or "")
    findings = []
    for finding, pattern in _INJECTION_PATTERNS:
        if pattern.search(value):
            findings.append(finding)
    return {
        "tainted": True,
        "instruction_like_content": bool(findings),
        "findings": findings[:10],
        "policy": "data_only",
    }


def prepare_sources(
    sources: list[dict[str, Any]] | None,
    *,
    max_source_age_days: int = 730,
) -> list[dict[str, Any]]:
    prepared = []
    seen: set[str] = set()
    for index, raw in enumerate(sources or [], start=1):
        if not isinstance(raw, dict):
            continue
        url = normalize_url(str(raw.get("url") or ""))
        citation = str(raw.get("citation") or raw.get("id") or index).strip()[:80]
        aliases = [citation]
        aliases.extend(str(item).strip()[:80] for item in raw.get("citations", []) if str(item).strip())
        key = url or f"ref:{citation}"
        if key in seen:
            continue
        seen.add(key)
        observed = str(raw.get("text") or raw.get("excerpt") or raw.get("snippet") or "")
        authority = source_authority(url)
        published_at = str(raw.get("published_at") or "") or None
        prepared.append({
            "id": citation,
            "aliases": list(dict.fromkeys(aliases)),
            "title": str(raw.get("title") or url or citation)[:300],
            "url": url,
            "domain": (urlparse(url).hostname or "").casefold(),
            "authority": authority,
            "retrieved_at": str(raw.get("retrieved_at") or utc_now()),
            "published_at": published_at,
            "freshness": source_freshness(published_at, max_age_days=max_source_age_days),
            "content_sha256": hashlib.sha256(observed.encode("utf-8", errors="ignore")).hexdigest() if observed else None,
            "content_guard": scan_untrusted_content(observed),
            "_observed_text": observed,
        })
    return prepared


def _references_for_claim(claim: str, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    urls = {normalize_url(item) for item in _URL_RE.findall(claim)}
    refs = {item.casefold() for item in _REF_RE.findall(claim)}
    matched = []
    for source in catalog:
        aliases = {str(item).casefold() for item in source.get("aliases", [])}
        if (source.get("url") and source["url"] in urls) or aliases.intersection(refs):
            matched.append(source)
    return matched


def _lexical_support(claim: str, source_text: str) -> float:
    tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9_-]{2,}", claim)
        if token.casefold() not in _STOPWORDS and not token.casefold().startswith(("http", "cell-"))
    }
    if not tokens or not source_text:
        return 0.0
    observed = source_text.casefold()
    return round(sum(token in observed for token in tokens) / len(tokens), 4)


def build_bundle(
    answer: str,
    *,
    sources: list[dict[str, Any]] | None = None,
    evidence_tools: list[str] | None = None,
    reviewed: bool = False,
    contradictions: list[str] | None = None,
    max_source_age_days: int = 730,
) -> dict[str, Any]:
    max_source_age_days = max(1, min(int(max_source_age_days), 36500))
    catalog = prepare_sources(sources, max_source_age_days=max_source_age_days)
    tools = sorted(set(str(item) for item in (evidence_tools or []) if str(item)))
    contradiction_text = [str(item)[:1000] for item in (contradictions or []) if str(item).strip()]
    claims = []
    raw_debt = 0.0
    for claim in split_claims(answer):
        matched = _references_for_claim(claim, catalog)
        domains = {item.get("domain") for item in matched if item.get("domain")}
        if matched:
            status = "sourced"
            authority = max(float(item["authority"]["score"]) for item in matched)
            support_scores = [_lexical_support(claim, item.get("_observed_text", "")) for item in matched]
            best_support = max(support_scores, default=0.0)
            content_available = any(bool(item.get("_observed_text")) for item in matched)
            support_level = (
                "lexical_support" if best_support >= 0.12
                else "content_available_unverified" if content_available
                else "citation_only"
            )
            confidence = min(
                0.98,
                0.48 + authority * 0.22 + min(len(domains), 2) * 0.07
                + (0.08 if reviewed else 0) + (0.08 if best_support >= 0.12 else 0),
            )
            debt = (
                0.08 if len(domains) >= 2 and best_support >= 0.12
                else 0.18 if best_support >= 0.12
                else 0.3 if content_available
                else 0.4
            )
            stale_sources = sum(item["freshness"]["status"] == "stale" for item in matched)
            if stale_sources:
                debt = min(1.0, debt + min(stale_sources, 2) * 0.12)
                confidence = max(0.1, confidence - min(stale_sources, 2) * 0.08)
        elif tools:
            status = "tool_supported"
            confidence = 0.65 if reviewed else 0.55
            debt = 0.45
            best_support = 0.0
            support_level = "tool_receipt_only"
        else:
            status = "unsupported"
            confidence = 0.3 if reviewed else 0.2
            debt = 1.0
            best_support = 0.0
            support_level = "none"
        raw_debt += debt
        claims.append({
            "claim": claim[:1500],
            "status": status,
            "source_ids": [item["id"] for item in matched],
            "sources": [item["url"] for item in matched if item.get("url")],
            "independent_domains": len(domains),
            "support_level": support_level,
            "lexical_support": best_support,
            "corroborated": len(domains) >= 2,
            "stale_source_count": sum(
                item["freshness"]["status"] == "stale" for item in matched
            ),
            "evidence_tools": tools,
            "reviewed": bool(reviewed),
            "confidence": round(confidence, 3),
            "debt": round(debt, 3),
        })
    count = len(claims)
    debt_score = round(raw_debt / count, 4) if count else 0.0
    injection_sources = [item["id"] for item in catalog if item["content_guard"]["instruction_like_content"]]
    public_catalog = [{key: value for key, value in item.items() if key != "_observed_text"} for item in catalog]
    if contradiction_text and count:
        debt_score = min(1.0, round(debt_score + min(len(contradiction_text), 3) * 0.08, 4))
    return {
        "version": 1,
        "generated_at": utc_now(),
        "claims": claims,
        "claim_count": count,
        "sourced_count": sum(item["status"] == "sourced" for item in claims),
        "tool_supported_count": sum(item["status"] == "tool_supported" for item in claims),
        "unsupported_count": sum(item["status"] == "unsupported" for item in claims),
        "multi_source_count": sum(item["independent_domains"] >= 2 for item in claims),
        "corroborated_count": sum(bool(item["corroborated"]) for item in claims),
        "lexically_supported_count": sum(item["support_level"] == "lexical_support" for item in claims),
        "source_count": len(catalog),
        "source_catalog": public_catalog,
        "source_quality": {
            "authoritative_or_primary": sum(
                item["authority"]["level"] in {"authoritative", "primary"} for item in catalog
            ),
            "current": sum(item["freshness"]["status"] == "current" for item in catalog),
            "stale": sum(item["freshness"]["status"] == "stale" for item in catalog),
            "unknown_freshness": sum(item["freshness"]["status"] in {"unknown", "invalid"} for item in catalog),
            "independent_domains": len({item["domain"] for item in catalog if item["domain"]}),
        },
        "contradictions": contradiction_text,
        "epistemic_debt": {
            "score": debt_score,
            "level": "low" if debt_score <= 0.25 else "moderate" if debt_score <= 0.55 else "high",
        },
        "source_firewall": {
            "policy": "observed_content_is_data_only",
            "flagged_source_ids": injection_sources,
            "flagged_count": len(injection_sources),
        },
    }
