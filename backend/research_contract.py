"""Contrat déterministe des recherches Web de Marvin.

Le contrat sépare l'intention utilisateur de l'orchestration LLM. Il borne
explicitement le temps, les requêtes, les pages et les domaines afin qu'une
recherche reste explicable, testable et annulable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Literal
from urllib.parse import urlparse


Depth = Literal["quick", "deep", "exhaustive"]
_DEPTH_ALIASES = {
    "quick": "quick",
    "rapide": "quick",
    "standard": "deep",
    "deep": "deep",
    "approfondi": "deep",
    "approfondie": "deep",
    "exhaustive": "exhaustive",
    "exhaustif": "exhaustive",
    "exhaustive": "exhaustive",
}
_BUDGETS = {
    "quick": {"max_queries": 6, "max_pages": 18, "max_rounds": 2, "max_seconds": 180},
    "deep": {"max_queries": 18, "max_pages": 60, "max_rounds": 6, "max_seconds": 900},
    "exhaustive": {"max_queries": 36, "max_pages": 120, "max_rounds": 10, "max_seconds": 1800},
}
_DOMAIN_RE = re.compile(
    r"^(?:[a-z][a-z0-9+.-]*://)?([a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?)$",
    re.IGNORECASE,
)


def _bounded_text(value: object, *, maximum: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        raise ValueError("La question de recherche est requise.")
    if len(text) > maximum:
        raise ValueError(f"Texte limité à {maximum} caractères.")
    return text


def _domains(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple, set)):
        raise ValueError("Les domaines doivent être fournis sous forme de liste.")
    normalized: list[str] = []
    for raw in values:
        candidate = str(raw or "").strip().lower().rstrip("/")
        match = _DOMAIN_RE.fullmatch(candidate)
        if not match:
            raise ValueError(f"Domaine invalide : {candidate[:120]}")
        host = urlparse(candidate if "://" in candidate else f"https://{candidate}").hostname
        if not host:
            raise ValueError(f"Domaine invalide : {candidate[:120]}")
        host = host.encode("idna").decode("ascii")
        if host not in normalized:
            normalized.append(host)
        if len(normalized) > 50:
            raise ValueError("Une politique de recherche est limitée à 50 domaines.")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class ResearchBudget:
    max_queries: int
    max_pages: int
    max_rounds: int
    max_seconds: int


@dataclass(frozen=True, slots=True)
class ResearchContract:
    question: str
    depth: Depth
    language: str
    region: str
    freshness: str | None
    source_policy: str
    preferred_domains: tuple[str, ...] = ()
    excluded_domains: tuple[str, ...] = ()
    deliverable: str = "report"
    budget: ResearchBudget = field(
        default_factory=lambda: ResearchBudget(**_BUDGETS["deep"])
    )
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_depth(question: str, requested: object = None) -> Depth:
    explicit = str(requested or "").strip().casefold()
    if explicit:
        try:
            return _DEPTH_ALIASES[explicit]  # type: ignore[return-value]
        except KeyError as exc:
            raise ValueError("Profondeur invalide : quick, deep ou exhaustive attendue.") from exc
    folded = question.casefold()
    if any(word in folded for word in ("exhaustif", "exhaustive", "étude complète", "toutes les sources")):
        return "exhaustive"
    if any(word in folded for word in ("approfond", "enquête", "compare en détail", "état de l'art")):
        return "deep"
    return "quick"


def build_contract(question: object, options: dict[str, Any] | None = None) -> ResearchContract:
    options = dict(options or {})
    normalized_question = _bounded_text(question, maximum=12_000)
    depth = infer_depth(normalized_question, options.get("depth"))
    defaults = dict(_BUDGETS[depth])
    for key, floor in (
        ("max_queries", 1),
        ("max_pages", 1),
        ("max_rounds", 1),
        ("max_seconds", 30),
    ):
        if options.get(key) is not None:
            value = int(options[key])
            ceiling = _BUDGETS["exhaustive"][key]
            if not floor <= value <= ceiling:
                raise ValueError(f"{key} doit être compris entre {floor} et {ceiling}.")
            defaults[key] = value
    preferred = _domains(options.get("preferred_domains"))
    excluded = _domains(options.get("excluded_domains"))
    overlap = sorted(set(preferred) & set(excluded))
    if overlap:
        raise ValueError(f"Un domaine ne peut pas être préféré et exclu : {overlap[0]}")
    language = str(options.get("language") or "fr-FR").strip()
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?", language):
        raise ValueError("Langue invalide.")
    region = str(options.get("region") or "FR").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        raise ValueError("Région invalide.")
    freshness = str(options.get("freshness") or "").strip().lower() or None
    if freshness not in {None, "day", "week", "month", "year"}:
        raise ValueError("Fraîcheur invalide : day, week, month ou year attendue.")
    policy = str(options.get("source_policy") or "balanced").strip().lower()
    if policy not in {"balanced", "primary_first", "academic", "official_only"}:
        raise ValueError("Politique de sources invalide.")
    deliverable = str(options.get("deliverable") or "report").strip().lower()
    if deliverable not in {"answer", "report", "comparison", "brief"}:
        raise ValueError("Type de livrable invalide.")
    return ResearchContract(
        question=normalized_question,
        depth=depth,
        language=language,
        region=region,
        freshness=freshness,
        source_policy=policy,
        preferred_domains=preferred,
        excluded_domains=excluded,
        deliverable=deliverable,
        budget=ResearchBudget(**defaults),
    )


def initial_query_portfolio(contract: ResearchContract) -> list[dict[str, str]]:
    """Produit des angles complémentaires, sans dépendre d'un LLM."""
    question = contract.question
    today = datetime.now(timezone.utc).date().isoformat()
    rows = [
        ("discovery", question),
        ("primary", f"{question} documentation officielle source primaire"),
        ("counterevidence", f"{question} limites échecs critiques contradictions"),
        ("freshness", f"{question} mise à jour {today} version actuelle"),
        ("implementation", f"{question} pratiques production retour expérience"),
        ("verification", f"{question} données preuves méthodologie"),
    ]
    if contract.preferred_domains:
        target = contract.preferred_domains[0]
        rows[1] = ("primary", f"site:{target} {question}")
        if contract.source_policy == "official_only":
            rows = [
                (axis, f"site:{target} {query}")
                for axis, query in rows
            ]
    if contract.source_policy == "academic":
        rows[1] = ("primary", f"{question} étude publication DOI arXiv")
    elif contract.source_policy == "official_only":
        rows = [row for row in rows if row[0] in {"discovery", "primary", "freshness", "verification"}]
    return [
        {"id": f"query-{index}", "axis": axis, "query": query[:500]}
        for index, (axis, query) in enumerate(rows[: contract.budget.max_queries], start=1)
    ]
