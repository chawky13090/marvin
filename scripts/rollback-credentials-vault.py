"""Rollback contrôlé des secrets globaux DPAPI vers l'ancien stockage SQLite."""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import credentials_manager
from config import BACKEND_PORT


def backend_is_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.3)
        return client.connect_ex(("127.0.0.1", int(BACKEND_PORT))) == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Réhydrate temporairement les secrets globaux en clair dans SQLite "
            "avant une réversion vers une version antérieure à 2.401."
        )
    )
    parser.add_argument(
        "--confirm-plaintext-rollback",
        action="store_true",
        help="Confirme explicitement la dégradation de la protection au repos.",
    )
    arguments = parser.parse_args()
    if not arguments.confirm_plaintext_rollback:
        parser.error("L'option --confirm-plaintext-rollback est obligatoire.")
    if backend_is_running():
        print(
            "ECHEC : arrêtez Marvin avant le rollback pour éviter une migration concurrente.",
            file=sys.stderr,
        )
        return 2
    result = credentials_manager.restore_legacy_plaintext(
        confirmed=True,
        delete_protected=True,
    )
    print(
        f"Rollback préparé : {result['restored']} secret(s) restauré(s), "
        f"{result['absent']} absent(s). Aucune valeur n'a été affichée."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
