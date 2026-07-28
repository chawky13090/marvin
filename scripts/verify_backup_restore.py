"""Restaure un snapshot Marvin réel dans une base temporaire isolée."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import backup
from backup import BackupService


def _logical_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    connection = sqlite3.connect(path)
    try:
        for statement in connection.iterdump():
            digest.update(statement.encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vérifie une restauration sans toucher secretary.db."
    )
    parser.add_argument("--filename")
    arguments = parser.parse_args()

    entries = backup.list_backups()
    selected = next(
        (
            entry
            for entry in entries
            if arguments.filename is None
            or entry["filename"] == arguments.filename
        ),
        None,
    )
    if selected is None:
        raise SystemExit("Sauvegarde demandée introuvable.")
    source = Path(selected["path"])
    sidecar = source.with_suffix(source.suffix + ".sha256")
    if not sidecar.is_file():
        raise SystemExit(
            "La preuve isolée exige une sauvegarde v2.419 avec SHA-256."
        )

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        isolated_database = root / "secretary-restored.db"
        isolated_backups = root / "backups"
        isolated_backups.mkdir()
        copied_source = isolated_backups / source.name
        shutil.copy2(source, copied_source)
        shutil.copy2(
            sidecar,
            copied_source.with_suffix(copied_source.suffix + ".sha256"),
        )
        connection = sqlite3.connect(isolated_database)
        try:
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker VALUES ('before-restore')")
            connection.commit()
        finally:
            connection.close()

        service = BackupService(
            isolated_database,
            isolated_backups,
            keep_last=4,
            event_logger=lambda *_: None,
        )
        restored = service.restore(source.name)
        if not restored.get("success"):
            raise SystemExit(
                f"Restauration isolée échouée: {restored.get('error_code')}"
            )
        source_hash = _logical_sha256(copied_source)
        restored_hash = _logical_sha256(isolated_database)
        if source_hash != restored_hash:
            raise SystemExit(
                "Le contenu logique restauré diffère de la source."
            )
        if restored["foreign_key_violations"] < 0:
            raise SystemExit("Compteur relationnel invalide.")
        print(
            "Restauration isolée OK - intégrité SQLite, contenu logique exact, "
            f"{restored['foreign_key_violations']} violation(s) FK historique(s)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
