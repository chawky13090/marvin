"""
Marvin — serveur MCP (Model Context Protocol), v2.103.

Expose les 294 outils déjà vérifiés de Marvin (winget, PC, fichiers, réseau,
calendrier, etc.) à n'importe quel client MCP (Claude Desktop, Cursor…) via
la transport stdio standard — le pattern normal pour un serveur MCP local :
le client MCP LANCE ce script comme sous-processus et lui parle en JSON-RPC
sur stdin/stdout.

⚠️ CHOIX DE SÉCURITÉ DÉLIBÉRÉ — lire avant de modifier :
  1. Ce script n'importe JAMAIS `tools.py` ni `database.py` directement.
     Qdrant est mono-process (verrou) — un import direct depuis un second
     process risquerait `AlreadyLocked` avec le backend principal déjà lancé
     (piège documenté dans CLAUDE.md §4). Ce serveur est un PROXY RÉSEAU PUR
     vers le backend Marvin déjà démarré (:8005) — rien d'autre.
  2. L'exécution passe par `/api/mcp/execute`, PAS `/api/tools` (qui force la
     confirmation des outils dangereux car pensé pour des boutons UI qui ont
     déjà demandé confirmation). `/api/mcp/execute` respecte le niveau de
     permission ACTUEL de Marvin (réglé dans Paramètres) : en Sécurisé/Standard,
     un outil dangereux renvoie `requiresConfirmation` que le client MCP peut
     re-soumettre avec confirmed=true si SON utilisateur approuve — jamais
     d'exécution automatique silencieuse en dehors du mode Expert.
  3. Ce serveur ne démarre QUE si un client MCP le lance explicitement (ajout
     manuel dans la config Claude Desktop / Cursor) — aucun port ouvert par
     défaut, aucune découverte automatique.

Config Claude Desktop (claude_desktop_config.json) :
  {
    "mcpServers": {
      "marvin": {
        "command": "C:\\Users\\Chawb\\secretary-ai\\backend\\.venv\\Scripts\\python.exe",
        "args": ["C:\\Users\\Chawb\\secretary-ai\\backend\\mcp_server.py"]
      }
    }
  }
Prérequis : le backend Marvin (uvicorn main:app, port 8005) doit déjà tourner.
"""
import os
import time
import anyio
import httpx
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

BACKEND_URL = os.environ.get("MARVIN_BACKEND_URL", "http://127.0.0.1:8005")

server = Server("marvin", version="1.0.0", instructions=(
    "Marvin — assistant IA local pour technicien informatique. Expose les outils "
    "PC/fichiers/réseau/calendrier/etc. déjà vérifiés de Marvin. Le backend Marvin "
    "doit être démarré (uvicorn main:app --port 8005) pour que ces outils répondent."
))

_tool_cache: list[types.Tool] | None = None
_tool_cache_ts: float = 0.0
_TOOL_CACHE_TTL = 60.0  # les 294 outils ne changent pas en cours de session


async def _fetch_tools() -> list[types.Tool]:
    global _tool_cache, _tool_cache_ts
    if _tool_cache is not None and (time.monotonic() - _tool_cache_ts) < _TOOL_CACHE_TTL:
        return _tool_cache
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BACKEND_URL}/api/tools/list")
        r.raise_for_status()
        data = r.json()
    tools = []
    for spec in data.get("tools", []):
        fn = spec.get("function", {})
        name = fn.get("name")
        if not name:
            continue
        tools.append(types.Tool(
            name=name,
            description=(fn.get("description") or "")[:1024],
            inputSchema=fn.get("parameters") or {"type": "object", "properties": {}},
        ))
    _tool_cache = tools
    _tool_cache_ts = time.monotonic()
    return tools


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    try:
        return await _fetch_tools()
    except Exception as e:
        # Backend Marvin injoignable — remonter un catalogue vide plutôt que
        # planter le serveur MCP (le client affichera juste "aucun outil").
        return [types.Tool(
            name="marvin_backend_unreachable",
            description=f"Backend Marvin injoignable sur {BACKEND_URL} ({e}). Lancez start.bat puis reconnectez ce serveur MCP.",
            inputSchema={"type": "object", "properties": {}},
        )]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "marvin_backend_unreachable":
        return [types.TextContent(type="text", text=f"Backend Marvin injoignable sur {BACKEND_URL}.")]
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:  # certains outils sont longs (winget upgrade --all…)
            r = await client.post(f"{BACKEND_URL}/api/mcp/execute", json={
                "toolName": name, "args": arguments or {},
            })
        if r.status_code == 404:
            return [types.TextContent(type="text", text=f"Outil « {name} » introuvable côté Marvin.")]
        r.raise_for_status()
        result = r.json().get("result", {})
        import json as _json
        return [types.TextContent(type="text", text=_json.dumps(result, ensure_ascii=False, default=str))]
    except httpx.ConnectError:
        return [types.TextContent(type="text", text=(
            f"❌ Impossible de joindre le backend Marvin sur {BACKEND_URL}. "
            f"Lancez start.bat (ou uvicorn main:app --port 8005) puis réessayez."
        ))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"❌ Erreur : {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
