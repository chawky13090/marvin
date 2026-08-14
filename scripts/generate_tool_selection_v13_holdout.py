"""Génère le holdout indépendant v1.3 sans exposer la correction produit aux rôles Cloud."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tools import TOOLS_SPEC


BASE = ROOT / "benchmarks/tool-selection/v1.3"
POLICY = BASE / "holdout-generation-freeze.json"
CORPUS = BASE / "holdout-corpus.json"
ORACLE = BASE / "holdout-oracle.json"
REPORT = BASE / "holdout-generation-report.json"
OLLAMA = "http://127.0.0.1:11434"
FAMILIES = ("application_launch", "software_management")
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
PERSONAL_PATTERNS = (
    re.compile(r"[A-Z]:\\Users\\", re.IGNORECASE),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:\+33|0)[1-9](?:[ .-]?\d{2}){4}\b"),
)
RELEVANT_NAMES = {
    "windows_task", "pc_app_launch", "pc_open_file", "win_quick_launch",
    "computer_control", "pc_get_real_paths", "tool_search",
    "winget_search", "winget_install", "winget_list_installed",
    "winget_list_upgrades", "winget_upgrade", "winget_uninstall",
    "pc_installed_software", "win_system_report",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _atomic(path: Path, value: Any) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_json(content: str) -> dict[str, Any]:
    value = content.strip()
    if value.startswith("```json") and value.endswith("```"):
        value = value[7:-3].strip()
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Réponse Cloud JSON racine invalide.")
    return parsed


async def _chat(model: str, system: str, user: str, *, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "format": "json",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": 0.15, "top_p": 0.9, "seed": seed, "num_predict": 12288},
    }
    assert "num_ctx" not in payload["options"]
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
                response = await client.post(f"{OLLAMA}/api/chat", json=payload)
                response.raise_for_status()
            body = response.json()
            content = str((body.get("message") or {}).get("content") or "")
            return _parse_json(content), {
                "requested_model": model,
                "observed_model": str(body.get("model") or ""),
                "raw_response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "prompt_eval_count": int(body.get("prompt_eval_count") or 0),
                "eval_count": int(body.get("eval_count") or 0),
                "attempts": attempt,
                "client_num_ctx": None,
            }
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt < 3:
                await asyncio.sleep(float(attempt))
    raise RuntimeError(f"Réponse Cloud JSON indisponible pour {model}.") from last_error


async def _models() -> dict[str, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        response = await client.get(f"{OLLAMA}/api/tags")
        response.raise_for_status()
    return {str(row.get("name") or ""): row for row in response.json().get("models") or []}


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in TOKEN_RE.findall(value) if len(token) > 1}


def _jaccard(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a or b else 1.0


def _reference_prompts() -> list[str]:
    paths = (
        ROOT / "benchmarks/tool-selection/v1.2/holdout-corpus.json",
        ROOT / "benchmarks/windows-operator/v1.1/intent-corpus.json",
        ROOT / "benchmarks/tool-recovery/v1.2/development-corpus.json",
    )
    values: list[str] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("items") or []:
            value = str(row.get("prompt") or row.get("unknown_name") or "").replace("_", " ").strip()
            if value:
                values.append(value)
    return values


def _author_rows(value: dict[str, Any], family: str) -> list[dict[str, str]]:
    rows = value.get("items")
    if not isinstance(rows, list):
        raise ValueError("Auteur sans liste items.")
    result: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("family") or "") != family:
            continue
        prompt = " ".join(str(row.get("prompt") or "").split())
        if not 20 <= len(prompt) <= 500 or any(pattern.search(prompt) for pattern in PERSONAL_PATTERNS):
            continue
        result.append({"family": family, "prompt": prompt})
    if len(result) < 20:
        raise ValueError(f"Auteur insuffisant pour {family}: {len(result)}")
    return result


def _normalize_calls(value: Any, catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[tuple[str, str | None], dict[str, Any]] = {}
    for call in value if isinstance(value, list) else []:
        if not isinstance(call, dict):
            continue
        tool = str(call.get("tool") or "")
        action = call.get("action")
        action = str(action) if action is not None else None
        specification = catalog.get(tool)
        if specification is None:
            continue
        properties = specification["function"].get("parameters", {}).get("properties", {})
        if action is not None and action not in (properties.get("action", {}).get("enum") or []):
            continue
        constraints = []
        for constraint in call.get("constraints") or []:
            if not isinstance(constraint, dict):
                continue
            argument = str(constraint.get("argument") or "")
            operator = str(constraint.get("operator") or "")
            if argument not in properties or operator not in {"present", "equals"}:
                continue
            item = {"argument": argument, "operator": operator}
            if operator == "equals":
                item["value"] = constraint.get("value")
            constraints.append(item)
        output[(tool, action)] = {
            "tool": tool,
            "action": action,
            "constraints": sorted(constraints, key=lambda item: (item["argument"], item["operator"])),
        }
    return sorted(output.values(), key=lambda item: (item["tool"], item["action"] or ""))


def _oracle_rows(value: dict[str, Any], ids: set[str], catalog: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows = value.get("items")
    if not isinstance(rows, list):
        raise ValueError("Oracle sans liste items.")
    output: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        identity = str(row.get("id") or "")
        if identity in ids:
            output[identity] = _normalize_calls(row.get("accepted_calls"), catalog)
    if set(output) != ids:
        raise ValueError("Oracle incomplet.")
    return output


def _consensus(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    a = {(item["tool"], item["action"]): item for item in left}
    b = {(item["tool"], item["action"]): item for item in right}
    result = []
    for key in sorted(set(a) & set(b)):
        left_constraints = {_canonical(item): item for item in a[key]["constraints"]}
        right_constraints = {_canonical(item): item for item in b[key]["constraints"]}
        result.append({
            "tool": key[0],
            "action": key[1],
            "constraints": [left_constraints[item] for item in sorted(set(left_constraints) & set(right_constraints))],
        })
    return result


def _review_rows(value: dict[str, Any], ids: set[str]) -> dict[str, bool]:
    rows = value.get("items")
    if not isinstance(rows, list):
        raise ValueError("Revue sans liste items.")
    output = {
        str(row.get("id") or ""): row.get("valid")
        for row in rows if isinstance(row, dict)
    }
    if set(output) != ids or any(not isinstance(value, bool) for value in output.values()):
        raise ValueError("Revue incomplète.")
    return output


async def run() -> dict[str, Any]:
    if any(path.exists() for path in (CORPUS, ORACLE, REPORT)):
        raise RuntimeError("Artefact v1.3 déjà présent; écrasement interdit.")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy["status"] != "frozen_before_cloud_generation":
        raise RuntimeError("Gel de génération invalide.")
    if _sha256(Path(__file__)) != policy["generator_sha256"]:
        raise RuntimeError("Générateur modifié après gel.")
    models = await _models()
    for role, contract in policy["roles"].items():
        row = models.get(contract["model"])
        if not row or str(row.get("digest") or "") != contract["digest"] or not row.get("remote_host"):
            raise RuntimeError(f"Provenance Cloud invalide: {role}")

    relevant = [item for item in TOOLS_SPEC if str(item["function"]["name"]) in RELEVANT_NAMES]
    catalog = {str(item["function"]["name"]): item for item in relevant}
    catalog_json = json.dumps(relevant, ensure_ascii=False, separators=(",", ":"))
    candidates: list[dict[str, str]] = []
    metadata: dict[str, list[dict[str, Any]]] = {role: [] for role in policy["roles"]}
    family_contracts = {
        "application_launch": (
            "une action simple demandant de lancer une application Windows installée par son nom; exclure les fichiers, "
            "dossiers, URL, panneaux Windows, explications et interactions visuelles multi-étapes"
        ),
        "software_management": (
            "une action simple parmi rechercher un paquet Winget, installer, inventorier les logiciels installés, "
            "lister les mises à jour, mettre à jour ou désinstaller; une seule de ces actions par demande"
        ),
    }
    for family_index, family in enumerate(FAMILIES):
        authored, meta = await _chat(
            policy["roles"]["author"]["model"],
            "Tu écris des demandes de test synthétiques, jamais leur solution. JSON strict sans Markdown.",
            "Retourne {items:[{family,prompt}]}. Produis exactement 30 formulations françaises inédites et variées "
            f"pour family={family}. Contrat: {family_contracts[family]}. Chaque demande est mono-intention, précise, "
            "sans nom d'outil, sans chemin réel, sans personne, sans email et sans donnée privée. Les noms de logiciels "
            "peuvent être des produits publics courants ou des placeholders FixtureApp-A/B/C.",
            seed=26520 + family_index,
        )
        rows = _author_rows(authored, family)[:30]
        for ordinal, row in enumerate(rows, start=1):
            row["id"] = f"v13-{family.replace('_', '-')}-{ordinal:02d}"
        candidates.extend(rows)
        metadata["author"].append({"family": family, **meta})

    ids = {row["id"] for row in candidates}
    oracle_results: dict[str, dict[str, list[dict[str, Any]]]] = {}
    requests = json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
    for role in ("oracle_a", "oracle_b"):
        raw, meta = await _chat(
            policy["roles"][role]["model"],
            "Tu es un oracle fonctionnel indépendant. JSON strict sans Markdown.",
            "Retourne {items:[{id,accepted_calls:[{tool,action,constraints}]}]}. Pour chaque demande, énumère tous "
            "les appels initiaux fonctionnellement recevables, jamais un outil préféré unique. action est la valeur "
            "de l'argument action pour windows_task, sinon null. constraints contient seulement des faits explicites "
            "sous forme {argument,operator:'present'|'equals',value?}. Refuse les noms absents du catalogue. Ne vois "
            "aucun résultat du produit ni du benchmark.\nCATALOGUE:\n" + catalog_json + "\nDEMANDES:\n" + requests,
            seed=26530 if role == "oracle_a" else 26531,
        )
        oracle_results[role] = _oracle_rows(raw, ids, catalog)
        metadata[role].append(meta)

    consensus = {
        identity: _consensus(oracle_results["oracle_a"][identity], oracle_results["oracle_b"][identity])
        for identity in ids
    }
    review_input = [
        {**row, "consensus_calls": consensus[row["id"]]}
        for row in candidates
    ]
    reviews: dict[str, dict[str, bool]] = {}
    for role, seed in (("adjudicator", 26540), ("critic", 26541)):
        raw, meta = await _chat(
            policy["roles"][role]["model"],
            "Tu es un réviseur indépendant. Tu peux seulement accepter ou exclure. JSON strict sans Markdown.",
            "Retourne {items:[{id,valid}]}. valid=true seulement si la demande est mono-intention, appartient exactement "
            "à sa famille, et au moins un consensus_call peut accomplir l'action initiale entière sans supposer une "
            "cible absente. Refuse explication, fichier/URL/panneau confondu avec application, ou recherche/inventaire/"
            "installation/mise à jour/désinstallation confondus. Ne corrige aucun item.\nITEMS:\n"
            + json.dumps(review_input, ensure_ascii=False, separators=(",", ":")),
            seed=seed,
        )
        reviews[role] = _review_rows(raw, ids)
        metadata[role].append(meta)

    references = _reference_prompts()
    maximum_jaccard = float(policy["novelty"]["token_jaccard_maximum"])
    survivors: dict[str, list[dict[str, str]]] = {family: [] for family in FAMILIES}
    oracle_by_id: dict[str, dict[str, Any]] = {}
    excluded: Counter[str] = Counter()
    for row in candidates:
        identity = row["id"]
        if not consensus[identity]:
            excluded["no_oracle_consensus"] += 1
            continue
        if not reviews["adjudicator"][identity] or not reviews["critic"][identity]:
            excluded["review_rejected"] += 1
            continue
        if max((_jaccard(row["prompt"], value) for value in references), default=0.0) > maximum_jaccard:
            excluded["novelty_rejected"] += 1
            continue
        survivors[row["family"]].append(row)
        oracle_by_id[identity] = {"id": identity, "accepted_calls": consensus[identity]}

    selected: list[dict[str, str]] = []
    for family in FAMILIES:
        rows = survivors[family][: int(policy["target_per_family"])]
        if len(rows) != int(policy["target_per_family"]):
            raise RuntimeError(f"Holdout indépendant insuffisant pour {family}: {len(rows)}")
        selected.extend(rows)
    selected_ids = {row["id"] for row in selected}
    corpus_value = {
        "schema": "marvin.tool-selection-v13-holdout/1.0",
        "status": "frozen_candidate",
        "items": selected,
    }
    oracle_value = {
        "schema": "marvin.tool-selection-v13-oracle/1.0",
        "status": "frozen_candidate",
        "items": [oracle_by_id[row["id"]] for row in selected],
    }
    report = {
        "schema": "marvin.tool-selection-v13-generation-report/1.0",
        "status": "complete",
        "policy_sha256": _sha256(POLICY),
        "generator_sha256": _sha256(Path(__file__)),
        "counts": {
            "authored": len(candidates),
            "selected": len(selected),
            "families": dict(Counter(row["family"] for row in selected)),
            "excluded": dict(excluded),
        },
        "models": metadata,
        "privacy": {"synthetic_only": True, "raw_model_responses_published": False, "personal_data_patterns_passed": True},
        "novelty": {"reference_count": len(references), "token_jaccard_maximum": maximum_jaccard},
        "corpus_sha256": hashlib.sha256(json.dumps(corpus_value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n").hexdigest(),
        "oracle_sha256": hashlib.sha256(json.dumps(oracle_value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n").hexdigest(),
        "selected_ids_sha256": hashlib.sha256(_canonical(sorted(selected_ids))).hexdigest(),
        "business_tool_execution_count": 0,
        "host_side_effect_count": 0,
    }
    _atomic(CORPUS, corpus_value)
    _atomic(ORACLE, oracle_value)
    _atomic(REPORT, report)
    return report


def main() -> int:
    report = asyncio.run(run())
    print(json.dumps(report["counts"], ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
