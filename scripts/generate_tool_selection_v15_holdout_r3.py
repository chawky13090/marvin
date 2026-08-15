"""Generate the v1.5 r3 holdout with aggregate, privacy-safe gate observability."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

import generate_tool_selection_v13_holdout as shared
import generate_tool_selection_v15_holdout as historical
from tools import TOOLS_SPEC


BASE = ROOT / "benchmarks/tool-selection/v1.5"
POLICY = BASE / "holdout-generation-freeze-r3.json"
CORPUS = BASE / "holdout-corpus.json"
ORACLE = BASE / "holdout-oracle.json"
REPORT = BASE / "holdout-generation-report.json"
DIAGNOSTIC = BASE / "holdout-generation-diagnostics-r3.json"
INTENTS = historical.INTENTS
RELEVANT = historical.RELEVANT
COUNT_FIELDS = (
    "authored_valid",
    "oracle_a_nonempty",
    "oracle_b_nonempty",
    "consensus_nonempty",
    "adjudicator_valid",
    "critic_valid",
    "both_reviews_valid",
    "novelty_valid",
    "survivors_final",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _empty_counts() -> dict[str, dict[str, int]]:
    return {intent: {field: 0 for field in COUNT_FIELDS} for intent in INTENTS}


def _diagnostic(
    *,
    counts: dict[str, dict[str, int]],
    completed_stages: list[str],
    status: str,
    failure_stage: str | None,
    failure_intent: str | None,
) -> dict[str, Any]:
    if status not in {"complete", "aborted"}:
        raise ValueError("Statut de diagnostic r3 invalide.")
    if status == "aborted" and (not failure_stage or not failure_intent):
        raise ValueError("Un diagnostic interrompu exige un étage et une intention.")
    normalized: dict[str, dict[str, int]] = {}
    for intent in INTENTS:
        source = counts.get(intent, {})
        normalized[intent] = {field: int(source.get(field, 0)) for field in COUNT_FIELDS}
        if any(value < 0 for value in normalized[intent].values()):
            raise ValueError("Un compteur agrégé ne peut pas être négatif.")
    return {
        "schema": "marvin.tool-selection-v15-generation-diagnostics/1.0",
        "status": status,
        "policy_sha256": _sha(POLICY),
        "runner_sha256": _sha(Path(__file__)),
        "completed_stages": list(completed_stages),
        "failure_stage": failure_stage,
        "failure_intent": failure_intent,
        "counts_by_intent": normalized,
        "aggregate_only": True,
        "raw_cloud_responses_persisted": False,
        "prompts_persisted": False,
        "candidate_ids_persisted": False,
        "accepted_calls_persisted": False,
        "per_item_verdicts_persisted": False,
        "personal_data_persisted": False,
        "business_tool_execution_count": 0,
        "host_side_effect_count": 0,
    }


def _write_diagnostic(
    *,
    counts: dict[str, dict[str, int]],
    completed_stages: list[str],
    status: str,
    failure_stage: str | None = None,
    failure_intent: str | None = None,
) -> dict[str, Any]:
    value = _diagnostic(
        counts=counts,
        completed_stages=completed_stages,
        status=status,
        failure_stage=failure_stage,
        failure_intent=failure_intent,
    )
    shared._atomic(DIAGNOSTIC, value)
    return value


def _abort_insufficient(
    intent: str,
    observed: int,
    required: int,
    *,
    counts: dict[str, dict[str, int]],
    completed_stages: list[str],
) -> None:
    _write_diagnostic(
        counts=counts,
        completed_stages=completed_stages,
        status="aborted",
        failure_stage="selection",
        failure_intent=intent,
    )
    raise RuntimeError(f"Holdout r3 insuffisant pour {intent}: {observed}/{required}")


def _author_items(value: dict[str, Any], intent: str) -> list[dict[str, str]]:
    output = []
    for row in value.get("items") if isinstance(value.get("items"), list) else []:
        if not isinstance(row, dict) or str(row.get("intent") or "") != intent:
            continue
        prompt = " ".join(str(row.get("prompt") or "").split())
        if 20 <= len(prompt) <= 400 and not any(
            pattern.search(prompt) for pattern in shared.PERSONAL_PATTERNS
        ):
            output.append({"intent": intent, "prompt": prompt})
    if len(output) < 16:
        raise RuntimeError(f"Auteur r3 insuffisant pour {intent}: {len(output)}")
    return output[:20]


async def run() -> dict[str, Any]:
    if any(path.exists() for path in (CORPUS, ORACLE, REPORT, DIAGNOSTIC)):
        raise RuntimeError("Tentative r3 déjà consommée; aucun artefact ne peut être écrasé.")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if _sha(Path(__file__)) != policy["runner_sha256"]:
        raise RuntimeError("Runner r3 modifié après gel.")
    models = await shared._models()
    for role, contract in policy["roles"].items():
        row = models.get(contract["model"])
        if not row or str(row.get("digest") or "") != contract["digest"] or not row.get("remote_host"):
            raise RuntimeError(f"Provenance Cloud invalide: {role}")

    counts = _empty_counts()
    completed: list[str] = []
    candidates: list[dict[str, str]] = []
    metadata: dict[str, list[dict[str, Any]]] = {role: [] for role in policy["roles"]}
    for index, (intent, contract) in enumerate(INTENTS.items()):
        try:
            raw, meta = await shared._chat(
                policy["roles"]["author"]["model"],
                "Tu écris uniquement des demandes de test synthétiques. JSON strict sans Markdown.",
                "Retourne {items:[{intent,prompt}]}. Produis exactement 20 demandes françaises inédites pour "
                f"intent={intent}. Contrat: {contract}. Une action unique, aucun nom d'outil, aucun chemin réel, "
                "aucune personne ni donnée privée. Varie verbes, ordre des mots, fautes naturelles et noms publics.",
                seed=26820 + index,
            )
            rows = _author_items(raw, intent)
        except Exception:
            _write_diagnostic(
                counts=counts,
                completed_stages=completed,
                status="aborted",
                failure_stage="author",
                failure_intent=intent,
            )
            raise
        for ordinal, row in enumerate(rows, 1):
            row["id"] = f"v15-r3-{intent.replace('.', '-')}-{ordinal:02d}"
        counts[intent]["authored_valid"] = len(rows)
        candidates.extend(rows)
        metadata["author"].append({"intent": intent, **meta})
    completed.append("author")

    relevant = [spec for spec in TOOLS_SPEC if spec["function"]["name"] in RELEVANT]
    catalog = {spec["function"]["name"]: spec for spec in relevant}
    ids = {row["id"] for row in candidates}
    request_json = json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
    catalog_json = json.dumps(relevant, ensure_ascii=False, separators=(",", ":"))
    oracle_results: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for role, seed in (("oracle_a", 26850), ("oracle_b", 26851)):
        try:
            raw, meta = await shared._chat(
                policy["roles"][role]["model"],
                "Tu es un oracle fonctionnel indépendant. JSON strict sans Markdown.",
                "Retourne {items:[{id,accepted_calls:[{tool,action,constraints}]}]}. Accepte tous les appels initiaux "
                "qui accomplissent l'action entière; refuse une étape seulement préparatoire quand un outil terminal "
                "existe. Pour une lecture, refuse toute mutation. action vaut null hors windows_task. constraints ne "
                "contient que des faits explicites. N'invente aucun outil.\nCATALOGUE:\n" + catalog_json
                + "\nDEMANDES:\n" + request_json,
                seed=seed,
            )
            oracle_results[role] = shared._oracle_rows(raw, ids, catalog)
        except Exception:
            _write_diagnostic(
                counts=counts,
                completed_stages=completed,
                status="aborted",
                failure_stage=role,
                failure_intent="all_intents",
            )
            raise
        field = f"{role}_nonempty"
        for row in candidates:
            counts[row["intent"]][field] += int(bool(oracle_results[role][row["id"]]))
        completed.append(role)
        metadata[role].append(meta)

    consensus = {
        identity: shared._consensus(oracle_results["oracle_a"][identity], oracle_results["oracle_b"][identity])
        for identity in ids
    }
    for row in candidates:
        counts[row["intent"]]["consensus_nonempty"] += int(bool(consensus[row["id"]]))
    completed.append("consensus")

    review_input = [{**row, "consensus_calls": consensus[row["id"]]} for row in candidates]
    reviews: dict[str, dict[str, bool]] = {}
    for role, seed in (("adjudicator", 26860), ("critic", 26861)):
        try:
            raw, meta = await shared._chat(
                policy["roles"][role]["model"],
                "Tu révises sans corriger. JSON strict sans Markdown.",
                "Retourne {items:[{id,valid}]}. valid=true seulement si l'intention correspond exactement au texte, "
                "reste mono-action, et le consensus contient un appel terminal sûr. Refuse toute confusion entre "
                "recherche, installation, inventaire, vérification, mise à niveau, désinstallation et panneau.\nITEMS:\n"
                + json.dumps(review_input, ensure_ascii=False, separators=(",", ":")),
                seed=seed,
            )
            reviews[role] = shared._review_rows(raw, ids)
        except Exception:
            _write_diagnostic(
                counts=counts,
                completed_stages=completed,
                status="aborted",
                failure_stage=role,
                failure_intent="all_intents",
            )
            raise
        for row in candidates:
            counts[row["intent"]][f"{role}_valid"] += int(reviews[role][row["id"]])
        completed.append(role)
        metadata[role].append(meta)

    references = historical._references()
    maximum = float(policy["novelty"]["token_jaccard_maximum"])
    survivors = {intent: [] for intent in INTENTS}
    oracle_by_id: dict[str, dict[str, Any]] = {}
    excluded: Counter[str] = Counter()
    for row in candidates:
        identity = row["id"]
        intent = row["intent"]
        both_reviews = reviews["adjudicator"][identity] and reviews["critic"][identity]
        novelty_valid = max(
            (shared._jaccard(row["prompt"], old) for old in references), default=0.0
        ) <= maximum
        counts[intent]["both_reviews_valid"] += int(both_reviews)
        counts[intent]["novelty_valid"] += int(novelty_valid)
        if not consensus[identity]:
            excluded["no_oracle_consensus"] += 1
        elif not both_reviews:
            excluded["review_rejected"] += 1
        elif not novelty_valid:
            excluded["novelty_rejected"] += 1
        else:
            survivors[intent].append(row)
            oracle_by_id[identity] = {"id": identity, "accepted_calls": consensus[identity]}
            counts[intent]["survivors_final"] += 1
    completed.extend(("combined_reviews", "novelty", "selection"))

    selected = []
    required = int(policy["target_per_intent"])
    for intent in INTENTS:
        rows = survivors[intent][:required]
        if len(rows) != required:
            _abort_insufficient(
                intent,
                len(rows),
                required,
                counts=counts,
                completed_stages=completed,
            )
        selected.extend(rows)
    corpus = {"schema": "marvin.tool-selection-v15-holdout/1.0", "status": "frozen_candidate", "items": selected}
    oracle = {
        "schema": "marvin.tool-selection-v15-oracle/1.0",
        "status": "frozen_candidate",
        "items": [oracle_by_id[row["id"]] for row in selected],
    }
    report = {
        "schema": "marvin.tool-selection-v15-generation-report/1.1",
        "status": "complete",
        "policy_sha256": _sha(POLICY),
        "runner_sha256": _sha(Path(__file__)),
        "counts": {
            "authored": len(candidates),
            "selected": len(selected),
            "intents": dict(Counter(row["intent"] for row in selected)),
            "excluded": dict(excluded),
        },
        "corpus_sha256": hashlib.sha256(shared._canonical(corpus)).hexdigest(),
        "oracle_sha256": hashlib.sha256(shared._canonical(oracle)).hexdigest(),
        "role_metadata": metadata,
        "raw_cloud_responses_persisted": False,
        "business_tool_execution_count": 0,
        "host_side_effect_count": 0,
    }
    diagnostic = _write_diagnostic(counts=counts, completed_stages=completed, status="complete")
    report["diagnostic_sha256"] = hashlib.sha256(shared._canonical(diagnostic)).hexdigest()
    shared._atomic(CORPUS, corpus)
    shared._atomic(ORACLE, oracle)
    shared._atomic(REPORT, report)
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run())["counts"], ensure_ascii=False, separators=(",", ":")))
