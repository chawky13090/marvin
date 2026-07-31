"""Regression : file_delete envoie a la Corbeille par defaut (v2.524).

Avant cette tranche, `filesystem.delete` appelait `shutil.rmtree`/`unlink`
inconditionnellement : une confirmation de chat pouvait produire une suppression
definitive et irrecuperable. Ces tests verifient, en conditions reelles (vrais
fichiers, vraie Corbeille Windows), que :
  - la Corbeille est le comportement par defaut ;
  - `permanent=true` reste disponible et son message de confirmation le dit sans
    ambiguite ;
  - un chemin inexistant ou un module absent ne provoquent jamais une suppression
    definitive silencieuse.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tool_domains import filesystem as fs

fs.configure(resolve_path=lambda p: p)


def _write(tmp: Path, name: str) -> str:
    p = tmp / name
    p.write_text("contenu de test", encoding="utf-8")
    return str(p)


async def _check_confirmation_messages(tmp: Path) -> None:
    target = _write(tmp, "a.txt")
    r = await fs.delete({"path": target})
    assert r["requiresConfirmation"] is True
    assert "Corbeille" in r["message"], r
    assert "définitivement" not in r["message"]

    r = await fs.delete({"path": target, "permanent": True})
    assert r["requiresConfirmation"] is True
    assert "définitivement" in r["message"], r


async def _check_trash_is_default_and_reversible(tmp: Path) -> None:
    target = _write(tmp, "b.txt")
    r = await fs.delete({"path": target, "confirmed": True})
    assert r.get("success") is True, r
    assert r.get("permanent") is False, r
    assert not os.path.exists(target), "le fichier doit disparaitre de son dossier d'origine"


async def _check_permanent_requires_explicit_flag(tmp: Path) -> None:
    target = _write(tmp, "c.txt")
    r = await fs.delete({"path": target, "confirmed": True, "permanent": True})
    assert r.get("success") is True, r
    assert r.get("permanent") is True, r
    assert not os.path.exists(target)


async def _check_missing_path_is_an_error(tmp: Path) -> None:
    r = await fs.delete({"path": str(tmp / "absent.txt"), "confirmed": True})
    assert "error" in r
    assert r.get("success") is not True


async def _check_missing_module_never_falls_back_to_permanent(tmp: Path) -> None:
    """Si send2trash est indisponible, ne JAMAIS supprimer definitivement en silence."""
    target = _write(tmp, "d.txt")
    original_import = fs.__builtins__["__import__"] if isinstance(fs.__builtins__, dict) \
        else fs.__builtins__.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "send2trash":
            raise ModuleNotFoundError("simulated absence")
        return original_import(name, *args, **kwargs)

    import builtins
    real_import = builtins.__import__
    builtins.__import__ = _blocked_import
    try:
        r = await fs.delete({"path": target, "confirmed": True})
    finally:
        builtins.__import__ = real_import

    assert "error" in r, r
    assert r.get("success") is not True, "un module manquant ne doit jamais supprimer definitivement"
    assert os.path.exists(target), "le fichier doit rester intact si la Corbeille echoue"


async def _run_all() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        await _check_confirmation_messages(tmp)
        await _check_trash_is_default_and_reversible(tmp)
        await _check_permanent_requires_explicit_flag(tmp)
        await _check_missing_path_is_an_error(tmp)
        await _check_missing_module_never_falls_back_to_permanent(tmp)


def main() -> int:
    asyncio.run(_run_all())
    print(
        "File Delete Trash OK - Corbeille par defaut, suppression definitive "
        "explicite, aucun repli silencieux."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
