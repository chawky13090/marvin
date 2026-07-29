"""Mesures déterministes de qualité pour les rapports de recherche."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


_CITATION = re.compile(r"\[(?:source-)?(\d+)\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def extract_citations(text: object) -> list[int]:
    return [int(match.group(1)) for match in _CITATION.finditer(str(text or ""))]


def factual_sentences(report: object) -> list[str]:
    rows = []
    for sentence in _SENTENCE.split(str(report or "").strip()):
        candidate = sentence.strip()
        if len(candidate) < 30 or candidate.startswith(("#", "-", "*")):
            continue
        if re.search(r"\b(?:est|sont|était|sera|dispose|contient|permet|atteint|représente)\b", candidate, re.I):
            rows.append(candidate)
    return rows


def evaluate_report(report: object, sources: list[dict[str, Any]]) -> dict[str, Any]:
    text = str(report or "").strip()
    source_count = len(sources)
    citations = extract_citations(text)
    valid = [value for value in citations if 1 <= value <= source_count]
    invalid = [value for value in citations if value < 1 or value > source_count]
    factual = factual_sentences(text)
    cited_factual = [sentence for sentence in factual if extract_citations(sentence)]
    domains = {
        (urlsplit(str(source.get("url") or "")).hostname or "").lower()
        for source in sources
        if source.get("url")
    }
    primary = sum(
        1 for source in sources
        if str(source.get("source_type") or "").lower() in {"primary", "academic"}
    )
    return {
        "report_chars": len(text),
        "source_count": source_count,
        "unique_domains": len(domains),
        "citation_count": len(citations),
        "valid_citation_count": len(valid),
        "invalid_citations": invalid,
        "citation_validity": round(len(valid) / len(citations), 4) if citations else 0.0,
        "factual_sentence_count": len(factual),
        "cited_factual_sentence_count": len(cited_factual),
        "factual_citation_coverage": round(len(cited_factual) / len(factual), 4) if factual else 1.0,
        "primary_source_rate": round(primary / source_count, 4) if source_count else 0.0,
        "gate_passed": bool(
            text
            and source_count >= 2
            and not invalid
            and (not factual or len(cited_factual) / len(factual) >= 0.8)
        ),
    }
