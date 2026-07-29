"""Benchmark local reproductible de la frontière SQLite de Marvin, sans contenu métier."""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import DB_PATH
from db_connection import get_conn


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * fraction) - 1))
    return round(ordered[index], 4)


def _latencies(operation, iterations: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)
    return {
        "p50_ms": round(statistics.median(samples), 4),
        "p95_ms": _percentile(samples, 0.95),
        "max_ms": round(max(samples), 4),
    }


def _read_snapshot(path: Path) -> dict:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        tables = [
            row[0]
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"""
            )
        ]
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        latency = _latencies(
            lambda: connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall(),
            500,
        )
        return {
            "sqlite_version": sqlite3.sqlite_version,
            "database_bytes": path.stat().st_size,
            "tables": len(tables),
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
            "integrity": integrity,
            "schema_read_500": latency,
        }
    finally:
        connection.close()


def _write_worker(path: Path, worker: int, iterations: int) -> None:
    for index in range(iterations):
        connection = get_conn(path)
        try:
            connection.execute(
                "INSERT INTO benchmark_events(worker, sequence, payload) VALUES (?, ?, ?)",
                (worker, index, "x" * 256),
            )
            connection.commit()
        finally:
            connection.close()


def _write_benchmark() -> dict:
    with tempfile.TemporaryDirectory(prefix="marvin-persistence-benchmark-") as directory:
        path = Path(directory) / "benchmark.db"
        connection = get_conn(path)
        try:
            connection.execute(
                """CREATE TABLE benchmark_events(
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       worker INTEGER NOT NULL,
                       sequence INTEGER NOT NULL,
                       payload TEXT NOT NULL,
                       UNIQUE(worker, sequence)
                   )"""
            )
            connection.commit()
        finally:
            connection.close()
        workers = 4
        per_worker = 100
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_write_worker, path, worker, per_worker)
                for worker in range(workers)
            ]
            for future in futures:
                future.result()
        elapsed = time.perf_counter() - started
        connection = get_conn(path)
        try:
            rows = connection.execute("SELECT COUNT(*) FROM benchmark_events").fetchone()[0]
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
        return {
            "workers": workers,
            "committed_transactions": rows,
            "elapsed_ms": round(elapsed * 1000, 2),
            "transactions_per_second": round(rows / elapsed, 2),
            "integrity": integrity,
        }


def main() -> int:
    path = Path(DB_PATH)
    if not path.is_file():
        raise SystemExit("Base Marvin introuvable.")
    result = {
        "scope": "aggregate_only_no_business_content",
        "current_database": _read_snapshot(path),
        "synthetic_concurrent_writes": _write_benchmark(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (
        result["current_database"]["integrity"] == "ok"
        and result["synthetic_concurrent_writes"]["integrity"] == "ok"
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
