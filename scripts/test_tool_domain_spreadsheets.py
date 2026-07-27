"""Régressions déterministes du domaine Tableurs."""

from __future__ import annotations

import asyncio
import csv
import sys
import tempfile
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tool_domains import spreadsheets
import tools


def _resolve(raw: str) -> str:
    return str(Path(raw).resolve())


async def _run() -> None:
    spreadsheets.configure(resolve_path=_resolve)
    with tempfile.TemporaryDirectory(prefix="marvin-spreadsheets-") as temp:
        root = Path(temp)
        workbook_path = root / "wide.xlsx"
        headers = [f"Colonne {index}" for index in range(1, 29)]
        row = [index for index in range(1, 28)] + ["=SUM(A3:AA3)"]
        created = await spreadsheets.create_xlsx(
            {
                "path": str(workbook_path),
                "title": "Tableau de validation",
                "headers": headers,
                "rows": [row],
                "sheet_name": "Validation",
            }
        )
        assert created.get("success") is True, created
        workbook = load_workbook(workbook_path, data_only=False)
        try:
            sheet = workbook["Validation"]
            assert str(sheet.merged_cells) == "A1:AB1"
            assert sheet["AB3"].value == "=SUM(A3:AA3)"
            assert sheet.column_dimensions["AB"].width > 0
        finally:
            workbook.close()

        summary = await spreadsheets.read_xlsx(
            {"path": str(workbook_path), "action": "summary"}
        )
        assert summary.get("success") is True, summary
        assert summary["columns"] == 28
        assert summary["rows"] == 3

        sheets = await spreadsheets.read_xlsx(
            {"path": str(workbook_path), "action": "sheets"}
        )
        assert sheets["sheets"] == ["Validation"]
        read = await spreadsheets.read_xlsx(
            {"path": str(workbook_path), "max_rows": 1}
        )
        assert read["rows_loaded"] == 1
        assert len(read["headers"]) == 28
        invalid_limit = await spreadsheets.read_xlsx(
            {"path": str(workbook_path), "max_rows": 0}
        )
        assert "compris entre" in invalid_limit.get("error", "")

        csv_path = root / "source.csv"
        csv_path.write_text("nom;valeur\nalpha;1\nbêta;2\n", encoding="utf-8")
        converted_path = root / "converted.xlsx"
        converted = await spreadsheets.csv_to_xlsx(
            {"path": str(csv_path), "output_path": str(converted_path)}
        )
        assert converted.get("success") is True, converted
        assert converted["rows"] == 3

        roundtrip_path = root / "roundtrip.csv"
        roundtrip = await spreadsheets.xlsx_to_csv(
            {
                "path": str(converted_path),
                "output_path": str(roundtrip_path),
                "delimiter": ";",
            }
        )
        assert roundtrip.get("success") is True, roundtrip
        with roundtrip_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle, delimiter=";"))
        assert rows == [["nom", "valeur"], ["alpha", "1"], ["bêta", "2"]]

        invalid_sheet = await spreadsheets.create_xlsx(
            {"path": str(root / "bad.xlsx"), "sheet_name": "bad/name"}
        )
        assert "caractère interdit" in invalid_sheet.get("error", "")
        invalid_delimiter = await spreadsheets.xlsx_to_csv(
            {"path": str(converted_path), "delimiter": "::"}
        )
        assert "exactement un caractère" in invalid_delimiter.get("error", "")

    spreadsheets.configure(resolve_path=tools._resolve_path)
    assert tools.execute_file_create_xlsx is spreadsheets.create_xlsx
    assert tools.execute_csv_to_xlsx is spreadsheets.csv_to_xlsx
    assert tools.execute_xlsx_to_csv is spreadsheets.xlsx_to_csv
    assert tools.execute_xlsx_read is spreadsheets.read_xlsx


if __name__ == "__main__":
    asyncio.run(_run())
    print("Spreadsheet tool domain tests passed.")
