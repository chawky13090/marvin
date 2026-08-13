"""Génère puis fait labelliser indépendamment le holdout synthétique Stage B."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import dpapi_secret_store
import real_usage_corpus
from tools import TOOLS_SPEC

POLICY = ROOT / "benchmarks/tool-selection/v1.2/stage-b-preregistration.json"
OUTPUT_DIR = ROOT / "benchmarks/tool-selection/v1.2"
CORPUS = OUTPUT_DIR / "holdout-corpus.json"
ORACLE = OUTPUT_DIR / "holdout-oracle.json"
REPORT = OUTPUT_DIR / "holdout-generation-report.json"
OLLAMA = "http://127.0.0.1:11434"
ALLOWED_FAMILIES = (
    "file_discovery", "file_mutation", "application_launch",
    "process_inventory", "process_action", "software_management",
)
TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
FORBIDDEN_PERSONAL = (
    re.compile(r"[A-Z]:\\Users\\(?!Fixture(?:\\|$))", re.IGNORECASE),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:\+33|0)[1-9](?:[ .-]?\d{2}){4}\b"),
    re.compile(r"\\\\[^\\\s]+\\"),
)

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)

def _tokens(text: str) -> set[str]:
    return {item.casefold() for item in TOKEN.findall(text) if len(item) > 1}

def _jaccard(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a or b else 1.0

async def _models() -> dict[str, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        response = await client.get(f"{OLLAMA}/api/tags"); response.raise_for_status()
    return {str(row["name"]): row for row in response.json().get("models") or []}

async def _chat(model: str, system: str, user: str, *, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model": model, "stream": False, "think": False, "format": "json",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": 0.1, "top_p": 0.9, "seed": seed, "num_predict": 12288},
    }
    assert "num_ctx" not in payload["options"]
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        response = await client.post(f"{OLLAMA}/api/chat", json=payload); response.raise_for_status()
    body = response.json()
    content = str((body.get("message") or {}).get("content") or "")
    parsed = json.loads(content)
    return parsed, {
        "requested_model": model, "observed_model": str(body.get("model") or ""),
        "raw_response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "prompt_eval_count": int(body.get("prompt_eval_count") or 0),
        "eval_count": int(body.get("eval_count") or 0), "client_num_ctx": None,
    }

def _old_public_texts() -> list[str]:
    result: list[str] = []
    for path in (
        ROOT / "benchmarks/windows-operator/v1.1/intent-corpus.json",
        ROOT / "benchmarks/tool-recovery/v1.2/development-corpus.json",
    ):
        value = json.loads(path.read_text(encoding="utf-8"))
        for item in value.get("items") or []:
            for key in ("prompt", "unknown_name"):
                if item.get(key): result.append(str(item[key]).replace("_", " "))
    return result

def _private_texts(policy: dict[str, Any]) -> list[str]:
    base = json.loads((ROOT / "benchmarks/tool-selection/v1.0/ablation-preregistration.json").read_text(encoding="utf-8"))
    entry = base["private_inputs"]["text_envelope"]
    path = ROOT / entry["path"]
    if not path.is_file() or _sha256(path) != entry["sha256"]:
        return []
    envelope = json.loads(path.read_text(encoding="utf-8"))
    rows = real_usage_corpus.unprotect_payload(
        envelope,
        unprotect=lambda value, purpose: dpapi_secret_store.unprotect_bytes(value, purpose=purpose),
    )
    return [str(row.get("text") or "") for row in rows if str(row.get("text") or "").strip()]

def _validate_author(items: Any, policy: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(items, list): raise ValueError("Réponse auteur sans liste items.")
    output, ids = [], set()
    for row in items:
        if not isinstance(row, dict): continue
        identity, family, prompt = str(row.get("id") or ""), str(row.get("family") or ""), str(row.get("prompt") or "").strip()
        facts = row.get("argument_facts")
        if not re.fullmatch(r"sb-[a-z0-9-]{5,60}", identity) or identity in ids: continue
        if family not in ALLOWED_FAMILIES or not 20 <= len(prompt) <= 600 or not isinstance(facts, dict): continue
        if any(pattern.search(prompt) for pattern in FORBIDDEN_PERSONAL): continue
        if any(not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None))) for key, value in facts.items()): continue
        ids.add(identity); output.append({"id": identity, "family": family, "prompt": prompt, "argument_facts": facts})
    required = int(policy["holdout"]["minimum_per_family"])
    counts = Counter(row["family"] for row in output)
    if any(counts[family] < required for family in ALLOWED_FAMILIES):
        raise ValueError(f"Réponse auteur insuffisante par famille : {dict(counts)}")
    return output

def _normalize_oracle(value: Any, valid_ids: set[str], catalog: set[str]) -> dict[str, list[dict[str, Any]]]:
    rows = value.get("items") if isinstance(value, dict) else None
    if not isinstance(rows, list): raise ValueError("Oracle sans liste items.")
    output: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or str(row.get("id") or "") not in valid_ids: continue
        accepted: dict[tuple[str, str | None], dict[str, Any]] = {}
        for call in row.get("accepted_calls") or []:
            if not isinstance(call, dict): continue
            tool = str(call.get("tool") or "")
            action = call.get("action")
            action = str(action) if action is not None else None
            if tool not in catalog: continue
            constraints = []
            for constraint in call.get("constraints") or []:
                if not isinstance(constraint, dict): continue
                argument = str(constraint.get("argument") or "")
                operator = str(constraint.get("operator") or "")
                if argument and operator in {"equals", "present"}:
                    item = {"argument": argument, "operator": operator}
                    if operator == "equals": item["value"] = constraint.get("value")
                    constraints.append(item)
            accepted[(tool, action)] = {"tool": tool, "action": action, "constraints": sorted(constraints, key=lambda item: (item["argument"], item["operator"], json.dumps(item.get("value"), sort_keys=True)))}
        output[str(row["id"])] = sorted(accepted.values(), key=lambda item: (item["tool"], item["action"] or ""))
    if set(output) != valid_ids: raise ValueError("Oracle incomplet ou identifiants inattendus.")
    return output

def _consensus(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_left = {(item["tool"], item["action"]): item for item in left}
    by_right = {(item["tool"], item["action"]): item for item in right}
    result = []
    for key in sorted(set(by_left) & set(by_right)):
        left_constraints = {_canonical(item): item for item in by_left[key]["constraints"]}
        right_constraints = {_canonical(item): item for item in by_right[key]["constraints"]}
        result.append({"tool": key[0], "action": key[1], "constraints": [left_constraints[item] for item in sorted(set(left_constraints) & set(right_constraints))]})
    return result

async def run() -> dict[str, Any]:
    if any(path.exists() for path in (CORPUS, ORACLE, REPORT)):
        raise RuntimeError("Artefact Stage B déjà présent; écrasement interdit.")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy["status"] != "frozen_before_holdout_generation": raise RuntimeError("Politique Stage B non gelée.")
    models = await _models()
    for role in ("author", "oracle_a", "oracle_b", "benchmark"):
        expected = policy["independent_roles"][role]
        observed = models.get(expected["model"])
        if not observed or str(observed.get("digest") or "") != expected["digest"] or not observed.get("remote_host"):
            raise RuntimeError(f"Provenance Cloud invalide pour {role}.")

    catalog_json = json.dumps(TOOLS_SPEC, ensure_ascii=False, separators=(",", ":"))
    family_counts = {name: 8 for name in ALLOWED_FAMILIES}
    author_user = (
        "Crée un corpus inédit de demandes Windows en français. Retourne un objet JSON {items:[...]}. "
        f"Produis exactement {family_counts}. Chaque item contient id, family, prompt, argument_facts. "
        "Le prompt doit être naturel, mono-intention, synthétique et précis. Utilise uniquement des fixtures "
        "sous C:\\Fixture, des processus marvin_fixture_*.exe, des applications Windows génériques et des "
        "logiciels publics connus. argument_facts contient seulement les valeurs explicitement demandées. "
        "N'indique jamais le nom d'un outil dans le prompt. Ne fournis aucun oracle. Familles: "
        "file_discovery=chercher/lister par nom ou contenu; file_mutation=renommer/déplacer/copier/créer; "
        "application_launch=lancer une application; process_inventory=lister/inspecter les processus; "
        "process_action=arrêter une cible explicite; software_management=rechercher/lister/installer/désinstaller. "
        "Catalogue de référence (descriptions et schémas seulement):\n" + catalog_json
    )
    authored, author_meta = await _chat(policy["independent_roles"]["author"]["model"], "Tu rédiges des cas de test, jamais leurs réponses. JSON strict, sans Markdown.", author_user, seed=2651)
    candidates = _validate_author(authored.get("items") if isinstance(authored, dict) else None, policy)

    oracle_user = (
        "Établis indépendamment l'oracle de routage. Retourne {items:[{id,accepted_calls:[...]}]}. "
        "Pour chaque demande, énumère TOUS les outils réellement valides, jamais un outil préféré unique. "
        "Chaque appel contient tool, action (valeur de l'argument action pour windows_task, sinon null), et "
        "constraints [{argument,operator:'equals'|'present',value?}] uniquement pour les faits explicitement "
        "imposés. Refuse tout nom absent du catalogue. Ne déduis rien d'un résultat de benchmark.\nCATALOGUE:\n"
        + catalog_json + "\nDEMANDES:\n" + json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
    )
    oracle_values, oracle_meta = {}, {}
    for index, role in enumerate(("oracle_a", "oracle_b"), start=1):
        raw, meta = await _chat(policy["independent_roles"][role]["model"], "Tu es un oracle fonctionnel indépendant. JSON strict, sans Markdown.", oracle_user, seed=2651 + index)
        oracle_values[role] = _normalize_oracle(raw, {row["id"] for row in candidates}, {str(item["function"]["name"]) for item in TOOLS_SPEC})
        oracle_meta[role] = meta

    old_public, private = _old_public_texts(), _private_texts(policy)
    maximum = float(policy["holdout"]["novelty"]["token_jaccard_maximum"])
    selected, oracle_rows, excluded = [], [], Counter()
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        accepted = _consensus(oracle_values["oracle_a"][row["id"]], oracle_values["oracle_b"][row["id"]])
        if not accepted: excluded["oracle_no_consensus"] += 1; continue
        max_public = max((_jaccard(row["prompt"], text) for text in old_public), default=0.0)
        max_private = max((_jaccard(row["prompt"], text) for text in private), default=0.0)
        if max(max_public, max_private) > maximum: excluded["novelty"] += 1; continue
        clean = {"id": row["id"], "family": row["family"], "prompt": row["prompt"]}
        by_family[row["family"]].append(clean)
        oracle_rows.append({"id": row["id"], "accepted_calls": accepted})
    target_oracle = {row["id"]: row for row in oracle_rows}
    for family in ALLOWED_FAMILIES:
        family_rows = by_family[family][: int(policy["holdout"]["families"][family])]
        if len(family_rows) != int(policy["holdout"]["families"][family]):
            raise RuntimeError(f"Holdout insuffisant après consensus pour {family}.")
        selected.extend(family_rows)
    selected_ids = {row["id"] for row in selected}
    oracle_final = [target_oracle[row["id"]] for row in selected]
    corpus_value = {"schema": "marvin.tool-selection-stage-b-holdout/1.0", "status": "frozen_candidate", "items": selected}
    oracle_value = {"schema": "marvin.tool-selection-stage-b-oracle/1.0", "status": "frozen_candidate", "items": oracle_final}
    report = {
        "schema": "marvin.tool-selection-stage-b-generation-report/1.0", "status": "complete",
        "policy_sha256": _sha256(POLICY), "generator_sha256": _sha256(Path(__file__)),
        "models": {"author": author_meta, **oracle_meta},
        "counts": {"authored": len(candidates), "selected": len(selected), "excluded": dict(excluded), "families": dict(Counter(row["family"] for row in selected))},
        "novelty": {"public_reference_count": len(old_public), "private_reference_count": len(private), "maximum_token_jaccard": maximum, "private_details_published": False},
        "privacy": {"synthetic_only": True, "raw_model_responses_published": False, "personal_data_patterns_passed": True},
        "corpus_sha256": hashlib.sha256((json.dumps(corpus_value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")).hexdigest(),
        "oracle_sha256": hashlib.sha256((json.dumps(oracle_value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")).hexdigest(),
    }
    _atomic(CORPUS, corpus_value); _atomic(ORACLE, oracle_value); _atomic(REPORT, report)
    return report

def main() -> int:
    report = asyncio.run(run())
    print(json.dumps(report["counts"], ensure_ascii=False, separators=(",", ":")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
