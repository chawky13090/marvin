"""Execution deterministe des outils du moteur agentique Marvin.

Ce module constitue la frontiere entre la decision du LLM et les actions reelles :
resolution dans le registre, recus idempotents, capture d'erreur et normalisation des
appels d'outils emis sous forme textuelle. Il ne decide ni du modele ni de la strategie.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import uuid
from collections.abc import Mapping
from typing import Any

from action_replay import execute_once, should_guard
from config import DANGEROUS_TOOLS
from tools import TOOLS_REGISTRY


_LOGGER = logging.getLogger(__name__)


def log_tool_exception(
    tool_name: str,
    tool_args: dict[str, Any],
    ex: Exception,
    conversation_id: str | None,
) -> dict[str, str]:
    """Journalise une panne d'outil sans exposer arguments, exception ou pile."""
    incident = uuid.uuid4().hex
    argument_keys = sorted(str(key)[:80] for key in tool_args)[:50]
    argument_shape_hash = hashlib.sha256(
        json.dumps(argument_keys, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    try:
        import bug_log

        bug_log.log_bug(
            "tool_exception",
            "Un exécuteur d'outil a levé une exception interne.",
            context={
                "error_type": type(ex).__name__,
                "incident": incident,
                "argument_count": len(tool_args),
                "argument_shape_hash": argument_shape_hash,
            },
            conversation_id=conversation_id,
            tool_name=tool_name,
        )
    except Exception as log_error:
        _LOGGER.warning(
            "tool_exception_log_unavailable error_type=%s incident=%s",
            type(log_error).__name__,
            incident,
        )
    return {
        "error": f"L'outil a rencontré une erreur interne. Incident : {incident}.",
        "incident": incident,
    }


async def execute_registered_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    conversation_id: str | None,
    request_id: str | None,
    *,
    registry: Mapping[str, Any] | None = None,
    client_idempotency_key: str | None = None,
) -> Any:
    """Execute un outil derriere le recu idempotent des actions a effet de bord.

    ``registry`` est injectable pour les tests et les futurs runtimes, tout en gardant
    le registre historique comme valeur de production.
    """
    active_registry = TOOLS_REGISTRY if registry is None else registry
    executor = active_registry.get(tool_name)
    if not executor:
        return {"error": f"Outil inconnu : {tool_name}"}

    async def operation() -> Any:
        try:
            return await executor(tool_args)
        except Exception as ex:
            return log_tool_exception(tool_name, tool_args, ex, conversation_id)

    return await execute_once(
        request_id=request_id,
        conversation_id=conversation_id,
        tool_name=tool_name,
        arguments=tool_args,
        operation=operation,
        guarded=tool_name in DANGEROUS_TOOLS or should_guard(tool_name),
        client_key=client_idempotency_key,
    )


def is_tooling_failure(result: Any) -> bool:
    """Distingue un defaut d'outillage d'un resultat metier negatif."""
    if not isinstance(result, dict):
        return False
    blob_env = (
        str(result.get("error", ""))
        + " "
        + str(result.get("stderr", ""))
        + " "
        + str(result.get("message", ""))
    ).lower()
    environmental_signatures = (
        "delai depasse",
        "délai dépassé",
        "timed out",
        "timeout",
        "acces refuse",
        "accès refusé",
        "access denied",
        "administrateur",
        "antivirus",
        "permission refusée",
        "requis",
        "required",
        "manquant",
        "missing",
        "fournis",
        "préciser",
        "preciser",
        "renseigner",
        "obligatoire",
    )
    if any(signature in blob_env for signature in environmental_signatures):
        return False
    if result.get("error"):
        return True
    if result.get("success") is False:
        blob = (str(result.get("stderr", "")) + " " + str(result.get("stdout", ""))).lower()
        tooling_signatures = (
            "is not recognized",
            "n'est pas reconnu",
            "not recognized as",
            "commandnotfound",
            "cmdletnotfound",
            "the term ",
            "parsererror",
            "unexpected token",
            "paramètre",
            "parameterbinding",
            "cannot be loaded",
            "outil inconnu",
            "argument",
            "syntax",
        )
        return any(signature in blob for signature in tooling_signatures)
    return False


def salvage_text_tool_calls(content: str, allowed_names: set[str]) -> list[dict[str, Any]]:
    """Convertit les appels textuels valides vers le format natif du runner.

    Seuls les outils proposes pour le tour courant sont acceptes. Les permissions et
    confirmations restent ensuite appliquees par le chemin d'execution normal.
    """
    if not content or not allowed_names:
        return []

    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (value or "").lower())

    normalized_names: dict[str, str] = {}
    for allowed_name in allowed_names:
        normalized_names.setdefault(normalize(allowed_name), allowed_name)

    def resolve(name: str | None) -> str | None:
        if not name:
            return None
        if name in allowed_names:
            return name
        normalized = normalize(name)
        if normalized in normalized_names:
            return normalized_names[normalized]
        candidates = [
            real
            for candidate, real in normalized_names.items()
            if normalized and (normalized in candidate or candidate in normalized)
        ]
        return candidates[0] if len(set(candidates)) == 1 else None

    decoder = json.JSONDecoder()
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    index = 0
    while index < len(content):
        if content[index] != "{":
            index += 1
            continue
        try:
            obj, end = decoder.raw_decode(content, index)
        except (TypeError, ValueError, json.JSONDecodeError):
            index += 1
            continue
        index = end
        if not isinstance(obj, dict):
            continue
        function = obj.get("function") if isinstance(obj.get("function"), dict) else {}
        name = resolve(obj.get("name") or obj.get("tool") or function.get("name"))
        arguments = obj.get("arguments")
        if arguments is None:
            arguments = obj.get("parameters") or obj.get("args") or function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not name or name not in allowed_names or not isinstance(arguments, dict):
            continue
        key = name + json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            calls.append({"function": {"name": name, "arguments": arguments}})

    for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]{2,40})\s*\(?\s*(\{)", content):
        name = resolve(match.group(1))
        if not name or name not in allowed_names:
            continue
        try:
            arguments, _ = decoder.raw_decode(content, match.start(2))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(arguments, dict) or any(
            key in arguments for key in ("name", "function", "arguments")
        ):
            continue
        key = name + json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            calls.append({"function": {"name": name, "arguments": arguments}})
    return calls


_REVERSIBLE_ARTIFACT_TOOLS = frozenset({"pptx_create"})
_PRESENTATION_INTENT = re.compile(
    r"\b(pr[ée]sentation|powerpoint|diaporama|pptx|slide|diapositive)s?\b",
    re.IGNORECASE,
)
_XML_INVOKE = re.compile(
    r"<(?:[A-Za-z][\w.-]*:)?invoke\s+name=[\"'](?P<name>[A-Za-z_][\w.-]{1,80})[\"']\s*>"
    r"(?P<body>.*?)</(?:[A-Za-z][\w.-]*:)?invoke\s*>",
    re.IGNORECASE | re.DOTALL,
)
_XML_PARAMETER = re.compile(
    r"<(?:[A-Za-z][\w.-]*:)?parameter\s+name=[\"'](?P<name>[A-Za-z_][\w.-]{0,80})[\"']\s*>"
    r"(?P<value>.*?)</(?:[A-Za-z][\w.-]*:)?parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)


def salvage_reversible_artifact_calls(
    content: str,
    allowed_names: set[str],
    *,
    user_query: str,
) -> list[dict[str, Any]]:
    """Récupère un appel d'artefact explicite émis en balises par certains modèles."""
    if (
        not content
        or len(content) > 200_000
        or not _PRESENTATION_INTENT.search(user_query or "")
    ):
        return []
    permitted = set(allowed_names) & set(_REVERSIBLE_ARTIFACT_TOOLS)
    if not permitted:
        return []

    calls: list[dict[str, Any]] = []
    for invoke in _XML_INVOKE.finditer(content):
        name = invoke.group("name")
        if name not in permitted:
            continue
        arguments: dict[str, Any] = {}
        invalid = False
        for parameter in _XML_PARAMETER.finditer(invoke.group("body")):
            key = parameter.group("name")
            if key in arguments:
                invalid = True
                break
            raw = html.unescape(parameter.group("value").strip())
            if len(raw) > 100_000:
                invalid = True
                break
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
            arguments[key] = value
        if not invalid and arguments:
            calls.append({"function": {"name": name, "arguments": arguments}})
    return calls[:1]
