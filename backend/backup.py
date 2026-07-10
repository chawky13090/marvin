"""
Sauvegarde automatique de data/secretary.db (v2.111).

Né d'un incident réel : pendant une session de tests, une conversation utilisateur a été
supprimée par erreur (mauvais ciblage d'un clic UI automatisé) et il n'existait AUCUNE
sauvegarde pour la récupérer. Ce module comble ce trou.

Utilise l'API de sauvegarde native de SQLite (`sqlite3.Connection.backup`) plutôt qu'une
copie de fichier brute : la base est en mode WAL (écritures actives possibles pendant la
sauvegarde) — une copie fichier-à-fichier pourrait capturer un état incohérent entre
secretary.db et son .wal. L'API backup() gère ça correctement (verrouillage cohérent,
copie page par page), y compris avec le backend actif dessus.
"""
import sqlite3
import time
from pathlib import Path

from config import DB_PATH, DATA_DIR

BACKUP_DIR = DATA_DIR / "backups"
KEEP_LAST = 14  # nombre de sauvegardes conservées (rotation)


def create_backup() -> dict:
    """Crée une sauvegarde horodatée de secretary.db. Best-effort : ne lève jamais."""
    try:
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dest_path = BACKUP_DIR / f"secretary_{stamp}.db"

        src = sqlite3.connect(DB_PATH)
        dest = sqlite3.connect(str(dest_path))
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()

        size_kb = round(dest_path.stat().st_size / 1024, 1)
        _prune_old_backups()
        return {"success": True, "path": str(dest_path), "size_kb": size_kb}
    except Exception as e:
        return {"error": str(e)}


def _prune_old_backups():
    """Garde les KEEP_LAST sauvegardes les plus récentes, supprime le reste."""
    backups = sorted(BACKUP_DIR.glob("secretary_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[KEEP_LAST:]:
        try:
            old.unlink()
        except Exception:
            pass


def restore_backup(filename: str) -> dict:
    """Restaure une sauvegarde par-dessus data/secretary.db (v2.111bis).

    Sécurités : (1) le nom de fichier est validé contre BACKUP_DIR (empêche toute
    traversée de chemin) ; (2) une sauvegarde de l'état ACTUEL est prise avant la
    restauration, pour que la restauration elle-même soit réversible en cas d'erreur ;
    (3) utilise l'API backup() SQLite (copie page par page dans la base live, gérée par
    le verrouillage SQLite natif) plutôt qu'un remplacement de fichier brut."""
    try:
        backup_path = BACKUP_DIR / filename
        # Résolution + vérification stricte : le fichier doit être DANS BACKUP_DIR.
        if backup_path.resolve().parent != BACKUP_DIR.resolve():
            return {"error": "Nom de fichier de sauvegarde invalide."}
        if not backup_path.exists():
            return {"error": f"Sauvegarde introuvable : {filename}"}

        pre_restore = create_backup()  # filet de sécurité : annule la restauration si besoin

        src = sqlite3.connect(str(backup_path))
        dest = sqlite3.connect(DB_PATH)
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()

        return {"success": True, "restored_from": filename, "pre_restore_backup": pre_restore.get("path")}
    except Exception as e:
        return {"error": str(e)}


def list_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    backups = sorted(BACKUP_DIR.glob("secretary_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "filename": p.name,
            "path": str(p),
            "size_kb": round(p.stat().st_size / 1024, 1),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
        }
        for p in backups
    ]
