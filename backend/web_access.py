"""Classification conservative des pages Web qui exigent une session utilisateur."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


_AUTH_PATHS = ("/login", "/checkpoint", "/accounts/login", "/signin", "/sign-in")
_AUTH_TEXT_MARKERS = (
    "log in to continue",
    "login to continue",
    "sign in to continue",
    "connectez-vous pour continuer",
    "se connecter pour continuer",
    "vous devez vous connecter",
)


def detect_authentication_wall(
    url: str,
    *,
    title: str = "",
    text: str = "",
) -> dict[str, Any] | None:
    """Retourne un constat borné sans prétendre avoir lu le contenu protégé."""
    parsed = urlsplit(str(url or ""))
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "/").casefold()
    haystack = f"{title}\n{text[:4_000]}".casefold()
    auth_path = any(path == marker or path.startswith(f"{marker}/") for marker in _AUTH_PATHS)
    auth_text = any(marker in haystack for marker in _AUTH_TEXT_MARKERS)
    known_session_site = host == "facebook.com" or host.endswith(".facebook.com")
    if not auth_path and not (known_session_site and auth_text):
        return None

    service = "Facebook" if known_session_site else host or "Le site"
    return {
        "success": False,
        "access_limited": True,
        "authentication_required": True,
        "retryable": False,
        "error_code": "AUTHENTICATION_REQUIRED",
        "message": (
            f"{service} exige une session connectée. "
            "Marvin n’a pas lu le contenu de cette page."
        ),
        "next_actions": [
            "Ouvrir le lien dans le navigateur où l’utilisateur est déjà connecté.",
            "Ne pas présenter l’extrait du moteur de recherche comme une preuve du contenu.",
        ],
    }
