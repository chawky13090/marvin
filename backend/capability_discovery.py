"""Métadonnées de découverte des capacités Marvin.

Le registre ``TOOLS_SPEC`` reste l'unique autorité d'exécution. Ce module enrichit
uniquement la recherche et ne peut ni créer, ni autoriser, ni exécuter un outil.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


DISCOVERY_SCHEMA_VERSION = "marvin.capability-discovery/2.0"


@dataclass(frozen=True, slots=True)
class DiscoveryProfile:
    title: str
    aliases: tuple[str, ...] = ()
    use_when: tuple[str, ...] = ()
    do_not_use_when: tuple[str, ...] = ()
    related_tools: tuple[str, ...] = ()

    def search_document(self, name: str, summary: str, parameter_text: str) -> str:
        _ = summary, parameter_text
        return " ".join((
            name.replace("_", " "),
            self.title,
            *self.aliases,
            *self.use_when,
            *self.related_tools,
        ))

    def semantic_document(self, name: str, summary: str, parameter_text: str) -> str:
        return " ".join((
            self.search_document(name, summary, parameter_text),
            summary,
            parameter_text,
        ))


_PROFILES: dict[str, DiscoveryProfile] = {
    "tool_search": DiscoveryProfile(
        "Découvrir les capacités de Marvin",
        aliases=("chercher un outil", "trouver une capacité", "liste des outils"),
        use_when=("la capacité nécessaire n'est pas visible", "plusieurs outils semblent possibles"),
        do_not_use_when=("le bon outil est déjà visible et son schéma est connu",),
    ),
    "web_search": DiscoveryProfile(
        "Rechercher sur le Web",
        aliases=("recherche internet", "chercher avec searxng", "trouver des sources"),
        use_when=("trouver des pages sur plusieurs sites", "obtenir des résultats de moteur de recherche"),
        do_not_use_when=("lire une URL précise", "aspirer plusieurs pages d'un même site"),
        related_tools=("web_browser_open", "web_site_crawl", "web_research"),
    ),
    "web_browser_open": DiscoveryProfile(
        "Ouvrir et lire une page Web",
        aliases=("ouvrir une url", "naviguer sur une page", "rendre une page javascript"),
        use_when=("une URL précise doit être consultée", "une page dynamique doit être rendue"),
        do_not_use_when=("chercher plusieurs sites", "aspirer tout un site"),
        related_tools=("web_search", "web_site_crawl"),
    ),
    "web_site_crawl": DiscoveryProfile(
        "Aspirer les pages d'un site Web",
        aliases=("crawler", "aspirer un site", "explorer toutes les pages", "parcourir un site entier"),
        use_when=("plusieurs pages internes d'un même domaine doivent être extraites",),
        do_not_use_when=("une seule page doit être lue", "une recherche générale suffit"),
        related_tools=("web_search", "web_browser_open", "web_research"),
    ),
    "web_research": DiscoveryProfile(
        "Effectuer une recherche Web documentée",
        aliases=("recherche approfondie", "enquête web", "synthèse sourcée"),
        use_when=("la réponse nécessite plusieurs sources et une synthèse",),
        do_not_use_when=("une URL unique suffit", "une donnée locale est demandée"),
        related_tools=("web_search", "web_deep_research"),
    ),
    "web_deep_research": DiscoveryProfile(
        "Effectuer une recherche Web exhaustive",
        aliases=("recherche profonde", "étude exhaustive", "beaucoup de sources"),
        use_when=("l'utilisateur demande explicitement une couverture profonde ou exhaustive",),
        do_not_use_when=("une recherche Web courte suffit",),
        related_tools=("web_research", "web_search"),
    ),
    "pc_open_file": DiscoveryProfile(
        "Ouvrir un fichier dans son application Windows",
        aliases=("afficher un fichier", "lancer le fichier", "ouvrir avec windows"),
        use_when=("l'utilisateur veut voir le fichier dans son application",),
        do_not_use_when=("le contenu doit être analysé par Marvin",),
        related_tools=("file_read", "pdf_read", "pc_reveal"),
    ),
    "file_read": DiscoveryProfile(
        "Lire le contenu d'un fichier",
        aliases=(
            "analyser un fichier",
            "extraire le texte",
            "consulter le contenu",
            "lis le fichier texte",
        ),
        use_when=("Marvin doit exploiter le contenu d'un fichier local",),
        do_not_use_when=("l'utilisateur veut seulement ouvrir le fichier à l'écran",),
        related_tools=("pc_open_file", "pdf_read"),
    ),
    "docker_list_containers": DiscoveryProfile(
        "Lister les conteneurs Docker",
        aliases=("voir les containers docker", "conteneurs présents", "docker ps"),
        use_when=("lister les conteneurs Docker actifs ou arrêtés",),
        related_tools=("docker_inspect_container", "docker_container_logs"),
    ),
    "docker_container_logs": DiscoveryProfile(
        "Lire les journaux d'un conteneur Docker",
        aliases=("docker logs", "logs du container", "journaux du conteneur"),
        use_when=("diagnostiquer un service exécuté dans Docker",),
        do_not_use_when=("les journaux recherchés ne viennent pas de Docker",),
        related_tools=("docker_list_containers", "docker_inspect_container"),
    ),
    "email_send": DiscoveryProfile(
        "Envoyer un courriel",
        aliases=(
            "envoyer un email",
            "expédier un mail",
            "envoie un courriel",
            "courriel au client",
        ),
        use_when=("l'utilisateur demande explicitement l'envoi d'un message",),
        do_not_use_when=("l'utilisateur demande uniquement un brouillon",),
        related_tools=("email_draft_reply",),
    ),
    "email_draft_reply": DiscoveryProfile(
        "Préparer un brouillon de réponse",
        aliases=("rédiger sans envoyer", "brouillon email", "préparer une réponse"),
        use_when=("le message doit être validé avant tout envoi",),
        do_not_use_when=("l'utilisateur demande explicitement un envoi immédiat",),
        related_tools=("email_send",),
    ),
    "conversation_search": DiscoveryProfile(
        "Rechercher des conversations",
        aliases=("chercher un chat", "retrouver une discussion", "conversations du projet"),
        use_when=("retrouver des conversations par texte, projet ou titre",),
        do_not_use_when=(
            "toutes les conversations doivent seulement être listées",
            "ajouter ou créer un projet dans la barre latérale",
        ),
        related_tools=("conversation_list", "conversation_move"),
    ),
    "conversation_list": DiscoveryProfile(
        "Lister les conversations",
        aliases=("afficher les discussions", "liste des chats", "conversations récentes"),
        use_when=("afficher les conversations sans critère de recherche précis",),
        related_tools=("conversation_search",),
    ),
    "pdf_read": DiscoveryProfile(
        "Lire et analyser un document PDF",
        aliases=("extraire un pdf", "analyser un pdf", "lire les pages pdf"),
        use_when=("le contenu ou les métadonnées d'un PDF sont nécessaires",),
        do_not_use_when=("le PDF doit seulement être affiché",),
        related_tools=("pc_open_file", "file_read"),
    ),
    "file_find": DiscoveryProfile(
        "Trouver des fichiers par nom ou motif",
        aliases=("retrouver un fichier", "chercher par nom", "motif glob"),
        use_when=("le nom ou une partie du nom du fichier est connu",),
        do_not_use_when=("la recherche porte sur le contenu des documents",),
        related_tools=("file_search_text", "system_search", "system_search_content"),
    ),
    "file_search_text": DiscoveryProfile(
        "Rechercher du texte dans des fichiers",
        aliases=("grep dans les fichiers", "chercher un mot dans un dossier"),
        use_when=("un dossier est connu et son contenu doit être parcouru",),
        do_not_use_when=("le fichier est recherché uniquement par son nom",),
        related_tools=("file_find", "system_search_content"),
    ),
    "system_search_content": DiscoveryProfile(
        "Rechercher dans le contenu indexé du PC",
        aliases=("retrouver le document qui parle de", "recherche plein texte windows"),
        use_when=("l'emplacement est inconnu mais le contenu recherché est connu",),
        do_not_use_when=("seul le nom du fichier est recherché",),
        related_tools=("system_search", "file_search_text"),
    ),
    "project_create": DiscoveryProfile(
        "Créer un projet dans la barre latérale",
        aliases=(
            "nouveau dossier projet",
            "ajouter un projet sidebar",
            "dossier projet barre latérale",
            "rajoute dans la barre latérale un projet nommé",
            "grouper des conversations",
        ),
        use_when=("l'utilisateur demande un nouveau projet de conversations",),
        do_not_use_when=("créer un dossier sur le disque",),
        related_tools=("file_create_folder", "conversation_move"),
    ),
    "file_create_folder": DiscoveryProfile(
        "Créer un dossier sur le système de fichiers",
        aliases=("nouveau répertoire", "répertoire physique", "créer un dossier windows"),
        use_when=("un répertoire physique doit être créé sur le disque",),
        do_not_use_when=("l'utilisateur parle d'un projet dans la barre latérale",),
        related_tools=("project_create",),
    ),
}


def _human_title(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def profile_for(name: str) -> DiscoveryProfile:
    return _PROFILES.get(name, DiscoveryProfile(title=_human_title(name)))


def parameter_text(function: dict[str, Any]) -> str:
    parameters = function.get("parameters")
    if not isinstance(parameters, dict):
        return ""
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return ""
    parts: list[str] = []
    for key, definition in properties.items():
        parts.append(str(key))
        if isinstance(definition, dict):
            parts.append(str(definition.get("description") or ""))
            values = definition.get("enum")
            if isinstance(values, list):
                parts.extend(str(value) for value in values[:20])
    return " ".join(parts)


def discovery_enabled() -> bool:
    env_value = os.getenv("MARVIN_TOOL_DISCOVERY_V2")
    if env_value is not None:
        return env_value.strip().lower() not in {"0", "false", "no", "off"}
    try:
        import database as db

        stored = db.get_setting("tool_discovery_v2_enabled")
    except Exception:
        stored = None
    if stored is None:
        return True
    return str(stored).strip().lower() not in {"0", "false", "no", "off"}
