"""Contrat statique du bandeau d'activité persistant du chat."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    context = (ROOT / "lib" / "contexts" / "ChatContext.jsx").read_text(
        encoding="utf-8"
    )
    container = (
        ROOT / "components" / "chat" / "ChatContainer.jsx"
    ).read_text(encoding="utf-8")
    beacon = (
        ROOT / "components" / "chat" / "TypingIndicator.jsx"
    ).read_text(encoding="utf-8")
    styles = (
        ROOT / "components" / "chat" / "TypingIndicator.module.css"
    ).read_text(encoding="utf-8")

    assert "case 'tool_progress':" in context
    assert "progressEvents" in context and ".slice(-24)" in context
    assert container.index("<TypingIndicator") > container.index("</div>\n\n      {isLoading")
    assert "onStop={stop}" in container
    assert 'aria-live="polite"' in beacon
    assert 'role="progressbar"' in beacon
    assert "Aucun nouvel événement" in beacon
    assert "prefers-reduced-motion" in (
        ROOT / "app" / "globals.css"
    ).read_text(encoding="utf-8")
    assert ".beacon" in styles and ".timeline" in styles
    print("Activity Beacon OK - persistance visuelle, progression, arrêt et accessibilité.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
