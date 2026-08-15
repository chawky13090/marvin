"""Équivalence et coût observé du cache borné des motifs de sélection."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_tool_selection as selection
import dpapi_secret_store
import real_usage_corpus


POLICY = ROOT / "benchmarks/tool-selection/v1.1/keyword-regex-cache-preregistration.json"
PRIVATE = ROOT / "data/forge/real-usage-v1/real-usage-text.dpapi.json"


@lru_cache(maxsize=None)
def reference_pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword).replace(r"\ ", r"\s+")
    left = r"(?<![a-z0-9])" if keyword[0].isalnum() else ""
    right = r"(?![a-z0-9])" if keyword[-1].isalnum() else ""
    return re.compile(left + escaped + right)


def reference_present(keyword: str, text: str) -> bool:
    normalized = str(keyword or "").strip()
    return bool(normalized and reference_pattern(normalized).search(text))


def uncached_present(keyword: str, text: str) -> bool:
    normalized = str(keyword or "").strip()
    if not normalized:
        return False
    escaped = re.escape(normalized).replace(r"\ ", r"\s+")
    left = r"(?<![a-z0-9])" if normalized[0].isalnum() else ""
    right = r"(?![a-z0-9])" if normalized[-1].isalnum() else ""
    return re.search(left + escaped + right, text) is not None


def public_queries() -> list[str]:
    intents = json.loads(
        (ROOT / "benchmarks/windows-operator/v1.1/intent-corpus.json").read_text(
            encoding="utf-8"
        )
    )
    recovery = json.loads(
        (ROOT / "benchmarks/tool-recovery/v1.2/development-corpus.json").read_text(
            encoding="utf-8"
        )
    )
    return [str(item["prompt"]) for item in intents["items"]] + [
        str(item["unknown_name"]).replace("_", " ") for item in recovery["items"]
    ]


def private_queries() -> list[str]:
    if not PRIVATE.exists():
        return []
    envelope = json.loads(PRIVATE.read_text(encoding="utf-8"))
    records = real_usage_corpus.unprotect_payload(
        envelope,
        unprotect=lambda value, purpose: dpapi_secret_store.unprotect_bytes(
            value,
            purpose=purpose,
        ),
    )
    return [str(item["text"]) for item in records]


def vocabulary() -> tuple[str, ...]:
    values = {
        keyword
        for keywords, _tools in selection._KEYWORD_TOOLS_NORM
        for keyword in keywords
    }
    values.update(selection._VISUAL_CONTROL_TERMS_NORM)
    for specification in selection.TOOLS_SPEC:
        name = str(specification.get("function", {}).get("name") or "")
        if name:
            values.add(name)
            values.add(name.replace("_", " "))
    return tuple(sorted(value for value in values if value))


def ordinary_vocabulary() -> tuple[str, ...]:
    """Legacy exact-match contract, excluding preregistered explicit prefixes."""

    return tuple(value for value in vocabulary() if not value.endswith("*"))


def keyword_hits(
    query: str,
    predicate: Callable[[str, str], bool],
    *,
    ordinary_only: bool = False,
) -> set[str]:
    text = selection._strip_accents(query.lower())
    hits: set[str] = set()
    for keywords, tools in selection._KEYWORD_TOOLS_NORM:
        evaluated = (
            keyword for keyword in keywords
            if not ordinary_only or not keyword.endswith("*")
        )
        if any(predicate(keyword, text) for keyword in evaluated):
            hits.update(tools)
    return hits


def scan_cost(predicate: Callable[[str, str], bool], query: str, repetitions: int = 28) -> float:
    text = selection._strip_accents(query.lower())
    started = time.perf_counter()
    for _ in range(repetitions):
        for keywords, _tools in selection._KEYWORD_TOOLS_NORM:
            any(predicate(keyword, text) for keyword in keywords)
    return (time.perf_counter() - started) * 1000.0


def main() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["status"] == "frozen_before_product_optimization"
    queries = public_queries()
    private = private_queries()
    queries.extend(private)
    terms = ordinary_vocabulary()
    mismatch_count = 0
    hit_set_mismatch_count = 0
    for query in queries:
        text = selection._strip_accents(query.lower())
        mismatch_count += sum(
            reference_present(term, text) != selection._keyword_present(term, text)
            for term in terms
        )
        hit_set_mismatch_count += int(
            keyword_hits(query, reference_present, ordinary_only=True)
            != keyword_hits(query, selection._keyword_present, ordinary_only=True)
        )
    canaries = (
        ("ip", "adresse ip", True),
        ("ip", "multiplie", False),
        ("process", "liste les process", True),
        ("process", "processeur", False),
        ("+", "2 + 2", True),
        ("ouvre chrome", "ouvre   chrome", True),
    )
    for keyword, text, expected in canaries:
        assert selection._keyword_present(keyword, text) is expected
        assert reference_present(keyword, text) is expected
    assert mismatch_count == 0
    assert hit_set_mismatch_count == 0
    assert selection._keyword_present("install*", "installe le logiciel vlc") is True
    assert selection._keyword_present("install*", "instaler le logiciel vlc") is True
    assert selection._keyword_present("install*", "instant présent") is False
    assert selection._keyword_pattern.cache_info().maxsize == 4096
    benchmark_query = "cherche un fichier nommé rapport puis affiche son chemin"
    selection._keyword_pattern.cache_clear()
    selection._keyword_present("warmup", "warmup")
    uncached_ms = scan_cost(uncached_present, benchmark_query)
    scan_cost(selection._keyword_present, benchmark_query, repetitions=1)
    cached_ms = scan_cost(selection._keyword_present, benchmark_query)
    speedup = uncached_ms / cached_ms if cached_ms else float("inf")
    print(
        "Tool Selection Keyword Cache OK - "
        f"queries={len(queries)} private={len(private)} terms={len(terms)} "
        f"mismatches={mismatch_count} hit_set_mismatches={hit_set_mismatch_count} "
        f"uncached_ms={uncached_ms:.3f} cached_ms={cached_ms:.3f} speedup={speedup:.3f}"
    )


if __name__ == "__main__":
    main()
