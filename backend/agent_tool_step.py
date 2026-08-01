"""Préparation déterministe d'une étape d'outil du Runner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


_CRITICAL_RESULT_FIELDS = frozenset(
    {
        "error",
        "success",
        "message",
        "path",
        "url",
        "title",
        "status",
        "count",
        "hash",
        "result",
        "translated",
        "rows_count",
        "entries_count",
        "pages",
        "total_pages",
        "pages_read",
        "truncated",
        "chars",
    }
)


@dataclass(slots=True)
class PreparedToolCall:
    name: str
    arguments: dict[str, Any]
    read_signature: str = ""


# v2.526 — Incident réel reproduit (conversation « PowerPoint article Windows
# RDP ») : le modèle a appelé `pptx_create` avec `slides` comme CHAÎNE contenant
# du JSON (`"[{...}]"`) au lieu d'un tableau — rejeté par le validateur, IDENTIQUE
# 9 fois d'affilée, sans jamais s'adapter au message d'erreur. Ce n'est pas
# spécifique à `pptx_create` : tout paramètre `array`/`object` risque la même
# sérialisation excessive selon le modèle. Réparation générique et bornée : un
# champ déclaré `array`/`object` par le schéma, reçu sous forme de chaîne, est
# décodé UNE fois ; un échec de décodage ou un type décodé incohérent laisse la
# valeur telle quelle pour que le message d'erreur existant reste exact.
#
# v2.537 — Même défaut constaté sur `boolean`/`integer`/`number` (conversation
# « Liste des éléments du bureau ») : `file_find.include_dirs="true"`,
# `file_find.max_results="2000"`, `pc_run_powershell.timeout="120"`,
# `pc_run_powershell.confirmed="True"` — 6 échecs de validation d'affilée sur
# la MÊME demande utilisateur, alors qu'un correctif équivalent existait déjà
# mais seulement en dur pour deux clés de `computer_control` et quatre de
# `web_site_crawl`. Généralisé à TOUT champ scalaire déclaré par le schéma,
# pour ne plus dépendre d'une liste d'exceptions entretenue outil par outil.
_TRUE_LITERALS = frozenset({"true", "1", "yes", "oui"})
_FALSE_LITERALS = frozenset({"false", "0", "no", "non"})


def _coerce_stringified_scalar(value: str, expected: str) -> Any:
    stripped = value.strip()
    if expected == "boolean":
        folded = stripped.casefold()
        if folded in _TRUE_LITERALS:
            return True
        if folded in _FALSE_LITERALS:
            return False
        return None
    if expected == "integer":
        try:
            return int(stripped)
        except ValueError:
            return None
    if expected == "number":
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _coerce_stringified_json_fields(
    arguments: dict[str, Any], schema: Mapping[str, Any] | None
) -> dict[str, Any]:
    if not schema:
        return arguments
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return arguments
    expected_python_type = {"array": list, "object": dict}
    for key, field_schema in properties.items():
        if key not in arguments or not isinstance(field_schema, Mapping):
            continue
        expected = field_schema.get("type")
        value = arguments[key]
        if not isinstance(value, str):
            continue
        if expected in {"boolean", "integer", "number"}:
            coerced = _coerce_stringified_scalar(value, expected)
            if coerced is not None:
                arguments[key] = coerced
            continue
        python_type = expected_python_type.get(expected)
        if python_type is None:
            continue
        stripped = value.strip()
        if not stripped or stripped[0] not in "[{":
            continue
        try:
            decoded = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(decoded, python_type):
            arguments[key] = decoded
    return arguments


def prepare_tool_call(
    name: str,
    raw_arguments: Any,
    *,
    schemas_by_name: Mapping[str, Mapping[str, Any]] | None = None,
) -> PreparedToolCall:
    """Normalise les variantes réellement émises par les modèles."""
    arguments = raw_arguments
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    else:
        arguments = dict(arguments)
        arguments = _coerce_stringified_json_fields(
            arguments, (schemas_by_name or {}).get(name)
        )

    # Certains modèles compatibles OpenAI sérialisent encore les booléens JSON
    # en chaînes. La coercition reste volontairement limitée aux champs booléens
    # documentés de Computer Runtime et aux deux littéraux JSON exacts.
    if name == "computer_control":
        for key in ("visual", "capture_before", "embed", "confirmed"):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip().casefold() in {"true", "false"}:
                arguments[key] = value.strip().casefold() == "true"
        # v2.537 — Incident réel reproduit : le modèle appelle `action="open"` avec
        # `program`/`app`/`app_name` (absents du schéma) au lieu de `target`. v2.539 —
        # ajout de `url`, utilisé de la même façon pour `action="navigate"`. v2.540 —
        # ajout de `query`, utilisé pour un lancement d'application par nom flou.
        if not arguments.get("target"):
            for alias in ("program", "app", "app_name", "application", "url", "query"):
                if arguments.get(alias):
                    arguments["target"] = arguments.pop(alias)
                    break
        # v2.539/v2.540 — Incident réel reproduit (conversation « Ouvrir IT Connect sur
        # Firefox », après redémarrage) : le modèle appelle `action="launch"`/
        # `action="search_app"` (synonymes naturels de "lancer/trouver un programme")
        # au lieu de `action="open"`, le seul reconnu par le schéma.
        action_alias = {
            "launch": "open", "start": "open", "run": "open", "search_app": "open",
            "switch": "focus", "activate": "focus", "switch_to": "focus",
        }
        current_action = str(arguments.get("action") or "").strip().casefold()
        if current_action in action_alias:
            arguments["action"] = action_alias[current_action]
        # v2.540 — Incident réel reproduit : le modèle envoie `key="win"`/`key="enter"`
        # pour `action="keypress"` (et parfois `type`) au lieu de `text`, le seul champ
        # du schéma pour la touche ou le texte à envoyer.
        if not arguments.get("text") and arguments.get("key"):
            arguments["text"] = arguments.pop("key")
        # v2.544 — Incident réel reproduit (conversation « Ouvrir le site IT Connect ») :
        # le modèle envoie `duration="3000"` pour `action="wait"` au lieu de
        # `duration_ms`, le seul champ du schéma pour ce délai.
        if not arguments.get("duration_ms") and arguments.get("duration"):
            value = arguments.pop("duration")
            if isinstance(value, str):
                try:
                    value = int(value.strip())
                except ValueError:
                    pass
            arguments["duration_ms"] = value
        # v2.539 — Incident réel reproduit : le modèle envoie un unique paramètre
        # `coordinate` (convention "coordinate: [x, y]" d'autres API de contrôle
        # d'écran) au lieu des champs séparés `x`/`y` du schéma de cet outil.
        if (
            arguments.get("x") is None
            and arguments.get("y") is None
            and "coordinate" in arguments
        ):
            raw_coordinate = arguments.pop("coordinate")
            if isinstance(raw_coordinate, str):
                try:
                    raw_coordinate = json.loads(raw_coordinate)
                except (json.JSONDecodeError, TypeError):
                    raw_coordinate = None
            if (
                isinstance(raw_coordinate, (list, tuple))
                and len(raw_coordinate) == 2
                and all(isinstance(part, (int, float)) for part in raw_coordinate)
            ):
                arguments["x"], arguments["y"] = raw_coordinate

    # v2.538 — Incident réel reproduit (conversation « Ouvrir IT Connect sur
    # Firefox ») : le modèle a appelé un outil "browser" inexistant (aucun outil
    # du catalogue ne porte ce nom générique) avec {action, url}. Alias borné aux
    # noms génériques les plus prévisibles, uniquement si le nom n'existe PAS
    # déjà dans le catalogue réel (jamais de collision avec un vrai outil).
    if (
        name in {"browser", "web_browser", "open_browser", "navigate"}
        and (schemas_by_name is None or name not in schemas_by_name)
        and (arguments.get("url") or arguments.get("target"))
    ):
        arguments = {"url": arguments.get("url") or arguments.get("target")}
        name = "web_browser_open"

    if (
        name == "pc_run_powershell"
        and not arguments.get("script")
        and arguments.get("command")
    ):
        arguments["script"] = arguments.pop("command")
    if (
        name == "web_browser_open"
        and not arguments.get("url")
        and arguments.get("target")
    ):
        arguments["url"] = arguments.pop("target")
    if name == "web_browser_open":
        # Cloud models often copy this tuning hint from web_browse. It is not
        # part of the deliberately small browser-open contract.
        arguments.pop("max_chars", None)
    if name == "web_site_crawl":
        for key in ("max_pages", "max_depth", "per_page_chars", "max_return_chars"):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip().isdigit():
                arguments[key] = int(value.strip())
    if name == "ssh_connect" and arguments.get("save"):
        name = "ssh_connection_save"
        arguments.pop("save", None)

    read_signature = ""
    if name == "code_workspace_status":
        read_signature = json.dumps(
            {
                "tool": name,
                "mission_id": str(arguments.get("mission_id") or ""),
            },
            sort_keys=True,
        )
    return PreparedToolCall(
        name=name,
        arguments=arguments,
        read_signature=read_signature,
    )


def prepare_tool_call_for(specifications):
    """Lie `prepare_tool_call` aux schémas déclarés, comme `agent_safety.validator_for`.

    Ainsi la réparation des champs `array`/`object` sérialisés en chaîne connaît
    le schéma exact de CHAQUE outil sans que les appelants n'aient à le passer.
    """
    from functools import partial

    from agent_safety import build_tool_schemas

    return partial(
        prepare_tool_call,
        schemas_by_name=build_tool_schemas(specifications),
    )


def inject_internal_context(
    name: str,
    arguments: dict[str, Any],
    conversation_id: str,
) -> dict[str, Any]:
    """Ajoute les identifiants internes que le LLM ne doit jamais inventer."""
    enriched = dict(arguments)
    if name in {"long_task_start", "code_workspace_start"}:
        enriched["_conversation_id"] = conversation_id
    if (
        name in {"screenshot_list", "doc_generate_from_screenshots"}
        and "conversation_id" not in enriched
    ):
        enriched["_conversation_id"] = conversation_id
    if (
        name in {"conversation_move", "conversation_update", "conversation_export"}
        and "conversation_id" not in enriched
        and "conversation_title" not in enriched
        and "title" not in enriched
    ):
        enriched["_conversation_id"] = conversation_id
    return enriched


def compact_tool_result(
    result: Any,
    max_chars: int = 4000,
    *,
    tool_name: str = "",
) -> str:
    """Projette un résultat borné pour le contexte LLM sans toucher au reçu complet."""
    serialized = json.dumps(result, ensure_ascii=False)
    if (
        tool_name == "file_list"
        and isinstance(result, dict)
        and isinstance(result.get("files"), list)
    ):
        projection = {
            key: result.get(key)
            for key in (
                "success", "currentDir", "count", "total_count", "offset",
                "limit", "has_more", "next_offset",
            )
        }
        projection["files"] = [
            {
                "name": item.get("name"),
                "type": item.get("type"),
                "size": item.get("size"),
            }
            for item in result["files"]
            if isinstance(item, dict)
        ]
        return json.dumps(projection, ensure_ascii=False)
    if tool_name == "pdf_read":
        max_chars = max(max_chars, 16_000)
    if tool_name == "computer_control" and isinstance(result, dict):
        def without_images(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: without_images(child)
                    for key, child in value.items()
                    if key != "image"
                }
            if isinstance(value, list):
                return [without_images(child) for child in value[:100]]
            return value

        projected = without_images(result)
        serialized = json.dumps(projected, ensure_ascii=False)
        if len(serialized) <= 16_000:
            return serialized
        return serialized[:16_000] + "…[observation visuelle réduite]"
    if len(serialized) <= max_chars:
        return serialized
    try:
        if not isinstance(result, dict):
            return serialized[:max_chars] + "…[tronqué]"
        compact: dict[str, Any] = {}
        for key, value in result.items():
            if key in _CRITICAL_RESULT_FIELDS:
                compact[key] = value
            elif isinstance(value, str) and len(value) > 500:
                compact[key] = (
                    value[:500]
                    + f"…[projection de contexte réduite de {len(value) - 500} caractères; "
                    "ne pas confondre avec le champ métier 'truncated']"
                )
            elif isinstance(value, list) and len(value) > 20:
                compact[key] = value[:20] + [f"…+{len(value) - 20} éléments"]
            else:
                compact[key] = value
        return json.dumps(compact, ensure_ascii=False)
    except (TypeError, ValueError):
        return serialized[:max_chars] + "…[tronqué]"
