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
ADJUDICATOR_POLICY = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.3.json"
CRITIC_POLICY = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.6.json"
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
RELEVANT_PREFIXES = ("file_", "system_search", "pc_app_", "win_quick_", "pc_process_", "winget_")
RELEVANT_EXACT = {"unified_search", "pc_open_file", "pc_installed_software", "windows_task", "computer_control"}

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
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
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
                "attempts": attempt,
            }
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, TypeError) as exc:
            last_error = exc
            if attempt < 3:
                await asyncio.sleep(float(attempt))
    raise RuntimeError(f"Réponse Cloud JSON indisponible après trois tentatives : {model}") from last_error

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
    output = []
    family_ordinals: Counter[str] = Counter()
    for row in items:
        if not isinstance(row, dict): continue
        family, prompt = str(row.get("family") or ""), str(row.get("prompt") or "").strip()
        if family not in ALLOWED_FAMILIES or not 20 <= len(prompt) <= 600: continue
        if any(pattern.search(prompt) for pattern in FORBIDDEN_PERSONAL): continue
        family_ordinals[family] += 1
        identity = f"sb-{family.replace('_', '-')}-{family_ordinals[family]:02d}"
        output.append({"id": identity, "family": family, "prompt": prompt})
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

def _adjudications(value: Any, valid_ids: set[str]) -> dict[str, bool]:
    rows = value.get("items") if isinstance(value, dict) else None
    if not isinstance(rows, list): raise ValueError("Adjudication sans liste items.")
    observed: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict): continue
        identity = str(row.get("id") or "")
        valid = row.get("valid")
        if identity in valid_ids and isinstance(valid, bool):
            observed[identity].append(valid)
    return {
        identity: observed.get(identity) == [True]
        for identity in valid_ids
    }

def _schema_valid_calls(calls: list[dict[str, Any]], catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for call in calls:
        specification = catalog.get(call["tool"])
        if not specification: continue
        schema = specification.get("function", {}).get("parameters") or {}
        properties = schema.get("properties") or {}
        action = call.get("action")
        if action is not None:
            action_schema = properties.get("action") or {}
            if action not in (action_schema.get("enum") or []): continue
        valid = True
        for constraint in call.get("constraints") or []:
            field = properties.get(constraint["argument"])
            if not isinstance(field, dict): valid = False; break
            if constraint["operator"] == "equals":
                value, expected = constraint.get("value"), field.get("type")
                type_ok = (
                    (expected == "string" and isinstance(value, str))
                    or (expected == "integer" and isinstance(value, int) and not isinstance(value, bool))
                    or (expected == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
                    or (expected == "boolean" and isinstance(value, bool))
                    or expected not in {"string", "integer", "number", "boolean"}
                )
                if not type_ok or (field.get("enum") and value not in field["enum"]): valid = False; break
        if valid: output.append(call)
    return output

async def run() -> dict[str, Any]:
    if any(path.exists() for path in (CORPUS, ORACLE, REPORT)):
        raise RuntimeError("Artefact Stage B déjà présent; écrasement interdit.")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    adjudicator_policy = json.loads(ADJUDICATOR_POLICY.read_text(encoding="utf-8"))
    critic_policy = json.loads(CRITIC_POLICY.read_text(encoding="utf-8"))
    if policy["status"] != "frozen_before_holdout_generation": raise RuntimeError("Politique Stage B non gelée.")
    models = await _models()
    for role in ("author", "oracle_a", "oracle_b", "benchmark"):
        expected = policy["independent_roles"][role]
        observed = models.get(expected["model"])
        if not observed or str(observed.get("digest") or "") != expected["digest"] or not observed.get("remote_host"):
            raise RuntimeError(f"Provenance Cloud invalide pour {role}.")
    adjudicator_contract = adjudicator_policy["authorized_change"]
    adjudicator_model = str(adjudicator_contract["adjudicator_model"])
    adjudicator_row = models.get(adjudicator_model)
    if not adjudicator_row or str(adjudicator_row.get("digest") or "") != adjudicator_contract["adjudicator_digest"] or not adjudicator_row.get("remote_host"):
        raise RuntimeError("Provenance Cloud invalide pour l'adjudicateur.")
    critic_contract = critic_policy["authorized_change"]
    critic_model = str(critic_contract["critic_model"])
    critic_row = models.get(critic_model)
    if not critic_row or str(critic_row.get("digest") or "") != critic_contract["critic_digest"] or not critic_row.get("remote_host"):
        raise RuntimeError("Provenance Cloud invalide pour le critique.")

    relevant_spec = [
        item for item in TOOLS_SPEC
        if str(item["function"]["name"]) in RELEVANT_EXACT
        or str(item["function"]["name"]).startswith(RELEVANT_PREFIXES)
    ]
    catalog_json = json.dumps(relevant_spec, ensure_ascii=False, separators=(",", ":"))
    family_counts = {name: 8 for name in ALLOWED_FAMILIES}
    author_user = (
        "Crée un corpus inédit de demandes Windows en français. Retourne un objet JSON {items:[...]}. "
        f"Produis exactement {family_counts}. Chaque item contient seulement id, family et prompt. "
        "Le prompt doit être naturel, mono-intention, synthétique et précis. Utilise uniquement des fixtures "
        "sous C:\\Fixture, des processus marvin_fixture_*.exe, des applications Windows génériques et des "
        "logiciels publics connus. "
        "N'indique jamais le nom d'un outil dans le prompt. Ne fournis aucun oracle. Familles: "
        "file_discovery=chercher/lister par nom ou contenu; file_mutation=renommer/déplacer/copier/créer; "
        "application_launch=lancer une application; process_inventory=lister/inspecter les processus; "
        "process_action=arrêter une cible explicite; software_management=rechercher/lister/installer/désinstaller."
    )
    authored, author_meta = await _chat(policy["independent_roles"]["author"]["model"], "Tu rédiges des cas de test, jamais leurs réponses. JSON strict, sans Markdown.", author_user, seed=2651)
    candidates = _validate_author(authored.get("items") if isinstance(authored, dict) else None, policy)

    oracle_values = {"oracle_a": {}, "oracle_b": {}}
    oracle_meta = {"oracle_a": [], "oracle_b": []}
    for index, role in enumerate(("oracle_a", "oracle_b"), start=1):
        for family_index, family in enumerate(ALLOWED_FAMILIES):
            batch = [row for row in candidates if row["family"] == family]
            batch_ids = {row["id"] for row in batch}
            oracle_user = (
                "Établis indépendamment l'oracle de routage. Retourne {items:[{id,accepted_calls:[...]}]}. "
                "Pour chaque demande, énumère TOUS les outils réellement valides, jamais un outil préféré unique. "
                "Chaque appel contient tool, action (valeur de l'argument action pour windows_task, sinon null), et "
                "constraints [{argument,operator:'equals'|'present',value?}] uniquement pour les faits explicitement "
                "imposés. Refuse tout nom absent du catalogue. Ne déduis rien d'un résultat de benchmark.\nCATALOGUE:\n"
                + catalog_json + "\nDEMANDES:\n" + json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
            )
            raw, meta = await _chat(policy["independent_roles"][role]["model"], "Tu es un oracle fonctionnel indépendant. JSON strict, sans Markdown.", oracle_user, seed=2651 + index)
            oracle_values[role].update(_normalize_oracle(raw, batch_ids, {str(item["function"]["name"]) for item in relevant_spec}))
            oracle_meta[role].append({"family": family, **meta})

    catalog_by_name = {str(item["function"]["name"]): item for item in TOOLS_SPEC}
    consensus_by_id = {
        row["id"]: _schema_valid_calls(_consensus(
            oracle_values["oracle_a"][row["id"]],
            oracle_values["oracle_b"][row["id"]],
        ), catalog_by_name)
        for row in candidates
    }
    review_input = [
        {"id": row["id"], "family": row["family"], "prompt": row["prompt"], "consensus_calls": consensus_by_id[row["id"]]}
        for row in candidates
    ]
    adjudicated: dict[str, bool] = {}
    criticized: dict[str, bool] = {}
    adjudicator_meta: list[dict[str, Any]] = []
    critic_meta: list[dict[str, Any]] = []
    for family_index, family in enumerate(ALLOWED_FAMILIES):
        batch = [row for row in review_input if row["family"] == family]
        batch_ids = {row["id"] for row in batch}
        adjudicator_raw, meta = await _chat(
            adjudicator_model,
            "Tu es un adjudicateur indépendant. Tu peux seulement accepter ou exclure; JSON strict, sans Markdown.",
            "Retourne {items:[{id,valid}]}, exactement une décision par item. valid=true uniquement si le texte "
            "implique réellement la famille déclarée ET si au moins un consensus_call accomplit précisément la "
            "demande avec ses contraintes. Une ambiguïté ou une action relevant d'une autre famille impose false. "
            "Ne corrige et ne réécris jamais un item. Catalogue de référence:\n" + catalog_json
            + "\nITEMS:\n" + json.dumps(batch, ensure_ascii=False, separators=(",", ":")),
            seed=2654,
        )
        adjudicated.update(_adjudications(adjudicator_raw, batch_ids))
        adjudicator_meta.append({"family": family, **meta})
        critic_raw, meta = await _chat(
            critic_model,
            "Tu es un critique adversarial indépendant. Tu peux seulement accepter ou exclure; JSON strict, sans Markdown.",
            "Retourne {items:[{id,valid}]}, exactement une décision par item. Cherche les faux positifs: outil qui "
            "n'accomplit qu'une partie de la demande, différence nom/contenu, direct/récursif, application/fichier, "
            "processus/service, installé/disponible, lecture/mutation. valid=true seulement si au moins un "
            "consensus_call couvre la demande entière avec le schéma fourni. Ne corrige rien. Catalogue:\n"
            + catalog_json + "\nITEMS:\n" + json.dumps(batch, ensure_ascii=False, separators=(",", ":")),
            seed=2655,
        )
        criticized.update(_adjudications(critic_raw, batch_ids))
        critic_meta.append({"family": family, **meta})

    old_public, private = _old_public_texts(), _private_texts(policy)
    maximum = float(policy["holdout"]["novelty"]["token_jaccard_maximum"])
    selected, oracle_rows, excluded = [], [], Counter()
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        accepted = consensus_by_id[row["id"]]
        if not accepted: excluded["oracle_no_consensus"] += 1; continue
        if not adjudicated[row["id"]]: excluded["adjudicator_rejected"] += 1; continue
        if not criticized[row["id"]]: excluded["critic_rejected"] += 1; continue
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
        "models": {"author": author_meta, **oracle_meta, "adjudicator": adjudicator_meta, "critic": critic_meta},
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
