"""Inspection Git déterministe et bornée, sans shell ni mutation du dépôt."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


_resolver: Callable[[str], str] | None = None
_MAX_OUTPUT = 200_000


def configure(*, resolve_path: Callable[[str], str]) -> None:
    global _resolver
    _resolver = resolve_path


def _resolve(raw: str) -> Path:
    if _resolver is None:
        raise RuntimeError("Le domaine Git n'est pas configuré.")
    return Path(_resolver(raw)).resolve()


def _run(repo: Path, arguments: list[str], timeout: float = 15.0) -> tuple[str, str, int, bool]:
    environment = {
        **os.environ,
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C.UTF-8",
    }
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                ["git", "-C", str(repo), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Git a dépassé le délai de 15 secondes.") from exc
        stdout.seek(0)
        stderr.seek(0)
        raw_stdout = stdout.read(_MAX_OUTPUT + 1)
        raw_stderr = stderr.read(20_001)
    truncated = len(raw_stdout) > _MAX_OUTPUT
    return (
        raw_stdout[:_MAX_OUTPUT].decode("utf-8", errors="replace").strip(),
        raw_stderr[:20_000].decode("utf-8", errors="replace").strip(),
        completed.returncode,
        truncated,
    )


async def git_info(args: dict) -> dict:
    raw_path = str(args.get("path") or ".").strip() or "."
    action = str(args.get("action") or "status").strip().lower()
    if action not in {"status", "log", "branches", "diff"}:
        return {
            "error": (
                f"Action inconnue : {action}. Valeurs : status, log, branches, diff"
            )
        }
    try:
        repo = _resolve(raw_path)
        if not repo.is_dir():
            return {"error": f"Dossier introuvable : {repo}"}
        probe, error, return_code, _ = await asyncio.to_thread(
            _run, repo, ["rev-parse", "--is-inside-work-tree"]
        )
        if return_code != 0 or probe != "true":
            return {
                "error": (
                    "Ce dossier n'est pas un dépôt Git."
                    + (f" {error[:500]}" if error else "")
                )
            }

        if action == "status":
            output, error, return_code, truncated = await asyncio.to_thread(
                _run,
                repo,
                ["status", "--porcelain=v1", "--branch", "--untracked-files=normal"],
            )
            if return_code != 0:
                raise RuntimeError(error or "Impossible de lire le statut Git.")
            lines = output.splitlines()
            branch_line = lines[0] if lines and lines[0].startswith("## ") else ""
            changes = [line for line in lines[1 if branch_line else 0:] if line.strip()]
            branch = (
                branch_line[3:].split("...", 1)[0].strip()
                if branch_line
                else ""
            )
            return {
                "success": True,
                "repo": str(repo),
                "branch": branch,
                "changes_count": len(changes),
                "changes": changes[:50],
                "changes_truncated": truncated or len(changes) > 50,
                "clean": not changes,
            }

        if action == "log":
            count = int(args.get("count", 10))
            if not 1 <= count <= 100:
                raise ValueError("'count' doit être compris entre 1 et 100.")
            output, error, return_code, truncated = await asyncio.to_thread(
                _run,
                repo,
                [
                    "log",
                    f"--max-count={count}",
                    "--format=%H%x00%s",
                    "--no-color",
                ],
            )
            if return_code != 0:
                raise RuntimeError(error or "Impossible de lire le journal Git.")
            commits = []
            for line in output.splitlines():
                commit_hash, separator, message = line.partition("\0")
                if separator:
                    commits.append({"hash": commit_hash, "message": message})
            return {
                "success": True,
                "repo": str(repo),
                "commits": commits,
                "count": len(commits),
                "truncated": truncated,
            }

        if action == "branches":
            output, error, return_code, truncated = await asyncio.to_thread(
                _run,
                repo,
                [
                    "for-each-ref",
                    "--format=%(refname:short)",
                    "refs/heads",
                    "refs/remotes",
                ],
            )
            if return_code != 0:
                raise RuntimeError(error or "Impossible de lister les branches.")
            current, _, current_code, _ = await asyncio.to_thread(
                _run, repo, ["symbolic-ref", "--quiet", "--short", "HEAD"]
            )
            branches = [line for line in output.splitlines() if line][:200]
            return {
                "success": True,
                "repo": str(repo),
                "current": current if current_code == 0 else "",
                "branches": branches,
                "branches_truncated": truncated or len(output.splitlines()) > 200,
            }

        output, error, return_code, truncated = await asyncio.to_thread(
            _run, repo, ["diff", "--stat", "--no-color", "--"]
        )
        if return_code != 0:
            raise RuntimeError(error or "Impossible de lire le diff Git.")
        return {
            "success": True,
            "repo": str(repo),
            "diff_stat": output or "(aucune modification)",
            "truncated": truncated,
        }
    except FileNotFoundError:
        return {"error": "Git n'est pas installé ou est introuvable dans PATH."}
    except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
        return {"error": str(exc)}
