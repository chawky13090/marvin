"""Régressions du domaine CSV, graphique et SQLite."""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from agent_safety import validator_for
from tool_domains import structured_data as domain


async def run_domain() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        domain.configure(resolve_path=lambda value: str(Path(value).expanduser().resolve()))

        csv_path = root / "mesures.csv"
        csv_path.write_text(
            "nom;valeur;groupe\nalpha;1,5;A\nbeta;2,5;B\ngamma;3;A\n",
            encoding="utf-8",
        )
        summary = await domain.csv_analyze(
            {"path": str(csv_path), "delimiter": ";", "action": "summary"}
        )
        assert summary["rows_loaded"] == 3
        assert summary["column_analysis"]["valeur"]["numeric"] is True
        assert summary["column_analysis"]["valeur"]["mean"] == 2.3333
        stats = await domain.csv_analyze(
            {
                "path": str(csv_path),
                "delimiter": ";",
                "action": "stats",
                "column": "valeur",
            }
        )
        assert stats["median"] == 2.5
        unique = await domain.csv_analyze(
            {
                "path": str(csv_path),
                "delimiter": ";",
                "action": "unique",
                "column": "groupe",
            }
        )
        assert unique["unique_values"] == ["A", "B"]
        assert "séparateur" in (
            await domain.csv_analyze({"path": str(csv_path), "delimiter": "::"})
        )["error"]
        assert "max_rows" in (
            await domain.csv_analyze({"path": str(csv_path), "max_rows": 0})
        )["error"]
        malformed_csv = root / "malformed.csv"
        malformed_csv.write_text("nom;nom\na;b\n", encoding="utf-8")
        assert "uniques" in (
            await domain.csv_analyze(
                {"path": str(malformed_csv), "delimiter": ";"}
            )
        )["error"]

        chart_path = root / "graphique.png"
        chart = await domain.csv_to_chart(
            {
                "path": str(csv_path),
                "chart_type": "line",
                "label_column": 0,
                "value_columns": "1",
                "title": "Mesures",
                "output_path": str(chart_path),
            }
        )
        assert chart["success"] is True
        assert chart["points"] == 3
        assert chart_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert "extension .png" in (
            await domain.csv_to_chart(
                {"path": str(csv_path), "output_path": str(root / "bad.jpg")}
            )
        )["error"]

        database = root / "sample.sqlite"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute('CREATE TABLE "odd\'name"(value TEXT)')
        connection.executemany(
            "INSERT INTO items(name) VALUES(?)",
            [("alpha",), ("beta",), ("gamma",)],
        )
        connection.commit()
        connection.close()

        tables = await domain.sqlite_tables({"db_path": str(database)})
        assert tables["success"] is True
        assert {item["name"] for item in tables["tables"]} == {"items", "odd'name"}
        assert tables["schema"]["odd'name"][0]["col"] == "value"

        selected = await domain.sqlite_query(
            {
                "db_path": str(database),
                "query": "SELECT id, name FROM items ORDER BY id",
                "max_rows": 2,
            }
        )
        assert selected["rows_count"] == 2
        assert selected["truncated"] is True
        assert selected["rows"][0] == {"id": 1, "name": "alpha"}

        cte_write = (
            "WITH source(name) AS (SELECT 'delta') "
            "INSERT INTO items(name) SELECT name FROM source"
        )
        confirmation = await domain.sqlite_query(
            {"db_path": str(database), "query": cte_write}
        )
        assert confirmation["requiresConfirmation"] is True
        connection = sqlite3.connect(database)
        count_before = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        connection.close()
        assert count_before == 3

        written = await domain.sqlite_query(
            {"db_path": str(database), "query": cte_write, "confirmed": True}
        )
        assert written["success"] is True
        assert written["write"] is True
        backup = Path(written["rollback_path"])
        assert backup.is_file()
        connection = sqlite3.connect(database)
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 4
        connection.close()

        # Preuve de rollback exploitable : la sauvegarde SQLite restaure l'état exact.
        shutil.copy2(backup, database)
        connection = sqlite3.connect(database)
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3
        connection.close()

        backups_before = set((root / ".marvin-backups").iterdir())
        failed_write = await domain.sqlite_query(
            {
                "db_path": str(database),
                "query": "INSERT INTO items(id, name) VALUES(1, 'duplicate')",
                "confirmed": True,
            }
        )
        assert "SQLite" in failed_write["error"]
        assert set((root / ".marvin-backups").iterdir()) == backups_before
        connection = sqlite3.connect(database)
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3
        connection.close()

        forbidden = await domain.sqlite_query(
            {
                "db_path": str(database),
                "query": f"ATTACH DATABASE '{(root / 'other.db').as_posix()}' AS other",
                "confirmed": True,
            }
        )
        assert "interdite" in forbidden["error"]


def main() -> int:
    assert tools.execute_csv_analyze is domain.csv_analyze
    assert tools.execute_csv_to_chart is domain.csv_to_chart
    assert tools.execute_sqlite_query is domain.sqlite_query
    assert tools.execute_sqlite_tables is domain.sqlite_tables
    for name, function in {
        "csv_analyze": domain.csv_analyze,
        "csv_to_chart": domain.csv_to_chart,
        "sqlite_query": domain.sqlite_query,
        "sqlite_tables": domain.sqlite_tables,
    }.items():
        assert tools.TOOLS_REGISTRY[name] is function

    validator = validator_for(tools.TOOLS_SPEC)
    assert validator("csv_analyze", {"path": "x.csv", "max_rows": 0})
    assert validator(
        "sqlite_query",
        {"db_path": "x.db", "query": "SELECT 1", "max_rows": 1001},
    )
    asyncio.run(run_domain())
    print("Structured Data Domain OK - CSV, PNG, SQLite, confirmation et rollback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
