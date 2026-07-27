"""Analyse, consultation et documentation des captures de conversation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Awaitable, Callable

import httpx

import cloud_routing
from platform_paths import PATHS as _SYSTEM_PATHS
from tool_domains.ocr import encode_image


_list_screenshots: Callable[..., list[dict]] | None = None
_create_docx: Callable[[dict], Awaitable[dict]] | None = None
_create_pdf: Callable[[dict], Awaitable[dict]] | None = None
_ollama_url = ""
_requester: Callable[..., Awaitable[dict]] | None = None
_MAX_LIST = 500

ANALYZE_PROMPT = (
    "Tu analyses une capture d'écran technique (contexte informatique/administration système). "
    "Réponds en français, en respectant EXACTEMENT ce format à 2 sections :\n"
    "LÉGENDE: <une phrase décrivant ce que montre la capture>\n"
    "TEXTE RELEVÉ: <tout le texte visible dans l'image, transcrit fidèlement : messages, "
    "codes d'erreur, adresses IP, chemins, valeurs de configuration — verbatim, pas de résumé>\n"
    "N'invente rien : si un détail n'est pas lisible, ne le mentionne pas."
)


def configure(
    *,
    list_screenshots: Callable[..., list[dict]],
    ollama_url: str,
    requester: Callable[..., Awaitable[dict]] | None = None,
) -> None:
    global _list_screenshots, _ollama_url, _requester
    _list_screenshots = list_screenshots
    _ollama_url = ollama_url.rstrip("/")
    _requester = requester


def configure_renderers(
    *,
    create_docx: Callable[[dict], Awaitable[dict]],
    create_pdf: Callable[[dict], Awaitable[dict]],
) -> None:
    global _create_docx, _create_pdf
    _create_docx = create_docx
    _create_pdf = create_pdf


def _limit(raw: object, default: int) -> int:
    value = int(raw or default)
    if not 1 <= value <= _MAX_LIST:
        raise ValueError(f"'limit' doit être compris entre 1 et {_MAX_LIST}.")
    return value


def _shots(conversation_id: str | None, limit: int) -> list[dict]:
    if _list_screenshots is None:
        raise RuntimeError("Le domaine Captures n'est pas configuré")
    rows = _list_screenshots(conversation_id, limit=limit)
    return rows if isinstance(rows, list) else []


async def _request_json(*, timeout: float, payload: dict) -> dict:
    if _requester is not None:
        return await _requester(
            "POST", "/api/generate", timeout=timeout, payload=payload
        )
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{_ollama_url}/api/generate", json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Réponse Ollama invalide : objet JSON attendu")
        return data


def _parse_analysis(text: str) -> tuple[str, str]:
    match = re.search(
        r"L[ÉE]GENDE\s*:\s*(.+?)\n\s*TEXTE RELEV[ÉE]\s*:\s*(.+)",
        text,
        re.S | re.I,
    )
    return (
        (match.group(1).strip(), match.group(2).strip())
        if match
        else (text.strip(), "")
    )


async def analyze(resolved_path: str) -> dict:
    """Analyse une capture avec les candidats vision permis par le profil actif."""
    try:
        image_b64, _ = encode_image(Path(resolved_path))
    except (OSError, ValueError) as exc:
        return {"caption": "", "ocr_text": "", "model": None, "error": str(exc)}

    candidates: list[str] = []
    try:
        lockdown = cloud_routing.is_local_only_lockdown()
        cloud_enabled, _ = cloud_routing.get_cloud_config()
        if cloud_enabled and not lockdown:
            candidates = list(cloud_routing.list_vision_candidates())
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    try:
        cloud_only = cloud_routing.is_cloud_only_mode()
    except (OSError, RuntimeError, TypeError, ValueError):
        cloud_only = False
    if not cloud_only:
        if "llava-phi3" not in candidates:
            candidates.append("llava-phi3")
    elif not candidates:
        return {
            "caption": "",
            "ocr_text": "",
            "model": None,
            "error": (
                "Mode Ultra débridé actif : aucun modèle vision cloud disponible; "
                "repli local refusé."
            ),
            "cloud_only": True,
        }

    last_error: Exception | None = None
    for model in dict.fromkeys(candidates):
        try:
            data = await _request_json(
                timeout=60,
                payload={
                    "model": model,
                    "prompt": ANALYZE_PROMPT,
                    "images": [image_b64],
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
            caption, ocr_text = _parse_analysis(
                str(data.get("response") or "").strip()
            )
            if model != "llava-phi3":
                try:
                    cloud_routing.record_model_capability(model, "vision", True)
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass
            return {"caption": caption, "ocr_text": ocr_text, "model": model}
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            if model != "llava-phi3":
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and 400 <= status < 500:
                    try:
                        cloud_routing.record_model_capability(model, "vision", False)
                    except (OSError, RuntimeError, TypeError, ValueError):
                        pass
            last_error = exc
    return {
        "caption": "",
        "ocr_text": "",
        "model": None,
        "error": str(last_error) if last_error else "aucun modèle vision disponible",
    }


async def list_for_conversation(args: dict) -> dict:
    """Liste les captures analysées d'une conversation."""
    try:
        conversation_id = args.get("conversation_id") or args.get("_conversation_id")
        rows = _shots(conversation_id, _limit(args.get("limit"), 100))
        return {
            "success": True,
            "count": len(rows),
            "screenshots": [
                {
                    "id": row["id"],
                    "path": row["path"],
                    "caption": row.get("caption", ""),
                    "ocr_text": row.get("ocr_text", ""),
                    "created_at": row.get("created_at"),
                }
                for row in rows
            ],
        }
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        return {"error": str(exc)}


async def generate_document(args: dict) -> dict:
    """Génère un DOCX ou PDF structuré depuis les captures persistées."""
    try:
        conversation_id = args.get("conversation_id") or args.get("_conversation_id")
        if not conversation_id:
            return {
                "error": (
                    "Aucune conversation_id disponible — cet outil doit être appelé "
                    "depuis une conversation."
                )
            }
        rows = _shots(str(conversation_id), _limit(args.get("limit"), 200))
        if not rows:
            return {
                "error": (
                    "Aucune capture d'écran enregistrée pour cette conversation. "
                    "Demande à l'utilisateur d'attacher ses captures au chat d'abord."
                )
            }
        title = str(args.get("title") or "Documentation technique").strip()
        output_format = str(args.get("format") or "docx").lower().strip()
        if output_format not in {"docx", "pdf"}:
            return {"error": "Format invalide. Utilisez 'docx' ou 'pdf'."}

        parts: list[str] = []
        intro = str(args.get("intro") or "").strip()
        if intro:
            parts.extend((intro, ""))
        for index, row in enumerate(rows, 1):
            caption = str(row.get("caption") or f"Capture {index}").strip()
            path = str(row.get("path") or "").strip()
            if not path:
                return {"error": f"Chemin absent pour la capture {index}."}
            parts.extend((f"## {index}. {caption}", f"![{caption}]({path})"))
            ocr_text = str(row.get("ocr_text") or "").strip()
            if ocr_text:
                parts.extend(("**Texte relevé :**", f"```\n{ocr_text}\n```"))
            parts.append("")

        output_path = str(args.get("path") or "").strip()
        if not output_path:
            safe_title = (
                re.sub(r"[^\w\- ]", "", title).strip().replace(" ", "_")[:60]
                or "documentation"
            )
            output_path = str(
                Path(_SYSTEM_PATHS["desktop"]) / f"{safe_title}.{output_format}"
            )
        call_args = {
            "path": output_path,
            "title": title,
            "content": "\n".join(parts),
            "toc": True,
        }
        for key in ("author", "subtitle"):
            if args.get(key):
                call_args[key] = args[key]

        renderer = _create_pdf if output_format == "pdf" else _create_docx
        if renderer is None:
            return {"error": "Le moteur documentaire des captures n'est pas configuré."}
        result = await renderer(call_args)
        if result.get("success"):
            result["screenshots_used"] = len(rows)
        return result
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        return {"error": str(exc)}
