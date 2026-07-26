"""Préférences persistantes et catalogue documentaire de Marvin."""

from __future__ import annotations

from typing import Any

import database as db


IDENTITY_FIELDS = (
    "author", "org", "address", "phone", "email", "website", "logo",
    "footer_text", "confidentiality",
)

TEMPLATES: dict[str, dict[str, Any]] = {
    "rapport_intervention": {
        "name": "Rapport d'intervention IT", "icon": "🛠️",
        "sections": ["Contexte et demande", "Diagnostic", "Actions réalisées",
                     "Résultat et tests", "Recommandations"],
    },
    "dossier_pro": {
        "name": "Dossier professionnel", "icon": "🎓",
        "sections": ["Présentation et contexte", "Description de l'activité réalisée",
                     "Compétences mises en œuvre", "Difficultés rencontrées et solutions",
                     "Bilan et perspectives"],
    },
    "procedure": {
        "name": "Procédure technique", "icon": "📋",
        "sections": ["Objectif", "Prérequis", "Étapes détaillées", "Vérification",
                     "Dépannage (FAQ)"],
    },
    "cahier_charges": {
        "name": "Cahier des charges", "icon": "📐",
        "sections": ["Contexte et objectifs", "Périmètre du projet", "Besoins fonctionnels",
                     "Contraintes techniques", "Livrables et planning"],
    },
    "compte_rendu": {
        "name": "Compte-rendu de réunion", "icon": "📝",
        "sections": ["Informations (date, participants)", "Points abordés",
                     "Décisions prises", "Actions à suivre"],
    },
    "doc_technique": {
        "name": "Documentation technique", "icon": "🗂️",
        "sections": ["Vue d'ensemble", "Architecture et fonctionnement",
                     "Installation et configuration", "Utilisation",
                     "Maintenance et annexes"],
    },
    "devis_technique": {
        "name": "Devis technique", "icon": "💶",
        "sections": ["Contexte du besoin", "Solution proposée", "Détail des prestations",
                     "Matériel et licences", "Conditions et délais"],
    },
    "pv_recette": {
        "name": "PV de recette", "icon": "✅",
        "sections": ["Objet et périmètre", "Tests réalisés et résultats",
                     "Réserves et anomalies", "Conclusion et validation"],
    },
    "fiche_poste": {
        "name": "Fiche de poste", "icon": "👤",
        "sections": ["Intitulé et rattachement", "Missions principales",
                     "Activités et tâches", "Compétences requises",
                     "Conditions d'exercice"],
    },
    "libre": {
        "name": "Document professionnel", "icon": "📄",
        "sections": ["Introduction", "Développement", "Conclusion"],
    },
}


def get_identity() -> dict[str, Any]:
    try:
        value = db.get_setting("document_identity")
        return dict(value) if isinstance(value, dict) else {}
    except Exception:
        return {}


async def set_identity(args: dict[str, Any]) -> dict[str, Any]:
    current = get_identity()
    for field in IDENTITY_FIELDS:
        if field in args and args[field] is not None:
            value = args[field]
            current[field] = value.strip() if isinstance(value, str) else value
    db.set_setting("document_identity", current)
    return {
        "success": True,
        "message": "Identité document enregistrée.",
        "identity": current,
    }


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "name": value["name"],
            "icon": value["icon"],
            "sections": list(value["sections"]),
        }
        for key, value in TEMPLATES.items()
    ]
