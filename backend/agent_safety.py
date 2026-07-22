"""Validations deterministes appliquees avant et apres les appels LLM/outils."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from functools import partial


def build_required_tool_args(specifications: Iterable[dict]) -> dict[str, tuple[str, ...]]:
    required: dict[str, tuple[str, ...]] = {}
    for specification in specifications:
        function = specification.get("function", {})
        name = function.get("name")
        if name:
            required[str(name)] = tuple(
                function.get("parameters", {}).get("required", ())
            )
    return required


def validate_tool_args(
    tool_name: str,
    args: object,
    *,
    required_by_name: Mapping[str, tuple[str, ...]],
) -> str | None:
    """Refuse les arguments obligatoires absents sans coercition destructive."""
    if not isinstance(args, dict):
        return f"⛔ Les arguments de '{tool_name}' doivent former un objet JSON."
    required = required_by_name.get(tool_name, ())
    missing = [
        name
        for name in required
        if name not in args
        or (isinstance(args.get(name), str) and not args[name].strip())
    ]
    if not missing:
        return None
    return (
        f"⛔ Paramètre(s) obligatoire(s) manquant(s) pour '{tool_name}' : {', '.join(missing)}. "
        "Vérifie la demande de l'utilisateur ou utilise l'outil de recherche/liste approprié "
        "pour trouver la vraie valeur — n'invente jamais un identifiant de substitution."
    )


def validator_for(specifications: Iterable[dict]):
    return partial(
        validate_tool_args,
        required_by_name=build_required_tool_args(specifications),
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
