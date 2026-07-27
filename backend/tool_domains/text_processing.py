"""Traitement textuel déterministe, borné et indépendant des modèles."""

from __future__ import annotations

import asyncio
import difflib
import html
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

try:
    import regex as safe_regex
except ImportError:  # pragma: no cover - diagnostiqué explicitement au runtime
    safe_regex = None


_MAX_TEXT = 1_000_000
_MAX_DIFF_TEXT = 500_000
_MAX_DIFF_OUTPUT = 2_000_000
_MAX_EXTRACTED_PER_KIND = 1_000
_MAX_PATTERN = 2_048
_MAX_RESULTS = 1_000
_MAX_JOIN_ITEMS = 10_000
_MAX_JOIN_OUTPUT = 5_000_000
_REGEX_TIMEOUT_SECONDS = 0.25

_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_URL = re.compile(r"https?://[^\s\"')\]>]+")
_PHONE = re.compile(
    r"(?:\+33|0033|0)[1-9](?:[.\- ]?\d{2}){4}"
    r"|(?:\+\d{1,3}[\s\-]?)?\(?\d{3,4}\)?[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}"
)
_LINK = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_FENCE = re.compile(r"```([A-Za-z0-9_+.-]*)[ \t]*\n?([\s\S]*?)```")


def _bounded_text(value: object, *, name: str, maximum: int = _MAX_TEXT) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, f"Paramètre '{name}' invalide : chaîne attendue."
    if len(value) > maximum:
        return None, f"Paramètre '{name}' limité à {maximum} caractères."
    return value, None


def _bounded_int(
    value: object,
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> tuple[int | None, str | None]:
    if value is None:
        return default, None
    if isinstance(value, bool):
        return None, f"Paramètre '{name}' invalide."
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None, f"Paramètre '{name}' invalide."
    if not minimum <= number <= maximum:
        return None, f"Paramètre '{name}' attendu entre {minimum} et {maximum}."
    return number, None


def _unique_limited(values: Iterable[str]) -> tuple[list[str], bool]:
    unique: set[str] = set()
    truncated = False
    for value in values:
        unique.add(value)
        if len(unique) > _MAX_EXTRACTED_PER_KIND:
            truncated = True
            break
    return sorted(unique)[:_MAX_EXTRACTED_PER_KIND], truncated


async def text_extract(args: dict[str, Any]) -> dict[str, Any]:
    text, error = _bounded_text(args.get("text"), name="text")
    if error or text is None:
        return {"error": error}
    if not text:
        return {"error": "Paramètre 'text' requis."}
    extract = str(args.get("extract") or "all").strip().lower()
    if extract not in {"emails", "urls", "phones", "all"}:
        return {"error": "Paramètre 'extract' attendu : emails | urls | phones | all."}

    results: dict[str, Any] = {}
    truncated = False
    if extract in {"emails", "all"}:
        results["emails"], limited = _unique_limited(m.group(0) for m in _EMAIL.finditer(text))
        truncated |= limited
    if extract in {"urls", "all"}:
        results["urls"], limited = _unique_limited(
            m.group(0).rstrip(".,;") for m in _URL.finditer(text)
        )
        truncated |= limited
    if extract in {"phones", "all"}:
        results["phones"], limited = _unique_limited(m.group(0) for m in _PHONE.finditer(text))
        truncated |= limited
    return {
        "success": True,
        "extracted": extract,
        **results,
        "total_found": sum(len(value) for value in results.values()),
        "truncated": truncated,
    }


def _limited_diff(lines: Iterable[str]) -> tuple[str, int, int, bool]:
    chunks: list[str] = []
    size = added = removed = 0
    truncated = False
    for line in lines:
        if size + len(line) > _MAX_DIFF_OUTPUT:
            truncated = True
            break
        chunks.append(line)
        size += len(line)
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return "".join(chunks), added, removed, truncated


def _build_diff(text_a: str, text_b: str, mode: str, context_lines: int) -> dict[str, Any]:
    if mode == "ratio":
        ratio = difflib.SequenceMatcher(None, text_a, text_b, autojunk=True).ratio()
        percent = round(ratio * 100, 2)
        return {
            "success": True,
            "mode": "ratio",
            "similarity": percent,
            "message": f"Les textes sont similaires à {round(percent, 1)} %.",
        }
    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)
    if mode == "unified":
        iterator = difflib.unified_diff(
            lines_a, lines_b, fromfile="texte_a", tofile="texte_b", n=context_lines
        )
    elif mode == "context":
        iterator = difflib.context_diff(
            lines_a, lines_b, fromfile="texte_a", tofile="texte_b", n=context_lines
        )
    else:
        iterator = difflib.ndiff(lines_a, lines_b)
    rendered, added, removed, truncated = _limited_diff(iterator)
    return {
        "success": True,
        "mode": mode,
        "diff": rendered or "(Textes identiques)",
        "lines_added": added,
        "lines_removed": removed,
        "identical": not bool(rendered),
        "truncated": truncated,
    }


async def diff_text(args: dict[str, Any]) -> dict[str, Any]:
    text_a, error = _bounded_text(args.get("text_a"), name="text_a", maximum=_MAX_DIFF_TEXT)
    if error or text_a is None:
        return {"error": error}
    text_b, error = _bounded_text(args.get("text_b"), name="text_b", maximum=_MAX_DIFF_TEXT)
    if error or text_b is None:
        return {"error": error}
    mode = str(args.get("mode") or "unified").strip().lower()
    if mode not in {"unified", "context", "ndiff", "ratio"}:
        return {"error": "Paramètre 'mode' attendu : unified | context | ndiff | ratio."}
    context_lines, error = _bounded_int(
        args.get("context_lines"), name="context_lines", default=3, minimum=0, maximum=100
    )
    if error or context_lines is None:
        return {"error": error}
    return await asyncio.to_thread(_build_diff, text_a, text_b, mode, context_lines)


def _safe_url(value: str, *, image: bool) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    allowed = {"http", "https"} if image else {"http", "https", "mailto"}
    if parsed.scheme.lower() not in allowed:
        return None
    return html.escape(value, quote=True)


def _render_inline(value: str) -> str:
    escaped = html.escape(value, quote=True)
    code_blocks: dict[str, str] = {}

    def save_code(match: re.Match[str]) -> str:
        key = f"\x00CODE{len(code_blocks)}\x00"
        code_blocks[key] = f"<code>{match.group(1)}</code>"
        return key

    escaped = _INLINE_CODE.sub(save_code, escaped)

    def link(match: re.Match[str]) -> str:
        is_image, label, target = match.groups()
        safe_target = _safe_url(html.unescape(target), image=bool(is_image))
        if safe_target is None:
            return html.escape(match.group(0), quote=True)
        if is_image:
            return f'<img src="{safe_target}" alt="{label}">'
        return f'<a href="{safe_target}" rel="noopener noreferrer">{label}</a>'

    escaped = _LINK.sub(link, escaped)
    escaped = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", escaped)
    escaped = re.sub(r"___(.+?)___", r"<strong><em>\1</em></strong>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<em>\1</em>", escaped)
    for key, code in code_blocks.items():
        escaped = escaped.replace(key, code)
    return escaped


def _markdown_html(text: str) -> str:
    fenced: dict[str, str] = {}

    def save_fence(match: re.Match[str]) -> str:
        key = f"\x00FENCE{len(fenced)}\x00"
        language = html.escape(match.group(1), quote=True)
        code = html.escape(match.group(2), quote=False)
        fenced[key] = f'<pre><code class="language-{language}">{code}</code></pre>'
        return key

    protected = _FENCE.sub(save_fence, text)
    blocks: list[str] = []
    list_items: list[str] = []

    def flush_list() -> None:
        if list_items:
            blocks.append("<ul>" + "".join(list_items) + "</ul>")
            list_items.clear()

    for line in protected.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_list()
            continue
        if stripped in fenced:
            flush_list()
            blocks.append(fenced[stripped])
            continue
        heading = re.fullmatch(r"(#{1,6})\s+(.+)", stripped)
        if heading:
            flush_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_render_inline(heading.group(2))}</h{level}>")
        elif re.fullmatch(r"[-*_]{3,}", stripped):
            flush_list()
            blocks.append("<hr>")
        elif re.match(r"^[-*+]\s+", stripped):
            list_items.append(f"<li>{_render_inline(re.sub(r'^[-*+]\\s+', '', stripped))}</li>")
        else:
            flush_list()
            blocks.append(f"<p>{_render_inline(stripped)}</p>")
    flush_list()
    return "\n".join(blocks)


async def markdown_convert(args: dict[str, Any]) -> dict[str, Any]:
    text, error = _bounded_text(args.get("text"), name="text")
    if error or text is None:
        return {"error": error}
    if not text:
        return {"error": "Paramètre 'text' requis."}
    target = str(args.get("to") or "html").strip().lower()
    if target not in {"html", "plain", "stats"}:
        return {"error": "Paramètre 'to' attendu : html | plain | stats."}
    if target == "stats":
        return {
            "success": True,
            "headings": len(re.findall(r"^#{1,6}\s", text, re.MULTILINE)),
            "links": len(re.findall(r"(?<!!)\[[^\]\n]+\]\([^)]+\)", text)),
            "images": len(re.findall(r"!\[[^\]\n]*\]\([^)]+\)", text)),
            "code_blocks": len(_FENCE.findall(text)),
        }
    if target == "plain":
        plain = re.sub(r"```[A-Za-z0-9_+.-]*[ \t]*\n?([\s\S]*?)```", r"\1", text)
        plain = re.sub(r"`([^`\n]+)`", r"\1", plain)
        plain = re.sub(r"!\[[^\]\n]*\]\([^)]+\)", "", plain)
        plain = re.sub(r"\[([^\]\n]+)\]\([^)]+\)", r"\1", plain)
        plain = re.sub(r"^\s*(?:#{1,6}|[-*+]|\d+\.)\s+", "", plain, flags=re.MULTILINE)
        plain = re.sub(r"(\*\*\*|___|\*\*|__|\*|_)", "", plain)
        return {"success": True, "format": "plain", "result": plain.strip()}
    return {"success": True, "format": "html", "result": _markdown_html(text)}


def _regex_operation(
    pattern: str,
    text: str,
    action: str,
    replacement: str,
    flags: int,
    max_results: int,
) -> dict[str, Any]:
    if safe_regex is None:
        return {"error": "Dépendance 'regex' absente : réinstallez les dépendances Marvin."}
    try:
        compiled = safe_regex.compile(pattern, flags | safe_regex.VERSION0)
    except safe_regex.error as exc:
        return {"error": f"Expression régulière invalide : {exc}"}
    options = {"timeout": _REGEX_TIMEOUT_SECONDS, "concurrent": True}
    try:
        if action == "test":
            return {
                "success": True,
                "action": "test",
                "matches": compiled.search(text, **options) is not None,
                "pattern": pattern,
            }
        if action == "findall":
            iterator = compiled.finditer(text, **options)
            found = []
            truncated = False
            for match in iterator:
                if len(found) >= max_results:
                    truncated = True
                    break
                groups = match.groups()
                if not groups:
                    found.append(match.group(0))
                elif len(groups) == 1:
                    found.append(groups[0])
                else:
                    found.append(list(groups))
            return {
                "success": True,
                "action": "findall",
                "count": len(found),
                "matches": found,
                "truncated": truncated,
            }
        if action == "match":
            match = compiled.match(text, **options)
            if match is None:
                return {"success": True, "action": "match", "matched": False}
            return {
                "success": True,
                "action": "match",
                "matched": True,
                "groups": list(match.groups()),
                "span": list(match.span()),
            }
        if action == "replace":
            result, count = compiled.subn(
                replacement, text, count=max_results, **options
            )
            return {
                "success": True,
                "action": "replace",
                "result": result,
                "replacements": count,
                "limited_to": max_results,
            }
        parts = compiled.split(text, maxsplit=max_results, **options)
        return {
            "success": True,
            "action": "split",
            "count": len(parts),
            "parts": parts,
            "limited_to": max_results,
        }
    except TimeoutError:
        return {
            "error": (
                "Expression régulière interrompue après "
                f"{_REGEX_TIMEOUT_SECONDS:.2f} s (complexité excessive)."
            )
        }
    except (safe_regex.error, ValueError) as exc:
        return {"error": f"Expression régulière échouée : {exc}"}


async def regex_tool(args: dict[str, Any]) -> dict[str, Any]:
    pattern, error = _bounded_text(args.get("pattern"), name="pattern", maximum=_MAX_PATTERN)
    if error or pattern is None:
        return {"error": error}
    if not pattern:
        return {"error": "Paramètre 'pattern' requis."}
    text, error = _bounded_text(args.get("text", ""), name="text")
    if error or text is None:
        return {"error": error}
    action = str(args.get("action") or "findall").strip().lower()
    if action not in {"findall", "match", "replace", "split", "test"}:
        return {"error": "Action attendue : findall | match | replace | split | test."}
    if not text and action != "test":
        return {"error": "Paramètre 'text' requis."}
    replacement, error = _bounded_text(args.get("replace", ""), name="replace", maximum=100_000)
    if error or replacement is None:
        return {"error": error}
    flags_text = str(args.get("flags") or "").strip().upper()
    if any(flag not in "IMS" for flag in flags_text):
        return {"error": "Paramètre 'flags' attendu : combinaison de I, M et S."}
    max_results, error = _bounded_int(
        args.get("max_results"), name="max_results", default=100, minimum=1, maximum=_MAX_RESULTS
    )
    if error or max_results is None:
        return {"error": error}
    flags = 0
    if safe_regex is not None:
        if "I" in flags_text:
            flags |= safe_regex.IGNORECASE
        if "M" in flags_text:
            flags |= safe_regex.MULTILINE
        if "S" in flags_text:
            flags |= safe_regex.DOTALL
    return await asyncio.to_thread(
        _regex_operation, pattern, text, action, replacement, flags, max_results
    )


async def text_join(args: dict[str, Any]) -> dict[str, Any]:
    texts = args.get("texts")
    if isinstance(texts, str):
        texts = [texts]
    if not isinstance(texts, list) or not texts:
        return {"error": "Paramètre 'texts' requis (liste de chaînes)."}
    if len(texts) > _MAX_JOIN_ITEMS:
        return {"error": f"Paramètre 'texts' limité à {_MAX_JOIN_ITEMS} éléments."}
    if any(not isinstance(item, str) for item in texts):
        return {"error": "Chaque élément de 'texts' doit être une chaîne."}
    separator, error = _bounded_text(args.get("separator", "\n"), name="separator", maximum=10_000)
    if error or separator is None:
        return {"error": error}
    prefix, error = _bounded_text(args.get("prefix", ""), name="prefix", maximum=10_000)
    if error or prefix is None:
        return {"error": error}
    suffix, error = _bounded_text(args.get("suffix", ""), name="suffix", maximum=10_000)
    if error or suffix is None:
        return {"error": error}
    if args.get("dedupe", False):
        texts = list(dict.fromkeys(texts))
    estimated = sum(len(item) + len(prefix) + len(suffix) for item in texts)
    estimated += max(0, len(texts) - 1) * len(separator)
    if estimated > _MAX_JOIN_OUTPUT:
        return {"error": f"Résultat limité à {_MAX_JOIN_OUTPUT} caractères."}
    result = separator.join(f"{prefix}{item}{suffix}" for item in texts)
    return {
        "success": True,
        "result": result,
        "items": len(texts),
        "total_chars": len(result),
    }
