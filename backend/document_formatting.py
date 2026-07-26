"""Transformation Markdown partagée par les générateurs DOCX et PDF."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any


_EMOJI_STRIP_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "\U0000200D"
    "]+"
)


def parse_markdown_blocks(content: str) -> Iterator[tuple[str, Any]]:
    """Projette un Markdown borné en blocs compris par DOCX et ReportLab."""
    lines = (content or "").split("\n")
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if (
            stripped.startswith("|")
            and index + 1 < len(lines)
            and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[index + 1])
        ):
            rows = [[cell.strip() for cell in stripped.strip("|").split("|")]]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([
                    cell.strip()
                    for cell in lines[index].strip().strip("|").split("|")
                ])
                index += 1
            yield "table", rows
            continue
        if stripped.startswith("```"):
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            yield "code", "\n".join(code)
            continue
        image = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if image:
            yield "image", (image.group(1).strip(), image.group(2).strip())
            index += 1
            continue
        if stripped.startswith("### "):
            yield "h3", stripped[4:]
        elif stripped.startswith("## "):
            yield "h2", stripped[3:]
        elif stripped.startswith("# "):
            yield "h1", stripped[2:]
        elif stripped.startswith("> "):
            yield "quote", stripped[2:]
        elif stripped.startswith(("- ", "* ", "• ")):
            yield "bullet", stripped[2:]
        elif re.match(r"^\d+\.\s", stripped):
            yield "num", re.sub(r"^\d+\.\s", "", stripped)
        elif stripped in ("---", "***", "___", "==="):
            yield "hr", None
        elif not stripped:
            yield "space", None
        else:
            yield "p", stripped
        index += 1


def markdown_inline_to_reportlab(text: str) -> str:
    """Convertit le Markdown inline vers le sous-ensemble XML sûr de ReportLab."""
    value = (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    value = _EMOJI_STRIP_RE.sub("", value)
    value = re.sub(r"[ \t]{2,}", " ", value).strip()
    def link(match: re.Match[str]) -> str:
        url = match.group(2).replace('"', "&quot;")
        return f'<a href="{url}" color="#2563eb"><u>{match.group(1)}</u></a>'

    value = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", link, value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(
        r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
        r"<i>\1</i>",
        value,
    )
    return re.sub(
        r"`([^`]+)`",
        r'<font face="Courier" backColor="#f0f0f0">\1</font>',
        value,
    )
