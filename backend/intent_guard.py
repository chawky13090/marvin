"""Garde-fous déterministes entre une demande utilisateur et les outils de Marvin.

Ce module reste volontairement pur : aucun accès base de données, Qdrant ou Ollama. Les
règles critiques peuvent ainsi être testées rapidement sans démarrer un second backend.
"""

from __future__ import annotations

import re
import unicodedata


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("’", " ").replace("'", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


def _message_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content or "")


_NO_TOOL_PATTERNS = (
    re.compile(r"\b(?:sans|aucun)\s+(?:\w+\s+){0,2}outil(?:s)?\b"),
    re.compile(
        r"\bne\s+(?:\w+\s+){0,3}(?:utilise|declenche|appelle|lance|execute|active)\w*"
        r"\s+(?:\w+\s+){0,3}outil(?:s)?\b"
    ),
    re.compile(
        r"\bn[' ]?(?:utilise|emploie|appelle|active|execute)\w*\s+(?:\w+\s+){0,3}outil(?:s)?\b"
    ),
    re.compile(
        r"\b(?:utilise|declenche|declache|appelle|lance|execute|active)\w*\s+pas\s+d[' ]?\s*outil(?:s)?\b"
    ),
    re.compile(r"\b(?:ne\s+)?veux\s+pas\b.{0,60}\boutil(?:s)?\b"),
    re.compile(r"\bpas\s+besoin\s+d\s+outil(?:s)?\b"),
    re.compile(
        r"\bpas\s+(?:d\s+)?(?:utiliser|declencher|declacher|appeler|lancer|executer|proposer)\w*"
        r"(?:\s+\w+){0,4}\s+d\s+outil(?:s)?\b"
    ),
    re.compile(r"\breponds?\s+(?:moi\s+)?(?:directement|juste)\b.*\bsans\s+outil(?:s)?\b"),
)


def wants_no_tools(text: str) -> bool:
    """Détecte une interdiction explicite d'utiliser/déclencher des outils."""
    normalized = _norm(text)
    return bool(normalized and any(pattern.search(normalized) for pattern in _NO_TOOL_PATTERNS))


_COMMAND_TEXT_ONLY = re.compile(
    r"\b(donne[\s-]?moi\s+la|quelle?\s+(est\s+)?la|quel\s+est\s+la|"
    r"la\s+syntaxe\s+pour|c'?est\s+quoi\s+la)\s+commande\b",
    re.I,
)
_EXECUTION_VERB = re.compile(
    r"\b(lance|lance[\s-]?(la|le)|ex[ée]cute|ex[ée]cuter|ex[ée]cute[\s-]?(la|le)|"
    r"fais[\s-]?(le|la)|vas[\s-]?y|applique|applique[\s-]?(la|le)|"
    r"installe[\s-]?(le|la|maintenant)|active[\s-]?(le|la)|run\b)",
    re.I,
)
_EXECUTION_NEGATION = re.compile(
    r"\b(ne\s+(\w+\s+)?(lance|ex[ée]cute)\w*\s+(rien|pas)|"
    r"sans\s+(l')?\s*(lancer|ex[ée]cuter)|ne\s+pas\s+(lancer|ex[ée]cuter))\b",
    re.I,
)


def wants_command_text_only(text: str) -> bool:
    """Distingue la demande du texte d'une commande de son execution effective."""
    if not text or not _COMMAND_TEXT_ONLY.search(str(text)):
        return False
    if _EXECUTION_NEGATION.search(str(text)):
        return True
    return not _EXECUTION_VERB.search(str(text))


_QUIZ_MARKERS = (
    "question n°",
    "question no",
    "question :",
    "question:",
    "a toi de repondre",
    "quelle est ta reponse",
    "ta reponse ?",
    "ta reponse:",
)
_ACTION_REQUEST = re.compile(
    r"\b(?:utilise|lance|execute|active|ouvre|cherche|recherche|cree|genere|envoie|supprime|"
    r"installe|demarre|arrete)\b"
)


def is_quiz_answer(messages: list[dict], current_text: str) -> bool:
    """Vrai si le dernier message ressemble à la réponse courte à une question de quiz.

    Une réponse comme « backup total et incrémental » ne doit jamais devenir une nouvelle
    demande de sauvegarde. On exige un marqueur explicite dans le dernier tour assistant.
    """
    normalized = _norm(current_text)
    if not normalized or len(normalized.split()) > 24:
        return False
    if wants_no_tools(current_text):
        return True
    if "outil quiz" in normalized or _ACTION_REQUEST.search(normalized):
        return False

    prior_messages = messages[:-1] if messages and messages[-1].get("role") == "user" else messages
    previous_assistant = ""
    for message in reversed(prior_messages):
        if message.get("role") == "assistant":
            previous_assistant = _norm(_message_text(message))
            break
    return any(marker in previous_assistant for marker in _QUIZ_MARKERS)


_DIRECT_TEXT_ACTION = re.compile(r"\b(?:cree|ecris|redige|fais|prepare|genere|propose)\b")
_DIRECT_TEXT_OBJECT = re.compile(
    r"\b(?:questionnaire|quiz|liste de questions|questions d entrainement)\b"
)
_TOOL_OR_ARTIFACT_SIGNAL = re.compile(
    r"\b(?:outil|interactif|fichier|pdf|word|docx|xlsx|powerpoint|pptx|bureau|telecharge|"
    r"enregistre|sauvegarde|web|internet|recherche|cherche|sources?|officiel|a jour)\b"
)


def wants_direct_text(text: str) -> bool:
    """Détecte une création de contenu simple attendue directement dans le chat."""
    normalized = _norm(text)
    return bool(
        normalized
        and _DIRECT_TEXT_ACTION.search(normalized)
        and _DIRECT_TEXT_OBJECT.search(normalized)
        and not _TOOL_OR_ARTIFACT_SIGNAL.search(normalized)
    )


_FOLLOWUP_ONLY = re.compile(
    r"^(?:oui|non|ok|d accord|vas y|go|fais le|fais la|continue|poursuis|celle ci|celui ci|"
    r"la numero \d+|le numero \d+|et maintenant)(?:[ ?!.]+)?$"
)


def skill_match_text(messages: list[dict], current_text: str) -> str:
    """Ajoute le tour précédent uniquement pour une vraie réponse anaphorique.

    L'ancien critère « quatre mots ou moins » faisait hériter à toute réponse de quiz de
    l'intention du tour précédent et activait des compétences sans rapport.
    """
    normalized = _norm(current_text)
    if not _FOLLOWUP_ONLY.fullmatch(normalized):
        return current_text

    prior_messages = messages[:-1] if messages and messages[-1].get("role") == "user" else messages
    for message in reversed(prior_messages):
        if message.get("role") == "user":
            previous = _message_text(message).strip()
            return f"{previous} {current_text}".strip() if previous else current_text
    return current_text


def tool_suppression_reason(messages: list[dict], current_text: str) -> str | None:
    """Retourne la raison stable pour laquelle aucun outil ne doit être proposé au LLM."""
    if wants_no_tools(current_text):
        return "explicit_no_tools"
    if is_quiz_answer(messages, current_text):
        return "quiz_answer"
    if wants_direct_text(current_text):
        return "direct_text"
    return None


_COUNCIL_REQUEST = re.compile(
    r"\b(?:mode\s+council|model\s+council|conseil\s+de\s+modeles?|"
    r"demande\s+a\s+(?:plusieurs|cinq|5)\s+(?:ia|modeles?)|"
    r"(?:plusieurs|cinq|5)\s+(?:ia|modeles?)\s+(?:differents?\s+)?(?:avis|jugent|analysent|repondent))\b"
)


def wants_model_council(text: str) -> bool:
    """Détecte une demande explicite de Council, qui doit être exécutée et pas seulement
    proposée au LLM parmi des centaines d'outils."""
    return bool(_COUNCIL_REQUEST.search(_norm(text)))


_WORKSPACE_ID = re.compile(r"\b[0-9a-f]{32}\b")
_WORKSPACE_STATUS = re.compile(
    r"\b(?:ou en est|statut|status|progression|avance|preuves?|resultat|etape)\b"
)
_WORKSPACE_REPAIR = re.compile(
    r"\b(?:reecris|re ecris|reecrire|corrige|repare|reprends?|reprendre|poursuis|continue)\b"
)
_WORKSPACE_ARTIFACT = re.compile(r"\b(?:livrable|script|code|projet)\b")
_WORKSPACE_START = re.compile(
    r"\b(?:utilise|lance|demarre|cree|travaille|teste|corrige|prepare|mets|reprends?|poursuis|continue)\b"
)
_WORKSPACE_CONTROL = re.compile(
    r"\b(?:reprends?|reprendre|poursuis|continue|annule|annuler|arrete|stoppe)\b"
)


def workspace_followup(messages: list[dict], current_text: str) -> dict | None:
    """Route un suivi Code Workspace vers le bon outil et le dernier snapshot durable."""
    current = _norm(current_text)
    direct_ids = _WORKSPACE_ID.findall(current)
    history = _norm("\n".join(_message_text(item) for item in messages[-80:]))
    history_ids = _WORKSPACE_ID.findall(history)
    mission_id = direct_ids[-1] if direct_ids else (history_ids[-1] if history_ids else "")
    requested = any(marker in current for marker in ("code workspace", "coding mission", "code forge"))
    context = bool(mission_id or "code workspace" in history or "coding mission" in history)
    if not (requested or context):
        return None

    repair = bool(_WORKSPACE_REPAIR.search(current) and _WORKSPACE_ARTIFACT.search(current))
    if repair and mission_id:
        return {"tool": "code_workspace_control", "mission_id": mission_id, "action": "resume"}
    if _WORKSPACE_STATUS.search(current) and context:
        return {"tool": "code_workspace_status", "mission_id": mission_id}
    if direct_ids and _WORKSPACE_CONTROL.search(current):
        action = "cancel" if re.search(r"\b(?:annule|annuler|arrete|stoppe)\b", current) else "resume"
        return {"tool": "code_workspace_control", "mission_id": mission_id, "action": action}
    if _WORKSPACE_START.search(current):
        return {"tool": "code_workspace_start"}
    return None
