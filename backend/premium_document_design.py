"""Direction artistique déterministe pour les documents premium de Marvin.

Le LLM décrit l'intention. Ce module la transforme en jetons bornés et vérifiables ;
les moteurs DOCX/PDF restent responsables du rendu et n'exécutent aucun contenu libre.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

PALETTES: dict[str, dict[str, str]] = {
    "professional": {"accent": "#334155", "secondary": "#64748b", "text": "#172033", "muted": "#64748b", "surface": "#f8fafc", "cover": "#eef2f6", "cover_text": "#172033"},
    "executive": {"accent": "#9a7b3f", "secondary": "#3f4650", "text": "#202020", "muted": "#686868", "surface": "#f7f4ed", "cover": "#eee8db", "cover_text": "#202020"},
    "minimal": {"accent": "#444444", "secondary": "#737373", "text": "#202020", "muted": "#737373", "surface": "#fafafa", "cover": "#f2f2f2", "cover_text": "#202020"},
    "technical": {"accent": "#176b87", "secondary": "#3b8296", "text": "#16252d", "muted": "#52656f", "surface": "#eef6f8", "cover": "#dceef2", "cover_text": "#16252d"},
    "galactic": {"accent": "#8b5cf6", "secondary": "#22d3ee", "text": "#24223a", "muted": "#68658a", "surface": "#f4f2ff", "cover": "#0b1026", "cover_text": "#f4f2ff"},
    "luxury": {"accent": "#b8934f", "secondary": "#d8c49a", "text": "#211f1b", "muted": "#716b61", "surface": "#f8f5ef", "cover": "#171612", "cover_text": "#f8f5ef"},
    "nature": {"accent": "#39705a", "secondary": "#9caf88", "text": "#20352d", "muted": "#61736a", "surface": "#f1f5ef", "cover": "#173d30", "cover_text": "#f5f8f2"},
    "ocean": {"accent": "#136f8a", "secondary": "#51a9bb", "text": "#15343e", "muted": "#58747c", "surface": "#eef8fa", "cover": "#073642", "cover_text": "#f1fbfc"},
    "editorial": {"accent": "#b53b36", "secondary": "#d58c68", "text": "#25211f", "muted": "#756d68", "surface": "#faf5f1", "cover": "#f0e5dc", "cover_text": "#25211f"},
    "creative": {"accent": "#d33f75", "secondary": "#f29e4c", "text": "#302238", "muted": "#74647b", "surface": "#fff3f7", "cover": "#352044", "cover_text": "#fff8fb"},
}

_INTENTS = (
    ("galactic", ("galact", "espace", "cosmi", "astral", "science-fiction", "sci-fi")),
    ("luxury", ("luxe", "luxueux", "premium", "élégant", "elegant", "prestige", "haut de gamme")),
    ("nature", ("nature", "écolog", "ecolog", "forêt", "foret", "organique", "végétal", "vegetal")),
    ("ocean", ("océan", "ocean", "marin", "mer ", "aquatique", "bleu profond")),
    ("editorial", ("éditorial", "editorial", "magazine", "journal", "presse", "white paper")),
    ("creative", ("créatif", "creatif", "coloré", "colore", "dynamique", "pop", "startup")),
    ("technical", ("technique", "informatique", "cyber", "ingénier", "ingenier", "architecture")),
    ("executive", ("direction", "exécutif", "executif", "comex", "conseil", "finance")),
    ("minimal", ("minimal", "épuré", "epure", "sobre", "monochrome")),
)


@dataclass(frozen=True)
class DesignManifest:
    name: str
    layout: str
    density: str
    font: str
    palette: dict[str, str]
    source: str

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _valid_color(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip()
    if candidate and not candidate.startswith("#"):
        candidate = f"#{candidate}"
    return candidate.lower() if _HEX.fullmatch(candidate) else fallback


def _infer_name(prompt: str) -> str:
    folded = prompt.casefold()
    for name, terms in _INTENTS:
        if any(term in folded for term in terms):
            return name
    return "professional"


def _infer_layout(prompt: str, name: str) -> str:
    folded = prompt.casefold()
    if any(term in folded for term in ("brochure", "commercial", "catalogue", "offre")):
        return "customer_pack"
    if any(term in folded for term in ("proposition", "proposition commerciale", "appel d'offre", "candidature")):
        return "proposal"
    if any(term in folded for term in ("magazine", "éditorial", "editorial", "rapport", "livre blanc")):
        return "editorial"
    if any(term in folded for term in ("mémo", "memo", "audit", "incident", "technique", "procédure", "procedure")):
        return "masthead"
    return "immersive" if name in {"galactic", "luxury", "nature", "ocean", "creative"} else "masthead"


def resolve_design(args: dict[str, Any]) -> DesignManifest:
    prompt = str(args.get("design_prompt") or args.get("visual_style") or "").strip()
    requested = str(args.get("theme") or "").strip().casefold()
    name = requested if requested in PALETTES else _infer_name(prompt)
    source = "theme" if requested in PALETTES else ("design_prompt" if prompt else "default")
    palette = dict(PALETTES[name])
    custom = args.get("design_system")
    if isinstance(custom, dict):
        for key in palette:
            if key in custom:
                palette[key] = _valid_color(custom[key], palette[key])
        source = "design_system"
    if args.get("accent"):
        palette["accent"] = _valid_color(args["accent"], palette["accent"])
    layout = str(args.get("layout") or "").strip().casefold()
    if layout not in {"masthead", "editorial", "proposal", "customer_pack", "immersive", "minimal"}:
        layout = _infer_layout(prompt, name)
    density = str(args.get("density") or "balanced").strip().casefold()
    if density not in {"airy", "balanced", "compact"}:
        density = "balanced"
    return DesignManifest(name=name, layout=layout, density=density, font="Aptos", palette=palette, source=source)

