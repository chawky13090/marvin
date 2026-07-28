"""Régressions SQLite du repository de santé client."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.client_health import ClientHealthRepository


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "client-health.db"
        repository = ClientHealthRepository(connection_scope=lambda: db(path))
        with db(path) as connection:
            repository.ensure_schema(connection)

        with patch(
            "repositories.client_health.uuid.uuid4",
            side_effect=("score-a", "item-a", "recommendation-a"),
        ):
            score = repository.score_create(
                {
                    "client_id": "client-a",
                    "backup_score": 90,
                    "security_score": 80,
                    "documentation_score": 70,
                    "infrastructure_score": 60,
                    "incident_score": 50,
                    "global_score": 70,
                    "risk_level": "medium",
                },
                [
                    {
                        "category": "backup",
                        "label": "Sauvegarde",
                        "points": 9,
                        "max_points": 10,
                        "status": "ok",
                    }
                ],
                [
                    {
                        "priority": "high",
                        "category": "security",
                        "title": "Activer MFA",
                    }
                ],
            )
        assert score["id"] == "score-a"
        assert score["items"][0]["points"] == 9
        assert score["recommendations"][0]["title"] == "Activer MFA"
        assert repository.score_get("score-a") == score
        assert repository.score_latest("client-a")["id"] == "score-a"
        assert repository.score_history("client-a", limit=0)[0]["id"] == "score-a"
        assert repository.recommendations_list(
            "client-a",
            "open",
        )[0]["id"] == "recommendation-a"

        with patch(
            "repositories.client_health.uuid.uuid4",
            return_value="score-a",
        ):
            try:
                repository.score_create(
                    {"client_id": "client-a", "global_score": 10},
                    [{"label": "Ne doit pas rester"}],
                )
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("La collision doit annuler tout l'agrégat.")
        with db(path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM client_health_items"
            ).fetchone()[0] == 1

        invalid_cases = (
            ({"client_id": "", "global_score": 10}, None, None),
            ({"client_id": "client-a", "global_score": -1}, None, None),
            ({"client_id": "client-a", "global_score": float("nan")}, None, None),
            (
                {"client_id": "client-a", "global_score": 10},
                [{"label": "Incohérent", "points": 2, "max_points": 1}],
                None,
            ),
            (
                {"client_id": "client-a", "global_score": 10},
                ["pas-un-objet"],
                None,
            ),
            (
                {"client_id": "client-a", "global_score": 10},
                None,
                ["pas-un-objet"],
            ),
        )
        for data, items, recommendations in invalid_cases:
            try:
                repository.score_create(data, items, recommendations)
            except ValueError:
                pass
            else:
                raise AssertionError(f"Entrée invalide acceptée: {data!r}")

        with patch(
            "repositories.client_health.uuid.uuid4",
            return_value="score-risk",
        ):
            try:
                repository.score_create(
                    {
                        "client_id": "client-a",
                        "global_score": 10,
                        "risk_level": "inconnu",
                    }
                )
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Un niveau de risque inconnu doit être refusé.")
        assert repository.score_get("score-risk") is None

    import database
    from repositories import client_health

    names = (
        "health_score_create",
        "health_score_get",
        "health_score_latest",
        "health_score_history",
        "health_recommendations_list",
    )
    for name in names:
        assert getattr(database, name) is getattr(client_health, name), name

    print(
        "Client Health Repository OK - agrégat atomique, scores bornés, "
        "historique, recommandations, rollback et 5 façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
