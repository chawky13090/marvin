"""Contrôle exhaustif des chemins JSONL appartenant au backend Marvin."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
INVENTORY = ROOT / "MARVIN-PERSISTENCE-INVENTORY.md"
ALLOWED_CLASSES = {
    "technical_log",
    "domain_event_stream",
    "evaluation_ledger",
    "truth_ledger",
}
ALLOWED_STATES = {"structured", "pending"}


def discovered_jsonl() -> set[tuple[str, str]]:
    discovered: set[tuple[str, str]] = set()
    for path in BACKEND.rglob("*.py"):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.endswith(".jsonl")
            ):
                continue
            discovered.add((path.relative_to(ROOT).as_posix(), Path(node.value).name))
    return discovered


def manifest(text: str) -> dict[tuple[str, str], tuple[str, str, str]]:
    match = re.search(r"<!-- persistence-inventory\s*(.*?)\s*-->", text, flags=re.DOTALL)
    if not match:
        raise AssertionError("Manifeste persistence-inventory absent.")
    result: dict[tuple[str, str], tuple[str, str, str]] = {}
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 5:
            raise AssertionError(f"Ligne d'inventaire invalide : {line}")
        module, filename, category, lifecycle, state = parts
        key = (module, filename)
        if key in result:
            raise AssertionError(f"Persistance dupliquée : {key}")
        if category not in ALLOWED_CLASSES:
            raise AssertionError(f"Classe invalide pour {key} : {category}")
        if state not in ALLOWED_STATES:
            raise AssertionError(f"État invalide pour {key} : {state}")
        if not lifecycle:
            raise AssertionError(f"Cycle de vie absent pour {key}")
        result[key] = (category, lifecycle, state)
    return result


def run() -> None:
    text = INVENTORY.read_text(encoding="utf-8-sig")
    declared = manifest(text)
    discovered = discovered_jsonl()
    assert set(declared) == discovered, (
        f"Inventaire JSONL désynchronisé : absents={sorted(discovered - set(declared))}, "
        f"obsolètes={sorted(set(declared) - discovered)}"
    )
    structured_logs = {
        key for key, value in declared.items()
        if value[0] == "technical_log" and value[2] == "structured"
    }
    assert structured_logs == {
        ("backend/audit.py", "audit.jsonl"),
        ("backend/bug_log.py", "bug_log.jsonl"),
        ("backend/skills.py", "skills_match_log.jsonl"),
    }
    for module, _filename in structured_logs:
        source = (ROOT / module).read_text(encoding="utf-8-sig")
        assert "StructuredJsonlStore" in source
    structured_evidence = {
        key for key, value in declared.items()
        if value[0] == "evaluation_ledger" and value[2] == "structured"
    }
    assert structured_evidence == {("backend/forge.py", "forge_runs.jsonl")}
    assert "DurableEvidenceStore" in (ROOT / "backend" / "forge.py").read_text(
        encoding="utf-8-sig"
    )
    structured_domain_streams = {
        key for key, value in declared.items()
        if value[0] == "domain_event_stream" and value[2] == "structured"
    }
    assert structured_domain_streams == {
        ("backend/coding_mission.py", "events.jsonl"),
        ("backend/engineering_radar.py", "events.jsonl"),
        ("backend/mission_os.py", "mission_events.jsonl")
    }
    for module, _filename in structured_domain_streams:
        assert "DurableEvidenceStore" in (ROOT / module).read_text(encoding="utf-8-sig")
    for phrase in (
        "source de données durable",
        "idempotence",
        "corruption partielle",
        "ne sont jamais réécrits",
        "preuves métier sont conservées par défaut",
        "suppression doit être explicite et confirmée",
        "compensatoire ou une nouvelle version",
    ):
        assert phrase in text
    print(
        "Persistence Inventory OK - "
        f"{len(declared)} JSONL classifiés, {len(structured_logs)} logs et "
        f"{len(structured_evidence)} registre d'évaluation et "
        f"{len(structured_domain_streams)} flux métier structurés."
    )


if __name__ == "__main__":
    try:
        run()
    except (AssertionError, OSError, SyntaxError) as exc:
        print(f"ECHEC inventaire persistance : {exc}")
        raise SystemExit(1)
