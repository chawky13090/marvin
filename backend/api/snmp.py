"""Administration locale des profils SNMPv3 protégés par DPAPI."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from repositories.snmp_profiles import repository
from tool_domains.network import execute_net_snmp_query
import snmp_profile_vault


router = APIRouter(prefix="/api/snmp-profiles", tags=["snmp"])


class SNMPProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    username: str = Field(min_length=1, max_length=64)
    auth_key: str = Field(min_length=8, max_length=1024)
    priv_key: str = Field(default="", max_length=1024)
    auth_protocol: str = Field(default="sha256", pattern="^(sha1|sha256)$")
    priv_protocol: str = Field(default="aes128", pattern="^(none|aes128)$")
    context_name: str = Field(default="", max_length=64)
    port: int = Field(default=161, ge=1, le=65535)


class SNMPProfileTest(BaseModel):
    host: str = Field(min_length=1, max_length=253)


@router.get("")
async def list_profiles():
    return {"profiles": repository.list(), "storage": "windows_dpapi_current_user"}


@router.post("")
async def create_profile(body: SNMPProfileCreate):
    try:
        return repository.create(**body.model_dump())
    except snmp_profile_vault.SNMPProfileVaultError as exc:
        raise HTTPException(status_code=503, detail="Le coffre sécurisé Windows est indisponible.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str):
    try:
        repository.delete(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True}


@router.post("/{profile_id}/test")
async def test_profile(profile_id: str, body: SNMPProfileTest):
    result = await execute_net_snmp_query({"host": body.host, "profile_id": profile_id, "action": "sysinfo"})
    if result.get("error"):
        raise HTTPException(status_code=422, detail=str(result["error"]))
    return result
