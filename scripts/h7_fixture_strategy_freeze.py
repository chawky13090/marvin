"""Valide et gèle la stratégie fixtures E7 / harnais H7 sans exécuter d'outil."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
E7_CLASSIFICATION = BASE / "e7-classification.json"
E7_MANIFEST = BASE / "e7-freeze-manifest.json"
STRATA_POLICY = BASE / "fixture-strata-policy.json"
H7_POLICY = BASE / "h7-harness-policy.json"
H7_CORPUS = BASE / "h7-adversarial-corpus.json"
MANIFEST = BASE / "h7-fixture-strategy-manifest.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Objet JSON attendu : {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pair(item: dict[str, Any]) -> str:
    return f"{item['tool']}:{item['action']}"


def validate() -> dict[str, Any]:
    classification = _load(E7_CLASSIFICATION)
    strata = _load(STRATA_POLICY)
    h7 = _load(H7_POLICY)
    corpus = _load(H7_CORPUS)

    classified = {_pair(item): str(item["class"]) for item in classification["items"]}
    direct = set(map(str, strata["direct_fixture_pairs"]))
    bounded = set(map(str, strata["bounded_polymorphic_pairs"]))
    arbitrary = set(map(str, strata["arbitrary_executor_pairs"]))
    groups = (direct, bounded, arbitrary)
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise AssertionError("Les trois strates doivent être disjointes.")
    if set(classified) != direct | bounded | arbitrary:
        raise AssertionError("Les strates ne couvrent pas exactement les 36 couples E7.")
    if direct != {pair for pair, klass in classified.items() if klass != "P"}:
        raise AssertionError("La strate directe doit contenir exactement les couples non-P.")
    if bounded | arbitrary != {pair for pair, klass in classified.items() if klass == "P"}:
        raise AssertionError("Les deux strates P doivent couvrir exactement les 14 couples P.")
    if (len(direct), len(bounded), len(arbitrary)) != (22, 6, 8):
        raise AssertionError("Répartition attendue : 22 directs, 6 P bornés, 8 exécuteurs.")

    rules = strata["rules"]
    if rules.get("H7_never_implies_E7") is not True:
        raise AssertionError("H7 ne doit jamais conférer E7.")
    if rules.get("tool_execution_authorized") is not False:
        raise AssertionError("L'exécution d'outils doit rester verrouillée.")
    if h7.get("tool_execution_authorized") is not False:
        raise AssertionError("La politique H7 doit rester sans exécution.")
    if set(h7["authorization_modes"]) != {"normal", "auto", "full"}:
        raise AssertionError("Les trois modes d'autorisation réels doivent être couverts.")
    if set(h7["privacy_presets_are_orthogonal"]) != {
        "normal", "hyper", "cloud_max", "ultra"
    }:
        raise AssertionError("Les quatre profils de confidentialité doivent rester orthogonaux.")
    separation = h7["separation"]
    if not separation.get("H7_never_sets_E7"):
        raise AssertionError("La séparation H7/E7 est obligatoire.")

    if corpus.get("payloads_are_symbolic") is not True:
        raise AssertionError("Le corpus H7 public doit rester symbolique.")
    if corpus.get("tool_execution_authorized") is not False:
        raise AssertionError("Le corpus H7 ne doit autoriser aucune exécution.")
    cases = corpus.get("cases", [])
    ids = [str(case.get("id")) for case in cases]
    if len(cases) != 30 or len(ids) != len(set(ids)):
        raise AssertionError("Le corpus H7 doit contenir 30 cas uniques.")
    forbidden_payload_fields = {"command", "script", "content", "payload", "arguments"}
    for case in cases:
        if forbidden_payload_fields & set(case):
            raise AssertionError(f"Payload exécutable interdit dans {case.get('id')}.")
        if case.get("mode") not in {"normal", "auto", "full"}:
            raise AssertionError(f"Mode H7 inconnu dans {case.get('id')}.")
    privacy_cases = {case.get("privacy") for case in cases if case.get("privacy")}
    if privacy_cases != {"normal", "hyper", "cloud_max", "ultra"}:
        raise AssertionError("Le miroir d'invariance doit couvrir les quatre profils.")
    by_vector = {str(case["vector"]): case for case in cases}
    catastrophic = by_vector.get("catastrophic_command_with_valid_approval", {})
    if catastrophic.get("mode") != "full" or catastrophic.get("expected") != "deny":
        raise AssertionError("Le refus absolu doit être testé en accès complet avec approbation valide.")
    auto_high = by_vector.get("non_elevated_risk_tier_4_under_auto", {})
    if auto_high.get("mode") != "auto" or auto_high.get("expected") != "require_confirmation":
        raise AssertionError("Le plafond Auto hors élévation doit être testé au niveau 4.")
    properties = h7["required_properties"]
    if properties.get("catastrophic_command_is_denied_even_with_full_mode_and_valid_approval") is not True:
        raise AssertionError("La politique doit exiger le mur de refus catastrophique.")
    if properties.get("auto_never_approves_risk_tier_above_3") is not True:
        raise AssertionError("La politique doit exiger le plafond Auto de niveau 3.")

    return {
        "classified_pairs": len(classified),
        "direct_fixture_pairs": len(direct),
        "bounded_polymorphic_pairs": len(bounded),
        "arbitrary_executor_pairs": len(arbitrary),
        "h7_abstract_cases": len(cases),
        "tool_execution_authorized": False,
        "h7_sets_e7": False,
    }


def freeze() -> dict[str, Any]:
    summary = validate()
    sources = [E7_MANIFEST, STRATA_POLICY, H7_POLICY, H7_CORPUS]
    payload = {
        "schema": "marvin.h7-fixture-strategy-manifest/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_before_fixture_or_harness_execution",
        "source_hashes": {
            path.relative_to(ROOT).as_posix(): _sha256(path) for path in sources
        },
        "summary": summary,
        "fixture_design_authorized": True,
        "h7_harness_test_design_authorized": True,
        "tool_execution_authorized": False,
        "refreeze_required_on_source_change": True,
    }
    descriptor, name = tempfile.mkstemp(
        prefix=f".{MANIFEST.name}.", suffix=".tmp", dir=MANIFEST.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, MANIFEST)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def main() -> int:
    print(json.dumps(freeze()["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
