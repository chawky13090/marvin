"""Contrat API du compte de service Google protégé."""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api import connections
import google_service_account_vault as vault


async def main() -> None:
    upload = UploadFile(filename="google.json", file=io.BytesIO(b"fixture"))
    with patch.object(
        connections.google_service_account_vault,
        "store",
        return_value={"client_email": "marvin@example.iam.gserviceaccount.com"},
    ) as store:
        result = await connections.upload_google_service_account(upload)
    assert result["success"] is True
    assert result["storage"] == "windows_dpapi_current_user"
    store.assert_called_once_with(b"fixture")

    invalid = UploadFile(filename="invalid.json", file=io.BytesIO(b"invalid"))
    with patch.object(
        connections.google_service_account_vault,
        "store",
        side_effect=vault.GoogleServiceAccountVaultError("Document invalide."),
    ):
        try:
            await connections.upload_google_service_account(invalid)
        except HTTPException as exc:
            assert exc.status_code == 400
            assert exc.detail == "Document invalide."
        else:
            raise AssertionError("Une clé Google invalide doit être refusée.")

    with patch.object(connections.google_service_account_vault, "delete") as delete:
        removed = await connections.delete_google_service_account()
    assert removed == {"success": True, "storage": "windows_dpapi_current_user"}
    delete.assert_called_once_with()

    with patch.object(
        connections.google_service_account_vault,
        "delete",
        side_effect=vault.GoogleServiceAccountVaultError("Suppression incomplète."),
    ):
        try:
            await connections.delete_google_service_account()
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Une suppression partielle ne doit pas être annoncée comme réussie.")


if __name__ == "__main__":
    asyncio.run(main())
    print("Google Service Account API OK - upload borné, DPAPI et suppression fail-closed.")
