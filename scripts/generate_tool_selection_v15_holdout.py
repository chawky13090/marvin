"""Generate the independent v1.5 software-action holdout through separate Cloud roles."""

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
from tools import TOOLS_SPEC


BASE = ROOT / "benchmarks/tool-selection/v1.5"
POLICY = BASE / "holdout-generation-freeze.json"
CORPUS = BASE / "holdout-corpus.json"
ORACLE = BASE / "holdout-oracle.json"
REPORT = BASE / "holdout-generation-report.json"
INTENTS = {
    "software.search": "rechercher un paquet installable sans installer ni modifier le poste",
    "software.install": "installer réellement un logiciel Windows nommé ou décrit",
    "software.inventory": "inventorier ou vérifier les logiciels déjà installés sans mutation",
    "software.updates_check": "lister les mises à jour disponibles sans les appliquer",
    "software.upgrade": "appliquer réellement la mise à jour d'un logiciel",
    "software.uninstall": "désinstaller réellement un logiciel",
    "software.manual_panel": "ouvrir explicitement le panneau Windows Programmes et fonctionnalités",
}
RELEVANT = {
    "winget_search", "winget_install", "winget_list_installed", "pc_installed_software",
    "winget_list_upgrades", "winget_upgrade", "winget_uninstall", "win_quick_launch",
    "win_quick_launch_list", "windows_task", "pc_app_launch", "tool_search",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _references() -> list[str]:
    paths = [
        ROOT / "benchmarks/tool-selection/v1.2/holdout-corpus.json",
        ROOT / "benchmarks/tool-selection/v1.3/holdout-corpus.json",
        ROOT / "benchmarks/tool-selection/v1.4/holdout-corpus.json",
        ROOT / "benchmarks/tool-selection/v1.5/development-corpus.json",
    ]
    values: list[str] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        values.extend(str(row.get("prompt") or "") for row in payload.get("items", []))
    return values


def _author_items(value: dict[str, Any], intent: str) -> list[dict[str, str]]:
    output = []
    for row in value.get("items") if isinstance(value.get("items"), list) else []:
        if not isinstance(row, dict) or str(row.get("intent") or "") != intent:
            continue
        prompt = " ".join(str(row.get("prompt") or "").split())
        if 20 <= len(prompt) <= 400 and not any(pattern.search(prompt) for pattern in shared.PERSONAL_PATTERNS):
            output.append({"intent": intent, "prompt": prompt})
    if len(output) < 10:
        raise RuntimeError(f"Auteur insuffisant pour {intent}: {len(output)}")
    return output[:12]


async def run() -> dict[str, Any]:
    if CORPUS.exists() or ORACLE.exists() or REPORT.exists():
        raise RuntimeError("Holdout v1.5 déjà généré; autorisation à usage unique consommée.")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if _sha(Path(__file__)) != policy["generator_sha256"]:
        raise RuntimeError("Générateur v1.5 modifié après gel.")
    models = await shared._models()
    for role, contract in policy["roles"].items():
        row = models.get(contract["model"])
        if not row or str(row.get("digest") or "") != contract["digest"] or not row.get("remote_host"):
            raise RuntimeError(f"Provenance Cloud invalide: {role}")

    candidates: list[dict[str, str]] = []
    metadata: dict[str, list[dict[str, Any]]] = {role: [] for role in policy["roles"]}
    for index, (intent, contract) in enumerate(INTENTS.items()):
        raw, meta = await shared._chat(
            policy["roles"]["author"]["model"],
            "Tu écris uniquement des demandes de test synthétiques. JSON strict sans Markdown.",
            "Retourne {items:[{intent,prompt}]}. Produis exactement 12 demandes françaises inédites pour "
            f"intent={intent}. Contrat: {contract}. Une action unique, aucun nom d'outil, aucun chemin réel, "
            "aucune personne ni donnée privée. Varie verbes, ordre des mots, fautes naturelles et noms publics.",
            seed=26620 + index,
        )
        rows = _author_items(raw, intent)
        for ordinal, row in enumerate(rows, 1):
            row["id"] = f"v15-{intent.replace('.', '-')}-{ordinal:02d}"
        candidates.extend(rows)
        metadata["author"].append({"intent": intent, **meta})

    relevant = [spec for spec in TOOLS_SPEC if spec["function"]["name"] in RELEVANT]
    catalog = {spec["function"]["name"]: spec for spec in relevant}
    ids = {row["id"] for row in candidates}
    request_json = json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
    catalog_json = json.dumps(relevant, ensure_ascii=False, separators=(",", ":"))
    oracle_results = {}
    for role, seed in (("oracle_a", 26650), ("oracle_b", 26651)):
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
        metadata[role].append(meta)

    consensus = {
        identity: shared._consensus(oracle_results["oracle_a"][identity], oracle_results["oracle_b"][identity])
        for identity in ids
    }
    review_input = [{**row, "consensus_calls": consensus[row["id"]]} for row in candidates]
    reviews = {}
    for role, seed in (("adjudicator", 26660), ("critic", 26661)):
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
        metadata[role].append(meta)

    references = _references()
    maximum = float(policy["novelty"]["token_jaccard_maximum"])
    survivors = {intent: [] for intent in INTENTS}
    oracle_by_id = {}
    excluded: Counter[str] = Counter()
    for row in candidates:
        identity = row["id"]
        if not consensus[identity]:
            excluded["no_oracle_consensus"] += 1
        elif not reviews["adjudicator"][identity] or not reviews["critic"][identity]:
            excluded["review_rejected"] += 1
        elif max((shared._jaccard(row["prompt"], old) for old in references), default=0.0) > maximum:
            excluded["novelty_rejected"] += 1
        else:
            survivors[row["intent"]].append(row)
            oracle_by_id[identity] = {"id": identity, "accepted_calls": consensus[identity]}

    selected = []
    for intent in INTENTS:
        rows = survivors[intent][: int(policy["target_per_intent"])]
        if len(rows) != int(policy["target_per_intent"]):
            raise RuntimeError(f"Holdout insuffisant pour {intent}: {len(rows)}")
        selected.extend(rows)
    corpus = {"schema":"marvin.tool-selection-v15-holdout/1.0","status":"frozen_candidate","items":selected}
    oracle = {"schema":"marvin.tool-selection-v15-oracle/1.0","status":"frozen_candidate","items":[oracle_by_id[row["id"]] for row in selected]}
    report = {
        "schema":"marvin.tool-selection-v15-generation-report/1.0", "status":"complete",
        "policy_sha256":_sha(POLICY), "generator_sha256":_sha(Path(__file__)),
        "counts":{"authored":len(candidates),"selected":len(selected),"intents":dict(Counter(row["intent"] for row in selected)),"excluded":dict(excluded)},
        "corpus_sha256":hashlib.sha256(shared._canonical(corpus)).hexdigest(),
        "oracle_sha256":hashlib.sha256(shared._canonical(oracle)).hexdigest(),
        "role_metadata":metadata, "raw_cloud_responses_persisted":False,
        "business_tool_execution_count":0, "host_side_effect_count":0,
    }
    shared._atomic(CORPUS, corpus); shared._atomic(ORACLE, oracle); shared._atomic(REPORT, report)
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run())["counts"], ensure_ascii=False, separators=(",", ":")))
