"""Validations deterministes appliquees avant et apres les appels LLM/outils."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from functools import partial


def build_tool_schemas(specifications: Iterable[dict]) -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    for specification in specifications:
        function = specification.get("function", {})
        name = function.get("name")
        if name:
            schemas[str(name)] = dict(function.get("parameters", {}))
    return schemas


def build_required_tool_args(specifications: Iterable[dict]) -> dict[str, tuple[str, ...]]:
    """Compatibilité publique pour les tests et consommateurs historiques."""
    return {
        name: tuple(schema.get("required", ()))
        for name, schema in build_tool_schemas(specifications).items()
    }


def _type_matches(value: object, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _validate_schema_value(path: str, value: object, schema: Mapping) -> str | None:
    expected = schema.get("type")
    if isinstance(expected, str) and not _type_matches(value, expected):
        return f"le paramètre '{path}' doit être de type {expected}"
    allowed = schema.get("enum")
    if isinstance(allowed, list) and value not in allowed:
        return f"le paramètre '{path}' doit valoir l'une des valeurs {allowed}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum, maximum = schema.get("minimum"), schema.get("maximum")
        if minimum is not None and value < minimum:
            return f"le paramètre '{path}' doit être supérieur ou égal à {minimum}"
        if maximum is not None and value > maximum:
            return f"le paramètre '{path}' doit être inférieur ou égal à {maximum}"
    if isinstance(value, str):
        minimum, maximum = schema.get("minLength"), schema.get("maxLength")
        if minimum is not None and len(value) < minimum:
            return f"le paramètre '{path}' doit contenir au moins {minimum} caractère(s)"
        if maximum is not None and len(value) > maximum:
            return f"le paramètre '{path}' doit contenir au plus {maximum} caractère(s)"
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                if re.search(pattern, value) is None:
                    return f"le paramètre '{path}' ne respecte pas le format attendu"
            except re.error:
                return f"le schéma interne du paramètre '{path}' contient un motif invalide"
    if isinstance(value, list):
        minimum, maximum = schema.get("minItems"), schema.get("maxItems")
        if minimum is not None and len(value) < minimum:
            return f"le paramètre '{path}' doit contenir au moins {minimum} élément(s)"
        if maximum is not None and len(value) > maximum:
            return f"le paramètre '{path}' doit contenir au plus {maximum} élément(s)"
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for index, item in enumerate(value):
            error = _validate_schema_value(f"{path}[{index}]", item, schema["items"])
            if error:
                return error
    if isinstance(value, dict) and isinstance(schema.get("properties"), Mapping):
        properties = schema["properties"]
        required = schema.get("required", ())
        for name in required:
            if name not in value:
                return f"le paramètre '{path}.{name}' est obligatoire"
        for name, item in value.items():
            child_schema = properties.get(name)
            if isinstance(child_schema, Mapping):
                error = _validate_schema_value(f"{path}.{name}", item, child_schema)
                if error:
                    return error
            elif schema.get("additionalProperties") is False:
                return f"le paramètre '{path}.{name}' n'est pas déclaré par le schéma"
    return None


def validate_tool_args(
    tool_name: str,
    args: object,
    *,
    required_by_name: Mapping[str, tuple[str, ...]] | None = None,
    schemas_by_name: Mapping[str, Mapping] | None = None,
) -> str | None:
    """Valide champs obligatoires, types, enums, bornes et propriétés avant exécution."""
    if not isinstance(args, dict):
        return f"⛔ Les arguments de '{tool_name}' doivent former un objet JSON."
    schemas = schemas_by_name or {}
    schema = schemas.get(tool_name, {})
    required = (
        tuple(schema.get("required", ()))
        if schema
        else (required_by_name or {}).get(tool_name, ())
    )
    missing = [
        name
        for name in required
        if name not in args
        or (isinstance(args.get(name), str) and not args[name].strip())
    ]
    if missing:
        return (
            f"⛔ Paramètre(s) obligatoire(s) manquant(s) pour '{tool_name}' : {', '.join(missing)}. "
            "Vérifie la demande de l'utilisateur ou utilise l'outil de recherche/liste approprié "
            "pour trouver la vraie valeur — n'invente jamais un identifiant de substitution."
        )
    error = _validate_schema_value(tool_name, args, schema)
    return f"⛔ Arguments invalides pour '{tool_name}' : {error}." if error else None


def validator_for(specifications: Iterable[dict]):
    schemas = build_tool_schemas(specifications)
    return partial(
        validate_tool_args,
        schemas_by_name=schemas,
    )


_DANGEROUS_SCRIPT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"ALTER\s+USER\s+['\"]?root['\"]?@", re.IGNORECASE),
     "Ce script modifie le mot de passe/l'authentification du compte **root** d'une base de données (MariaDB/MySQL). Ce n'est presque jamais nécessaire — sur Debian/Ubuntu, root utilise déjà une authentification locale sûre par défaut."),
    (re.compile(r"SET\s+PASSWORD\s+FOR\s+['\"]?root['\"]?@", re.IGNORECASE),
     "Ce script modifie le mot de passe du compte **root** d'une base de données — vérifie que c'est vraiment voulu."),
    (re.compile(r"IDENTIFIED\s+BY\s+['\"]{2}", re.IGNORECASE),
     "Un mot de passe **VIDE** apparaît dans une commande d'authentification — à corriger avant toute exécution."),
    (re.compile(r"chmod\s+-R\s+777\b"),
     "Permissions **777 récursives** détectées (lecture/écriture/exécution pour TOUT LE MONDE) — presque toujours trop large."),
    (re.compile(r"curl\s+[^\n]*\|\s*(sudo\s+)?(ba)?sh\b|wget\s+[^\n]*-O-?\s*[^\n]*\|\s*(sudo\s+)?(ba)?sh\b", re.IGNORECASE),
     "Ce script télécharge un fichier distant et l'exécute directement (`curl|sh` / `wget|sh`) sans jamais l'inspecter — n'exécute un script tiers qu'après l'avoir lu, ou vérifie au minimum son empreinte (checksum/signature)."),
    (re.compile(r"curl\s+[^\n]*(-k\b|--insecure\b)", re.IGNORECASE),
     "Vérification du certificat TLS **désactivée** (`curl -k`/`--insecure`) — expose à une interception (MITM), à éviter même en test."),
    (re.compile(r"PermitRootLogin\s+yes", re.IGNORECASE),
     "Ce script active la **connexion SSH directe en root** (`PermitRootLogin yes`) — préférer un compte nommé + `sudo`."),
    (re.compile(r"\bufw\s+disable\b|iptables\s+-F\b(?!.*iptables-restore)", re.IGNORECASE),
     "Ce script désactive/vide le pare-feu (`ufw disable` / `iptables -F`) sans le reconfigurer ensuite — vérifie qu'un pare-feu reste actif après."),
    (re.compile(r"bind[- ]?address\s*[:=]\s*0\.0\.0\.0", re.IGNORECASE),
     "Un service est configuré pour écouter sur **toutes les interfaces réseau** (`0.0.0.0`) — vérifie que c'est voulu et que l'accès est bien restreint (pare-feu/authentification) plutôt qu'exposé par défaut."),
)

_DANGEROUS_DOCUMENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\$\([^)]*\b(date|hostname|whoami)\b[^)]*\)", re.IGNORECASE),
     "Une substitution shell non évaluée (ex. `$(date ...)`) apparaît littéralement dans le contenu — remplace-la par la vraie valeur, ce document n'est pas exécuté."),
)


def scan_dangerous_script_patterns(
    text: object,
    require_code_fence: bool = True,
    document_mode: bool = False,
) -> list[str]:
    content = str(text or "")
    if require_code_fence and "```" not in content:
        return []
    patterns = _DANGEROUS_SCRIPT_PATTERNS
    if document_mode:
        patterns += _DANGEROUS_DOCUMENT_PATTERNS
    return [message for pattern, message in patterns if pattern.search(content)]
