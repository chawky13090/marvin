"""Compute aggregate software-intent coverage from persisted user text only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.6/measurement-strategy-preregistration.json"
DATABASE = ROOT / "data/secretary.db"
OUTPUT = ROOT / "benchmarks/tool-selection/v1.6/retrospective-coverage.json"
FAMILIES = (
    "software.search",
    "software.install",
    "software.inventory",
    "software.updates_check",
    "software.upgrade",
    "software.uninstall",
    "software.manual_panel",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = "".join(char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn")
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def classify(text: str, *, conversation_title: str = "") -> tuple[str | None, str]:
    raw = str(text or "").strip()
    value = normalize(raw)
    title = normalize(conversation_title)
    if not value:
        return None, "empty"
    if raw.casefold().startswith("[reprise automatique"):
        return None, "automatic_long_task_resume"
    if "forge benchmark ephemere" in title:
        return None, "benchmark_ephemeral_conversation"
    if re.search(r"\b(comment|comment faire|quel(?:le)? est la commande|quelles? commandes)\b", value):
        return None, "how_to_or_command_question"
    if re.search(r"\b(script|procedure|documentation|guide)\b", value) and re.search(r"\binstal\w*\b", value):
        return None, "script_or_document_generation"
    if re.search(r"\b(j ai|jai|nous avons|on a) instal\w*\b", value):
        if re.search(r"\b(retrouve|trouve|cherche|localise)\b", value):
            return None, "software_search_for_an_already_installed_application"
        return None, "statement_about_already_completed_action"
    if re.search(r"\b(je confirme|c est bien|cela est bien|ca a bien)\b.{0,80}\binstal\w*\b", value):
        return None, "success_confirmation"

    if any(marker in value for marker in (
        "programmes et fonctionnalites", "panneau de desinstallation",
        "applications et fonctionnalites", "ouvre appwiz", "ouvrir appwiz",
    )):
        return "software.manual_panel", "direct_action"
    if re.search(r"\bdesinstal\w*\b", value) or re.search(r"\b(uninstall|retire|supprime)\b.{0,64}\b(logiciel|application|programme)\b", value):
        return "software.uninstall", "direct_action"

    update_subject = bool(re.search(r"\b(mises? a jour|versions? obsoletes?|logiciels? obsoletes?|upgrades?)\b", value))
    read_signal = bool(re.search(r"\b(liste|affiche|verifie|quels?|quelles?|disponibles?)\b", value))
    if update_subject and read_signal:
        return "software.updates_check", "direct_action"
    if re.search(r"\b(mets?|mettre|applique|actualise)\b.{0,64}\b(a jour|mises? a jour|logiciel)\b", value):
        return "software.upgrade", "direct_action"
    if re.search(r"\b(logiciels? installes?|programmes? installes?|applications? installees?|inventaire logiciel|liste des programmes|logiciels? sur ce pc)\b", value):
        return "software.inventory", "direct_action"

    search = bool(re.search(r"\b(cherche|recherche|trouve|localise)\b", value))
    software = bool(re.search(r"\b(winget|catalogue|logiciel|application|programme|paquet)\b", value))
    if search and software:
        return "software.search", "direct_action"
    if re.search(r"\b(instal\w*|telecharge et installe|ajoute le logiciel|ajoute l application)\b", value):
        return "software.install", "direct_action"
    return None, "outside_software_direct_actions"


def _read_messages(database: Path) -> list[dict[str, str]]:
    uri = database.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT m.content, COALESCE(c.title, '') AS conversation_title
            FROM messages AS m
            INNER JOIN conversations AS c ON c.id = m.conversation_id
            WHERE m.role = 'user'
            ORDER BY m.created_at, m.rowid
            """
        ).fetchall()
    finally:
        connection.close()
    return [{"text": str(row["content"]), "title": str(row["conversation_title"])} for row in rows]


def analyze(rows: list[dict[str, str]], policy: dict[str, Any]) -> dict[str, Any]:
    unique: dict[str, str] = {}
    exclusions: Counter[str] = Counter()
    raw_classified: Counter[str] = Counter()
    for row in rows:
        intent, reason = classify(row.get("text", ""), conversation_title=row.get("title", ""))
        if not intent:
            exclusions[reason] += 1
            continue
        raw_classified[intent] += 1
        key = normalize(row.get("text", ""))
        unique.setdefault(key, intent)
    counts = Counter(unique.values())
    minimum = int(policy["retrospective_coverage"]["minimum_requests_for_real_usage_coverage"])
    eligible = [family for family in FAMILIES if counts[family] < minimum]
    digest_source = sorted((intent, text) for text, intent in unique.items())
    return {
        "schema": "marvin.tool-selection-retrospective-coverage/1.0",
        "status": "complete_aggregate_retrospective_not_a_product_score",
        "policy_sha256": _sha(POLICY),
        "source": {
            "user_message_count": len(rows),
            "database_opened_read_only": True,
            "tool_names_read": False,
            "tool_results_read": False,
        },
        "coverage": {
            "unit": "unique_normalized_direct_action_request",
            "minimum": minimum,
            "counts_by_family": {family: counts[family] for family in FAMILIES},
            "raw_classified_before_deduplication": {family: raw_classified[family] for family in FAMILIES},
            "eligible_r4_families": eligible,
            "covered_by_real_usage_families": [family for family in FAMILIES if counts[family] >= minimum],
            "classified_projection_sha256": hashlib.sha256(
                json.dumps(digest_source, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        },
        "excluded_counts": dict(sorted(exclusions.items())),
        "claims": {
            "independent_holdout": False,
            "product_quality_score": False,
            "r4_scope_only": True,
            "unrepresented_means_unassessed": True,
        },
        "privacy": {
            "plaintext_published": False,
            "identifiers_published": False,
            "personal_data_published": False,
        },
    }


def _atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError("L'inventaire de couverture v1.6 existe déjà; écrasement interdit.")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy["status"] != "frozen_before_retrospective_coverage_recalculation":
        raise RuntimeError("Stratégie v1.6 non gelée.")
    value = analyze(_read_messages(DATABASE), policy)
    _atomic(OUTPUT, value)
    print(json.dumps(value["coverage"], ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
