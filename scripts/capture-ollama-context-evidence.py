"""Capture atomique de la preuve de contexte exigée par Forge Windows.

Ce script n'effectue aucune inférence et ne charge aucun modèle. Un modèle local
doit donc être préchauffé explicitement par la campagne avant la capture.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS_ROOT = (ROOT / "benchmarks" / "windows-operator" / "campaigns").resolve()
sys.path.insert(0, str(ROOT / "backend"))

import ollama_context_runtime


def _git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and len(value) == 40 else None


def _safe_output(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    resolved = path.resolve()
    try:
        resolved.relative_to(CAMPAIGNS_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"La preuve doit rester sous {CAMPAIGNS_ROOT}."
        ) from exc
    if resolved.suffix.casefold() != ".json":
        raise ValueError("La preuve doit utiliser l'extension .json.")
    return resolved


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def _run(args: argparse.Namespace) -> int:
    evidence = await ollama_context_runtime.inspect_context_runtime(
        args.model,
        minimum_tokens=args.minimum_tokens,
        recommended_tokens=args.recommended_tokens,
    )
    report = {
        "schema": "marvin.ollama-context-evidence/1.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "benchmark_contract": "windows-operator/v1",
        "evidence": evidence,
    }
    output = _safe_output(args.output)
    _write_atomic(output, report)
    print(json.dumps({"output": str(output), "status": evidence["status"]}, ensure_ascii=False))
    return 0 if evidence["status"] == "verified" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True, help="Tag Ollama exact à vérifier.")
    parser.add_argument("--output", required=True, help="JSON sous benchmarks/windows-operator/campaigns/.")
    parser.add_argument("--minimum-tokens", type=int, default=32_768)
    parser.add_argument("--recommended-tokens", type=int, default=65_536)
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except (OSError, ValueError) as exc:
        print(f"Erreur de capture : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
