"""Vérifie la confidentialité et la rétention du diagnostic de matching des skills."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import skills  # noqa: E402


def run() -> None:
    secret_query = "Mon dossier client très confidentiel"
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "skills_match_log.jsonl"
        path.write_text(
            json.dumps(
                {
                    "at": "2025-01-01 12:00:00",
                    "query": secret_query,
                    "winner": "ancienne-skill",
                    "winner_score": 0.9,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        previous = skills._MATCH_LOG_FILE
        try:
            skills._MATCH_LOG_FILE = str(path)
            skills._MATCH_LOG_STORE = None
            skills._MATCH_LOG_STORE_PATH = None
            store = skills._match_log_store()
            migrated = store.recent(10)
            assert migrated[0]["winner"] == "ancienne-skill"
            assert migrated[0]["query"]["redacted"] is True
            assert secret_query not in path.read_text(encoding="utf-8")

            best = {"name": "diagnostic-reseau"}
            runner_up = {"name": "diagnostic-windows"}
            skills._log_match_attempt(
                secret_query,
                best,
                best,
                0.94,
                runner_up,
                0.81,
            )
            entries = skills.get_match_log(10)
            assert entries[0]["event_name"] == "skill.match"
            assert entries[0]["outcome"] == "matched"
            assert entries[0]["winner"] == "diagnostic-reseau"
            assert entries[0]["query"]["redacted"] is True
            assert entries[0]["query"]["length"] > 0
            assert len(entries[0]["query"]["sha256"]) == 64
            assert secret_query not in path.read_text(encoding="utf-8")
            assert skills.get_match_log(0) == []
        finally:
            skills._MATCH_LOG_FILE = previous
            skills._MATCH_LOG_STORE = None
            skills._MATCH_LOG_STORE_PATH = None

    print("Skill Match Logging OK - migration, empreinte, compatibilité et bornes.")


if __name__ == "__main__":
    run()
