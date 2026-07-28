"""Régressions du domaine d'inspection Git en lecture seule."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from tool_domains import git_repository


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-git-") as temporary:
        repo = Path(temporary)
        git_repository.configure(resolve_path=lambda raw: str(Path(raw).resolve()))
        _git(repo, "init", "-q")
        _git(repo, "config", "user.name", "Marvin Test")
        _git(repo, "config", "user.email", "marvin@example.invalid")
        (repo / "proof.txt").write_text("initial\n", encoding="utf-8")
        _git(repo, "add", "proof.txt")
        _git(repo, "commit", "-q", "-m", "initial proof")

        status = await git_repository.git_info(
            {"path": str(repo), "action": "status"}
        )
        assert status["success"] is True and status["clean"] is True
        assert status["branch"]

        log = await git_repository.git_info(
            {"path": str(repo), "action": "log", "count": 1}
        )
        assert log["count"] == 1
        assert len(log["commits"][0]["hash"]) == 40
        assert log["commits"][0]["message"] == "initial proof"

        branches = await git_repository.git_info(
            {"path": str(repo), "action": "branches"}
        )
        assert branches["current"] == status["branch"]
        assert status["branch"] in branches["branches"]

        (repo / "proof.txt").write_text("changed\n", encoding="utf-8")
        changed = await git_repository.git_info(
            {"path": str(repo), "action": "status"}
        )
        assert changed["clean"] is False and changed["changes_count"] == 1
        diff = await git_repository.git_info(
            {"path": str(repo), "action": "diff"}
        )
        assert "proof.txt" in diff["diff_stat"]

        assert "count" in (
            await git_repository.git_info(
                {"path": str(repo), "action": "log", "count": 101}
            )
        )["error"]
        outside = await git_repository.git_info(
            {"path": str(repo.parent), "action": "status"}
        )
        assert "pas un dépôt" in outside["error"]

    git_repository.configure(resolve_path=tools._resolve_path)
    assert tools.execute_git_info is git_repository.git_info


if __name__ == "__main__":
    asyncio.run(main())
    print("Git Repository OK - porcelain stable, bornes et façade.")
