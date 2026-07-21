"""Repository Intelligence and isolated worktree regressions."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import coding_mission
import coding_workspace
import repository_intelligence
import windows_validation


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr)
    return completed.stdout.strip()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-repo-intelligence-") as temporary:
        base = Path(temporary)
        repository = base / "source"
        repository.mkdir()
        (repository / "AGENTS.md").write_text("# Rules\nRun npm test.\n", encoding="utf-8")
        (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
        (repository / "package.json").write_text(
            '{"scripts":{"test":"node --test","lint":"eslint ."}}', encoding="utf-8",
        )
        (repository / "package-lock.json").write_text('{"lockfileVersion":3}', encoding="utf-8")
        (repository / ".env").write_text("TOKEN=must-not-leak", encoding="utf-8")
        source = repository / "src"
        source.mkdir()
        (source / "AGENTS.md").write_text("# Nested\nUse strict mode.\n", encoding="utf-8")
        (source / "app.js").write_text("'use strict';\n", encoding="utf-8")
        git(repository, "init")
        git(repository, "config", "user.name", "Marvin Test")
        git(repository, "config", "user.email", "marvin-test@example.invalid")
        git(repository, "add", ".")
        git(repository, "commit", "-m", "initial")

        contract = repository_intelligence.inspect(str(source))
        assert contract["root"] == str(repository.resolve())
        assert contract["languages"] == ["javascript"]
        assert contract["package_scripts"]["test"] == "node --test"
        assert [item["path"] for item in contract["instructions"]] == ["AGENTS.md", "src/AGENTS.md"]
        assert "must-not-leak" not in str(contract)
        assert contract["git"]["dirty"] is False
        context = repository_intelligence.context(str(repository), "modifier src app javascript")
        assert "TRUSTED PROJECT INSTRUCTIONS" in context["context"]
        assert "UNTRUSTED_REPOSITORY_FILE" in context["context"]
        assert "must-not-leak" not in context["context"]

        old_missions, old_workspaces = coding_mission.ROOT, coding_workspace.ROOT
        coding_mission.ROOT = base / "missions"
        coding_workspace.ROOT = base / "workspaces"
        try:
            mission = coding_mission.create(
                "Modifier app.js", repository={"root": contract["root"]}, autonomy="autonomous",
            )
            workspace = coding_workspace.create(mission["id"], str(repository), confirmed=True)
            worktree = Path(workspace["worktree_root"])
            assert worktree.is_dir() and workspace["branch"].startswith("marvin/mission-")
            (worktree / "src" / "app.js").write_text("'use strict';\nconsole.log('isolated');\n", encoding="utf-8")
            state = coding_workspace.status(mission["id"])
            assert state["dirty"] is True and state["changed_count"] == 1
            assert "isolated" in coding_workspace.diff(mission["id"])["patch"]
            assert "isolated" not in (repository / "src" / "app.js").read_text(encoding="utf-8")
            applied = coding_workspace.apply_files(
                mission["id"], {"src/new.js": "export const ok = true;\n"}, max_files_changed=3,
            )
            assert applied["applied"] is True
            assert (worktree / "src" / "new.js").is_file()
            try:
                coding_workspace.apply_files(
                    mission["id"], {".git/config": "forbidden"}, max_files_changed=3,
                )
            except coding_workspace.WorkspaceError:
                pass
            else:
                raise AssertionError("Les métadonnées Git ne doivent jamais être modifiables.")
        finally:
            coding_mission.ROOT, coding_workspace.ROOT = old_missions, old_workspaces

        assert windows_validation.route(["install.msi"])["required_backend"] == "hyperv_checkpoint_vm"
        assert windows_validation.route(["Driver/device.inf"])["workload"] == "driver"
        assert windows_validation.route(["app.csproj"], "application WPF")["required_backend"] == "windows_gui_vm"
        assert windows_validation.route(["main.ps1"])["required_backend"] == "windows_sandbox_powershell"
    print("Repository Intelligence OK - règles hiérarchiques, secrets exclus, worktree isolé et routage Windows strict.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
