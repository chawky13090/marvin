"""Régressions SQLite du repository de sécurité des commandes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.command_safety import CommandSafetyRepository
from repositories.command_safety_rules import DEFAULT_COMMAND_RISK_RULES


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "command-safety.db"
        repository = CommandSafetyRepository(
            connection_scope=lambda: db(path)
        )
        with db(path) as connection:
            repository.ensure_schema(connection)

        rules = repository.rules_list()
        assert len(rules) == len(DEFAULT_COMMAND_RISK_RULES) == 25
        payload = json.dumps(
            DEFAULT_COMMAND_RISK_RULES,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        assert hashlib.sha256(payload).hexdigest() == (
            "478ae98254ae17f2ff124735d850d7116e9d57782730339a4f4a28c22067a479"
        )

        with patch(
            "repositories.command_safety.uuid.uuid4",
            return_value="review-a",
        ):
            review = repository.review_create(
                {
                    "intervention_id": "intervention-a",
                    "command": "qm destroy 101",
                    "platform": "proxmox",
                    "risk_level": "critical",
                    "requires_approval": True,
                    "matched_rule": r"\bqm\s+destroy\b",
                }
            )
        assert review["requires_approval"] == 1
        assert repository.review_list(
            "intervention-a",
            "critical",
            limit=0,
        )[0]["id"] == "review-a"

        with patch(
            "repositories.command_safety.uuid.uuid4",
            return_value="approval-a",
        ):
            approval = repository.approval_create(
                {
                    "command_review_id": "review-a",
                    "command": "",
                    "requested_by": "Marvin",
                    "status": "approved",
                }
            )
        assert approval["command"] == "qm destroy 101"
        assert approval["status"] == "pending"
        approved = repository.approval_decide(
            "approval-a",
            "approved",
            approver="Chaouki",
            reason="Fenêtre validée",
        )
        assert approved["status"] == "approved"
        assert approved["decided_at"]
        repeated = repository.approval_decide(
            "approval-a",
            "approved",
            approver="Autre",
            reason="Ne doit pas remplacer la preuve",
        )
        assert repeated["approver"] == "Chaouki"
        assert repeated["reason"] == "Fenêtre validée"
        try:
            repository.approval_decide("approval-a", "rejected")
        except ValueError:
            pass
        else:
            raise AssertionError(
                "Une décision finale contradictoire doit être refusée."
            )
        assert repository.approval_list("approved")[0]["id"] == "approval-a"
        assert repository.approval_decide("absent", "approved") is None

        invalid_reviews = (
            {"command": ""},
            {"command": "echo ok", "platform": "inconnue"},
            {"command": "echo ok", "risk_level": "inconnu"},
        )
        for data in invalid_reviews:
            try:
                repository.review_create(data)
            except ValueError:
                pass
            else:
                raise AssertionError(f"Analyse invalide acceptée: {data!r}")

        invalid_approvals = (
            {"command_review_id": "absent", "command": "echo ok"},
            {"command_review_id": "review-a", "command": "autre commande"},
            {"command": ""},
        )
        for data in invalid_approvals:
            try:
                repository.approval_create(data)
            except ValueError:
                pass
            else:
                raise AssertionError(
                    f"Demande d'approbation invalide acceptée: {data!r}"
                )

        with patch(
            "repositories.command_safety.uuid.uuid4",
            return_value="review-a",
        ):
            try:
                repository.review_create({"command": "echo collision"})
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("La collision doit être annulée.")
        assert len(repository.review_list()) == 1

    import database
    from repositories import command_safety

    names = (
        "cmd_rules_list",
        "cmd_review_create",
        "cmd_review_list",
        "approval_create",
        "approval_list",
        "approval_decide",
    )
    for name in names:
        assert getattr(database, name) is getattr(command_safety, name), name

    print(
        "Command Safety Repository OK - 25 règles exactes, analyses, "
        "approbations idempotentes, transitions, rollback et 6 façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
