"""Analyse CSV, graphiques et inspection SQLite avec limites et rollback."""

from __future__ import annotations

import asyncio
import csv
import math
import os
import sqlite3
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote


PathResolver = Callable[[str], str]

_MAX_CSV_BYTES = 50 * 1024 * 1024
_MAX_CSV_ROWS = 10_000
_MAX_CSV_COLUMNS = 500
_MAX_UNIQUE_VALUES = 200
_MAX_CHART_POINTS = 200
_MAX_CHART_COLUMNS = 20
_MAX_QUERY_LENGTH = 100_000
_MAX_SQL_ROWS = 1_000
_SQL_TIMEOUT_SECONDS = 5.0
_BLOCKED_PRAGMAS = {
    "data_store_directory",
    "journal_mode",
    "legacy_file_format",
    "locking_mode",
    "page_size",
    "temp_store_directory",
    "wal_checkpoint",
    "writable_schema",
}

_resolve_path: PathResolver = lambda value: str(Path(value).expanduser().resolve())


def configure(*, resolve_path: PathResolver) -> None:
    global _resolve_path
    _resolve_path = resolve_path


def _int_arg(
    value: object,
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> tuple[int | None, str | None]:
    if value is None:
        return default, None
    if isinstance(value, bool):
        return None, f"Paramètre '{name}' invalide."
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"Paramètre '{name}' invalide."
    if not minimum <= parsed <= maximum:
        return None, f"Paramètre '{name}' attendu entre {minimum} et {maximum}."
    return parsed, None


def _source_file(value: object, *, suffixes: set[str] | None = None) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, "Chemin de fichier requis."
    try:
        path = Path(_resolve_path(value.strip()))
    except (OSError, ValueError) as exc:
        return None, f"Chemin invalide : {exc}"
    if not path.is_file():
        return None, f"Fichier introuvable : {path}"
    if suffixes is not None and path.suffix.casefold() not in suffixes:
        return None, f"Extension attendue : {', '.join(sorted(suffixes))}."
    return path, None


def _delimiter(value: object) -> tuple[str | None, str | None]:
    delimiter = "," if value is None else str(value)
    if delimiter == r"\t":
        delimiter = "\t"
    if len(delimiter) != 1 or delimiter in {"\r", "\n", "\x00"}:
        return None, "Le séparateur CSV doit être un caractère unique."
    return delimiter, None


def _finite_number(value: object) -> float | None:
    if value is None:
        return None
    normalized = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".").strip()
    if not normalized:
        return None
    try:
        number = float(normalized)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _read_csv_rows(
    path: Path,
    *,
    delimiter: str,
    max_rows: int,
) -> tuple[list[str], list[dict[str, str | None]], bool]:
    if path.stat().st_size > _MAX_CSV_BYTES:
        raise ValueError(f"CSV limité à {_MAX_CSV_BYTES // (1024 * 1024)} Mio.")
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        headers = list(reader.fieldnames or [])
        if not headers:
            raise ValueError("En-tête CSV absent.")
        if len(headers) > _MAX_CSV_COLUMNS:
            raise ValueError(f"CSV limité à {_MAX_CSV_COLUMNS} colonnes.")
        if any(not isinstance(header, str) or not header.strip() for header in headers):
            raise ValueError("Chaque colonne CSV doit avoir un nom non vide.")
        if len(set(headers)) != len(headers):
            raise ValueError("Les noms de colonnes CSV doivent être uniques.")
        rows: list[dict[str, str | None]] = []
        truncated = False
        for row in reader:
            if len(rows) >= max_rows:
                truncated = True
                break
            if None in row:
                raise ValueError("Une ligne CSV contient plus de champs que l'en-tête.")
            rows.append(dict(row))
    return headers, rows, truncated


async def csv_analyze(args: dict[str, Any]) -> dict[str, Any]:
    path, error = _source_file(args.get("path"), suffixes={".csv", ".tsv", ".txt"})
    if error or path is None:
        return {"error": error}
    max_rows, error = _int_arg(
        args.get("max_rows"),
        name="max_rows",
        default=100,
        minimum=1,
        maximum=_MAX_CSV_ROWS,
    )
    if error or max_rows is None:
        return {"error": error}
    action = str(args.get("action") or "summary").strip().lower()
    if action not in {"summary", "head", "stats", "unique"}:
        return {"error": "Action attendue : summary | head | stats | unique."}
    delimiter, error = _delimiter(args.get("delimiter"))
    if error or delimiter is None:
        return {"error": error}
    column = str(args.get("column") or "")
    try:
        headers, rows, truncated = await asyncio.to_thread(
            _read_csv_rows, path, delimiter=delimiter, max_rows=max_rows
        )
    except (OSError, csv.Error, ValueError) as exc:
        return {"error": f"Lecture CSV échouée : {exc}"}

    base: dict[str, Any] = {
        "success": True,
        "file": str(path),
        "columns": headers,
        "column_count": len(headers),
        "rows_loaded": len(rows),
        "total_rows_approx": len(rows) + (1 if truncated else 0),
        "truncated": truncated,
    }
    if action == "head":
        return {**base, "preview": rows[:10]}
    if action in {"stats", "unique"} and column not in headers:
        return {
            **base,
            "error": f"Colonne '{column}' introuvable. Colonnes disponibles : {headers}",
        }
    if action == "unique":
        values = sorted(
            {str(row[column]) for row in rows if row.get(column) not in ("", None)}
        )
        return {
            **base,
            "column": column,
            "unique_values": values[:_MAX_UNIQUE_VALUES],
            "unique_count": len(values),
            "unique_truncated": len(values) > _MAX_UNIQUE_VALUES,
        }
    if action == "stats":
        numbers = [
            number
            for row in rows
            if (number := _finite_number(row.get(column))) is not None
        ]
        if not numbers:
            return {**base, "column": column, "error": "Aucune valeur numérique dans cette colonne."}
        return {
            **base,
            "column": column,
            "count": len(numbers),
            "sum": round(sum(numbers), 6),
            "mean": round(statistics.mean(numbers), 6),
            "median": round(statistics.median(numbers), 6),
            "min": min(numbers),
            "max": max(numbers),
            "stdev": round(statistics.stdev(numbers), 6) if len(numbers) > 1 else 0,
        }

    analysis: dict[str, Any] = {}
    for header in headers:
        values = [row.get(header, "") for row in rows]
        non_empty = [value for value in values if value not in ("", None)]
        numbers = [
            number
            for value in non_empty
            if (number := _finite_number(value)) is not None
        ]
        item: dict[str, Any] = {
            "non_empty": len(non_empty),
            "empty": len(values) - len(non_empty),
            "unique": len(set(non_empty)),
            "numeric": bool(non_empty) and len(numbers) == len(non_empty),
        }
        if numbers:
            item.update(
                min=min(numbers),
                max=max(numbers),
                mean=round(statistics.mean(numbers), 4),
            )
        analysis[header] = item
    return {**base, "column_analysis": analysis, "preview": rows[:5]}


def _sniff_delimiter(stream: Any) -> str:
    sample = stream.read(8_192)
    stream.seek(0)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _chart_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    if path.stat().st_size > _MAX_CSV_BYTES:
        raise ValueError(f"CSV limité à {_MAX_CSV_BYTES // (1024 * 1024)} Mio.")
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        delimiter = _sniff_delimiter(stream)
        reader = csv.reader(stream, delimiter=delimiter)
        header = next(reader, [])
        if not header:
            raise ValueError("En-tête CSV absent.")
        if len(header) > _MAX_CSV_COLUMNS:
            raise ValueError(f"CSV limité à {_MAX_CSV_COLUMNS} colonnes.")
        rows: list[list[str]] = []
        for row in reader:
            if any(cell.strip() for cell in row):
                rows.append(row)
            if len(rows) >= _MAX_CHART_POINTS:
                break
    if not rows:
        raise ValueError("CSV insuffisant (il faut un en-tête et des données).")
    return header, rows


def _parse_value_columns(value: object) -> tuple[list[int] | None, str | None]:
    if value in (None, ""):
        return None, None
    raw = value if isinstance(value, list) else str(value).split(",")
    if len(raw) > _MAX_CHART_COLUMNS:
        return None, f"Nombre de séries limité à {_MAX_CHART_COLUMNS}."
    columns: list[int] = []
    for item in raw:
        parsed, error = _int_arg(
            item,
            name="value_columns",
            default=0,
            minimum=0,
            maximum=_MAX_CSV_COLUMNS - 1,
        )
        if error or parsed is None:
            return None, error
        if parsed not in columns:
            columns.append(parsed)
    return columns, None


def _render_chart(
    *,
    header: list[str],
    rows: list[list[str]],
    label_column: int,
    value_columns: list[int],
    chart_type: str,
    title: str,
    output: Path,
) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    import numpy as np

    figure = Figure(figsize=(11, 6), dpi=120)
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    labels = [row[label_column] if label_column < len(row) else "" for row in rows]
    if chart_type == "pie":
        column = value_columns[0]
        values = [
            (_finite_number(row[column]) if column < len(row) else None) or 0
            for row in rows
        ]
        if any(value < 0 for value in values) or sum(values) <= 0:
            raise ValueError("Un graphique circulaire exige des valeurs positives dont la somme est non nulle.")
        axes.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
        axes.axis("equal")
    else:
        x_values = np.arange(len(labels))
        width = 0.8 / max(1, len(value_columns))
        for index, column in enumerate(value_columns):
            values = [
                (_finite_number(row[column]) if column < len(row) else None) or 0
                for row in rows
            ]
            label = header[column]
            if chart_type == "line":
                axes.plot(x_values, values, marker="o", label=label)
            else:
                axes.bar(
                    x_values + index * width - 0.4 + width / 2,
                    values,
                    width=width,
                    label=label,
                )
        axes.set_xticks(x_values, labels, rotation=45, ha="right")
        if len(value_columns) > 1:
            axes.legend()
        axes.grid(axis="y", alpha=0.3)
    axes.set_title(title)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.",
        suffix=output.suffix or ".png",
        dir=str(output.parent),
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        figure.savefig(temporary, format="png", bbox_inches="tight")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
        figure.clear()


async def csv_to_chart(args: dict[str, Any]) -> dict[str, Any]:
    path, error = _source_file(args.get("path"), suffixes={".csv", ".tsv", ".txt"})
    if error or path is None:
        return {"error": error}
    chart_type = str(args.get("chart_type") or "bar").strip().lower()
    if chart_type not in {"bar", "line", "pie"}:
        return {"error": "Paramètre 'chart_type' attendu : bar | line | pie."}
    label_column, error = _int_arg(
        args.get("label_column"),
        name="label_column",
        default=0,
        minimum=0,
        maximum=_MAX_CSV_COLUMNS - 1,
    )
    if error or label_column is None:
        return {"error": error}
    value_columns, error = _parse_value_columns(args.get("value_columns"))
    if error:
        return {"error": error}
    title = str(args.get("title") or path.stem).strip()
    if len(title) > 300:
        return {"error": "Titre limité à 300 caractères."}
    output_value = str(args.get("output_path") or "").strip()
    try:
        output = Path(_resolve_path(output_value)) if output_value else path.with_suffix(".png")
    except (OSError, ValueError) as exc:
        return {"error": f"Chemin de sortie invalide : {exc}"}
    if output.suffix.casefold() != ".png":
        return {"error": "Le graphique de sortie doit utiliser l'extension .png."}
    try:
        header, rows = await asyncio.to_thread(_chart_rows, path)
        if label_column >= len(header):
            return {"error": f"Colonne d'étiquettes hors limites (0 à {len(header) - 1})."}
        if value_columns is None:
            value_columns = []
            for index in range(len(header)):
                if index == label_column:
                    continue
                values = [
                    _finite_number(row[index])
                    for row in rows
                    if index < len(row)
                ]
                if values and sum(value is not None for value in values) >= max(1, len(values) // 2):
                    value_columns.append(index)
                if len(value_columns) >= _MAX_CHART_COLUMNS:
                    break
        if not value_columns:
            return {"error": "Aucune colonne numérique détectée à tracer."}
        if any(index >= len(header) or index == label_column for index in value_columns):
            return {"error": "Une colonne de valeurs est hors limites ou identique aux étiquettes."}
        await asyncio.to_thread(
            _render_chart,
            header=header,
            rows=rows,
            label_column=label_column,
            value_columns=value_columns,
            chart_type=chart_type,
            title=title,
            output=output,
        )
    except (OSError, csv.Error, ValueError) as exc:
        return {"error": f"Génération du graphique échouée : {exc}"}
    return {
        "success": True,
        "path": str(output),
        "destination": str(output),
        "chart_type": chart_type,
        "series": 1 if chart_type == "pie" else len(value_columns),
        "points": len(rows),
        "message": (
            f"Graphique {chart_type} généré "
            f"({1 if chart_type == 'pie' else len(value_columns)} série(s), "
            f"{len(rows)} points) → {output}"
        ),
    }


def _sqlite_uri(path: Path, *, readonly: bool) -> str:
    normalized = path.resolve().as_posix()
    return f"file:{quote(normalized, safe='/:')}?mode={'ro' if readonly else 'rw'}"


def _mutation_actions() -> set[int]:
    names = {
        "SQLITE_ALTER_TABLE",
        "SQLITE_ANALYZE",
        "SQLITE_CREATE_INDEX",
        "SQLITE_CREATE_TABLE",
        "SQLITE_CREATE_TEMP_INDEX",
        "SQLITE_CREATE_TEMP_TABLE",
        "SQLITE_CREATE_TEMP_TRIGGER",
        "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_CREATE_TRIGGER",
        "SQLITE_CREATE_VIEW",
        "SQLITE_CREATE_VTABLE",
        "SQLITE_DELETE",
        "SQLITE_DROP_INDEX",
        "SQLITE_DROP_TABLE",
        "SQLITE_DROP_TEMP_INDEX",
        "SQLITE_DROP_TEMP_TABLE",
        "SQLITE_DROP_TEMP_TRIGGER",
        "SQLITE_DROP_TEMP_VIEW",
        "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW",
        "SQLITE_DROP_VTABLE",
        "SQLITE_INSERT",
        "SQLITE_REINDEX",
        "SQLITE_UPDATE",
    }
    return {getattr(sqlite3, name) for name in names if hasattr(sqlite3, name)}


_MUTATION_ACTIONS = _mutation_actions()


def _authorizer_state(*, allow_mutation: bool) -> tuple[dict[str, bool], Callable[..., int]]:
    state = {"mutation": False, "forbidden": False}
    attach = {getattr(sqlite3, name, -1) for name in ("SQLITE_ATTACH", "SQLITE_DETACH")}
    function_code = getattr(sqlite3, "SQLITE_FUNCTION", -1)
    pragma_code = getattr(sqlite3, "SQLITE_PRAGMA", -1)

    def authorize(action: int, arg1: str | None, arg2: str | None, _db: str, _trigger: str) -> int:
        if action in attach:
            state["forbidden"] = True
            return sqlite3.SQLITE_DENY
        if action == function_code and str(arg2 or arg1 or "").casefold() == "load_extension":
            state["forbidden"] = True
            return sqlite3.SQLITE_DENY
        if action == pragma_code:
            pragma = str(arg1 or "").casefold()
            if pragma in _BLOCKED_PRAGMAS:
                state["forbidden"] = True
                return sqlite3.SQLITE_DENY
            if arg2 is not None:
                state["mutation"] = True
                return sqlite3.SQLITE_OK if allow_mutation else sqlite3.SQLITE_DENY
        if action in _MUTATION_ACTIONS:
            state["mutation"] = True
            return sqlite3.SQLITE_OK if allow_mutation else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return state, authorize


def _serialize_sql_value(value: object) -> object:
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    return value


def _run_sql(
    path: Path,
    query: str,
    *,
    max_rows: int,
    allow_mutation: bool,
) -> dict[str, Any]:
    connection = sqlite3.connect(
        _sqlite_uri(path, readonly=not allow_mutation),
        uri=True,
        timeout=3.0,
    )
    deadline = time.monotonic() + _SQL_TIMEOUT_SECONDS
    state, authorizer = _authorizer_state(allow_mutation=allow_mutation)
    connection.row_factory = sqlite3.Row
    connection.set_authorizer(authorizer)
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10_000)
    try:
        cursor = connection.execute(query)
        if state["mutation"]:
            connection.commit()
            return {
                "write": True,
                "rows_affected": max(0, cursor.rowcount),
            }
        columns = [description[0] for description in (cursor.description or [])]
        fetched = cursor.fetchmany(max_rows + 1)
        rows = [
            {
                column: _serialize_sql_value(value)
                for column, value in zip(columns, row, strict=False)
            }
            for row in fetched[:max_rows]
        ]
        return {
            "write": False,
            "columns": columns,
            "rows": rows,
            "rows_count": len(rows),
            "truncated": len(fetched) > max_rows,
        }
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.set_progress_handler(None, 0)
        connection.set_authorizer(None)
        connection.close()


def _classify_sql(path: Path, query: str, max_rows: int) -> dict[str, Any]:
    try:
        return _run_sql(path, query, max_rows=max_rows, allow_mutation=False)
    except sqlite3.DatabaseError as exc:
        # Une mutation refusée par l'authorizer est une demande de confirmation,
        # alors qu'ATTACH, load_extension et les PRAGMA dangereux restent interdits.
        state, _ = _authorizer_state(allow_mutation=False)
        del state  # l'état utile est observé dans le second passage ci-dessous
        message = str(exc)
        if "not authorized" not in message.casefold() and "readonly" not in message.casefold():
            raise
        probe = sqlite3.connect(_sqlite_uri(path, readonly=True), uri=True, timeout=3.0)
        observed, authorizer = _authorizer_state(allow_mutation=False)
        probe.set_authorizer(authorizer)
        try:
            probe.execute(query)
        except sqlite3.DatabaseError:
            pass
        finally:
            probe.set_authorizer(None)
            probe.close()
        if observed["forbidden"]:
            return {"forbidden": True}
        if observed["mutation"]:
            return {"mutation": True}
        raise


def _backup_database(path: Path) -> Path:
    backup_dir = path.parent / ".marvin-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_dir / f"{path.name}.{stamp}.bak"
    source = sqlite3.connect(_sqlite_uri(path, readonly=True), uri=True, timeout=3.0)
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
        destination.commit()
    except BaseException:
        destination.close()
        source.close()
        backup.unlink(missing_ok=True)
        raise
    destination.close()
    source.close()
    return backup


async def sqlite_query(args: dict[str, Any]) -> dict[str, Any]:
    path, error = _source_file(args.get("db_path"), suffixes={".db", ".db3", ".sqlite", ".sqlite3"})
    if error or path is None:
        return {"error": error}
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "Paramètre 'query' requis."}
    if len(query) > _MAX_QUERY_LENGTH:
        return {"error": f"Requête limitée à {_MAX_QUERY_LENGTH} caractères."}
    max_rows, error = _int_arg(
        args.get("max_rows"),
        name="max_rows",
        default=100,
        minimum=1,
        maximum=_MAX_SQL_ROWS,
    )
    if error or max_rows is None:
        return {"error": error}
    confirmed = args.get("confirmed", False) is True
    try:
        classified = await asyncio.to_thread(_classify_sql, path, query, max_rows)
        if classified.get("forbidden"):
            return {"error": "Instruction SQLite interdite (ATTACH, extension ou PRAGMA dangereux)."}
        if classified.get("mutation"):
            if not confirmed:
                return {
                    "requiresConfirmation": True,
                    "message": f"Exécuter cette requête d'écriture sur {path.name} ?\n{query[:200]}",
                }
            backup = await asyncio.to_thread(_backup_database, path)
            try:
                result = await asyncio.to_thread(
                    _run_sql,
                    path,
                    query,
                    max_rows=max_rows,
                    allow_mutation=True,
                )
            except BaseException:
                backup.unlink(missing_ok=True)
                raise
            return {
                "success": True,
                "write": True,
                "rows_affected": result["rows_affected"],
                "rollback_path": str(backup),
            }
        return {
            "success": True,
            "db": path.name,
            "query": query[:200],
            "columns": classified["columns"],
            "rows": classified["rows"],
            "rows_count": classified["rows_count"],
            "truncated": classified["truncated"],
        }
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).casefold():
            return {"error": f"Requête interrompue après {_SQL_TIMEOUT_SECONDS:.0f} secondes."}
        return {"error": f"SQLite : {exc}"}
    except sqlite3.DatabaseError as exc:
        return {"error": f"SQLite : {exc}"}
    except OSError as exc:
        return {"error": f"Accès SQLite échoué : {exc}"}


def _inspect_tables(path: Path) -> tuple[list[dict[str, str]], dict[str, list[dict[str, Any]]]]:
    connection = sqlite3.connect(_sqlite_uri(path, readonly=True), uri=True, timeout=3.0)
    try:
        rows = connection.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table','view') ORDER BY name"
        ).fetchall()
        tables = [{"name": str(row[0]), "type": str(row[1])} for row in rows]
        schema: dict[str, list[dict[str, Any]]] = {}
        for table in tables:
            columns = connection.execute(
                'SELECT name, type, "notnull", pk FROM pragma_table_info(?)',
                (table["name"],),
            ).fetchall()
            schema[table["name"]] = [
                {
                    "col": str(column[0]),
                    "type": str(column[1]),
                    "notnull": bool(column[2]),
                    "pk": bool(column[3]),
                }
                for column in columns
            ]
        return tables, schema
    finally:
        connection.close()


async def sqlite_tables(args: dict[str, Any]) -> dict[str, Any]:
    path, error = _source_file(args.get("db_path"), suffixes={".db", ".db3", ".sqlite", ".sqlite3"})
    if error or path is None:
        return {"error": error}
    try:
        tables, schema = await asyncio.to_thread(_inspect_tables, path)
        stat = path.stat()
    except (OSError, sqlite3.DatabaseError) as exc:
        return {"error": f"Inspection SQLite échouée : {exc}"}
    return {
        "success": True,
        "db": path.name,
        "size_kb": round(stat.st_size / 1024, 1),
        "table_count": len(tables),
        "tables": tables,
        "schema": schema,
    }
