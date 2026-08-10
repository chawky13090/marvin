"""Valide et gèle la taxonomie E7 sans exécuter d'outil."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
POLICY_PATH = BASE / "e7-taxonomy-policy.json"
CLASSIFICATION_PATH = BASE / "e7-classification.json"
CANDIDATES_PATH = BASE / "campaign-b-candidates.json"
MANIFEST_PATH = BASE / "e7-freeze-manifest.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Objet JSON attendu : {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> dict[str, Any]:
    policy = _load(POLICY_PATH)
    classification = _load(CLASSIFICATION_PATH)
    candidates = _load(CANDIDATES_PATH)
    if policy.get("execution_authorized") is not False:
        raise AssertionError("La politique E7 doit rester verrouillée.")
    if classification.get("execution_authorized") is not False:
        raise AssertionError("La classification E7 doit rester verrouillée.")
    expected = {
        (str(item["tool"]), str(item["action"]))
        for item in candidates.get("first_wave", [])
    }
    items = classification.get("items", [])
    actual = {(str(item["tool"]), str(item["action"])) for item in items}
    if len(actual) != len(items):
        raise AssertionError("Couple outil/action E7 dupliqué.")
    if actual != expected:
        raise AssertionError(
            f"Classification E7 incomplète : absents={sorted(expected-actual)}, "
            f"surplus={sorted(actual-expected)}"
        )
    classes = set(policy.get("classes", {}))
    profiles = set(policy.get("surface_profiles", {}))
    counts = Counter()
    for item in items:
        klass = str(item.get("class") or "")
        counts[klass] += 1
        if klass not in classes:
            raise AssertionError(f"Classe E7 inconnue : {klass}")
        if item.get("surface_profile") not in profiles:
            raise AssertionError(f"Surface inconnue pour {item['tool']}:{item['action']}")
        for field in ("expected_delta", "justification", "residual_loss"):
            if not str(item.get(field) or "").strip():
                raise AssertionError(f"Champ {field} absent pour {item['tool']}:{item['action']}")
        paths = item.get("restoration_paths_considered")
        if not isinstance(paths, list):
            raise AssertionError("restoration_paths_considered doit être une liste")
        if klass == "R":
            if not paths or item["residual_loss"] != "none_expected":
                raise AssertionError("R exige restauration déclarée et aucune perte attendue")
        elif klass == "C":
            if not paths or item["residual_loss"] in {"", "none_expected", "not_applicable"}:
                raise AssertionError("C exige compensation et perte résiduelle mesurable")
        elif klass == "I":
            if item.get("intrinsic_irreversibility") is not True or not paths:
                raise AssertionError("I exige irréversibilité intrinsèque et chemins examinés")
        elif klass == "N":
            if paths or item["residual_loss"] != "not_applicable":
                raise AssertionError("N interdit rollback et perte résiduelle")
        elif klass == "P":
            allowed = item.get("allowed_scenario_classes")
            if not isinstance(allowed, list) or not allowed or "P" in allowed:
                raise AssertionError("P exige des classes de scénario finales bornées")
            if not set(allowed) <= {"R", "C", "I", "N"}:
                raise AssertionError("Classe finale interdite pour P")
    if counts["I"] == 0 or counts["P"] == 0 or counts["N"] == 0:
        raise AssertionError("La taxonomie doit exercer I, P et N avant les fixtures")
    return {
        "classified_pairs": len(items),
        "class_counts": dict(sorted(counts.items())),
        "execution_authorized": False,
    }


def freeze() -> dict[str, Any]:
    summary = validate()
    sources = [POLICY_PATH, CLASSIFICATION_PATH, CANDIDATES_PATH]
    payload = {
        "schema": "marvin.e7-freeze-manifest/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_before_fixture_design",
        "source_hashes": {
            path.relative_to(ROOT).as_posix(): _sha256(path) for path in sources
        },
        "summary": summary,
        "fixture_design_authorized": True,
        "tool_execution_authorized": False,
        "refreeze_required_on_source_change": True,
    }
    descriptor, name = tempfile.mkstemp(
        prefix=f".{MANIFEST_PATH.name}.", suffix=".tmp", dir=MANIFEST_PATH.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, MANIFEST_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def main() -> int:
    payload = freeze()
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
