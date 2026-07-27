"""Utilitaires déterministes bornés, sans dépendance au modèle."""

from __future__ import annotations

import ast
import asyncio
import base64
import colorsys
import hashlib
import json
import math
import operator
import re
import secrets
import string
from collections import Counter
from pathlib import Path
from typing import Any, Callable

_MAX_INPUT = 1_000_000
_SYMBOLS = "!@#$%^&*()-_=+[]{}|;:,.<>?"
_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "int": int,
    "float": float,
    "sqrt": math.sqrt,
    "cbrt": lambda value: math.copysign(abs(value) ** (1 / 3), value),
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "trunc": math.trunc,
    "gcd": math.gcd,
    "degrees": math.degrees,
    "radians": math.radians,
    "hypot": math.hypot,
    "factorial": math.factorial,
    "comb": math.comb,
    "perm": math.perm,
    "pow": pow,
}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _evaluate(node: ast.AST, *, depth: int = 0) -> int | float:
    if depth > 24:
        raise ValueError("Expression trop profondément imbriquée.")
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, depth=depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Seuls les nombres sont autorisés.")
        if abs(node.value) > 1e100:
            raise ValueError("Constante numérique trop grande.")
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand, depth=depth + 1))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left = _evaluate(node.left, depth=depth + 1)
        right = _evaluate(node.right, depth=depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 10_000:
            raise ValueError("Exposant limité à 10000.")
        value = _BINARY[type(node.op)](left, right)
        if isinstance(value, int) and value.bit_length() > 65_536:
            raise ValueError("Résultat entier trop volumineux.")
        return value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id)
        if function is None or node.keywords:
            raise ValueError("Fonction mathématique non autorisée.")
        if len(node.args) > 32:
            raise ValueError("Trop d'arguments.")
        values = [_evaluate(arg, depth=depth + 1) for arg in node.args]
        if node.func.id == "factorial" and (
            len(values) != 1 or not isinstance(values[0], int) or not 0 <= values[0] <= 10_000
        ):
            raise ValueError("factorial accepte un entier compris entre 0 et 10000.")
        if node.func.id in {"comb", "perm"} and any(
            not isinstance(value, int) or not 0 <= value <= 100_000
            for value in values
        ):
            raise ValueError(f"{node.func.id} accepte des entiers compris entre 0 et 100000.")
        if node.func.id == "pow" and len(values) >= 2 and abs(values[1]) > 10_000:
            raise ValueError("Exposant limité à 10000.")
        value = function(*values)
        if isinstance(value, int) and value.bit_length() > 65_536:
            raise ValueError("Résultat entier trop volumineux.")
        return value
    raise ValueError(f"Expression non autorisée : {type(node).__name__}.")


async def calculator(args: dict[str, Any]) -> dict[str, Any]:
    expression = str(args.get("expression") or "").strip()
    if not expression:
        return {"error": "Paramètre 'expression' requis."}
    if len(expression) > 4096:
        return {"error": "Expression limitée à 4096 caractères."}
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 256:
            raise ValueError("Expression trop complexe.")
        result = _evaluate(tree)
        if isinstance(result, float) and not math.isfinite(result):
            raise ValueError("Résultat non fini.")
        formatted = f"{result:.10g}" if isinstance(result, float) else str(result)
        if len(formatted) > 100:
            formatted = f"{formatted[:48]}…[{len(formatted)} caractères]"
        serializable: Any = result
        if isinstance(result, int) and abs(result) > 10**15:
            serializable = formatted
        return {
            "success": True,
            "expression": expression,
            "result": serializable,
            "formatted": formatted,
        }
    except ZeroDivisionError:
        return {"error": "Division par zéro."}
    except (ArithmeticError, SyntaxError, TypeError, ValueError) as exc:
        return {"error": f"Expression invalide : {exc}"}


async def password_generate(args: dict[str, Any]) -> dict[str, Any]:
    try:
        length = int(args.get("length", 16))
        count = int(args.get("count", 1))
    except (TypeError, ValueError):
        return {"error": "La longueur et le nombre doivent être des entiers."}
    if not 4 <= length <= 128 or not 1 <= count <= 20:
        return {"error": "Longueur attendue : 4..128; nombre attendu : 1..20."}
    pin = bool(args.get("pin", False))
    include = set(args.get("include") or ["letters", "digits", "symbols"])
    if not include <= {"letters", "digits", "symbols"}:
        return {"error": "Catégorie inconnue; utilisez letters, digits ou symbols."}
    exclude = set(str(args.get("exclude") or ""))
    categories = []
    if pin:
        categories = [string.digits]
    else:
        if "letters" in include:
            categories.append(string.ascii_letters)
        if "digits" in include:
            categories.append(string.digits)
        if "symbols" in include:
            categories.append(_SYMBOLS)
        if not categories:
            categories = [string.ascii_letters + string.digits]
    categories = ["".join(char for char in group if char not in exclude) for group in categories]
    if any(not group for group in categories):
        return {"error": "Une catégorie demandée est vide après exclusions."}
    if len(categories) > length:
        return {"error": "La longueur ne permet pas de couvrir toutes les catégories."}
    charset = "".join(categories)
    randomizer = secrets.SystemRandom()
    passwords = []
    for _ in range(count):
        characters = [secrets.choice(group) for group in categories]
        characters.extend(
            secrets.choice(charset) for _ in range(length - len(characters))
        )
        randomizer.shuffle(characters)
        passwords.append("".join(characters))
    return {
        "success": True,
        "passwords": passwords,
        "length": length,
        "charset_size": len(set(charset)),
        "note": "Généré avec le générateur cryptographique du système.",
    }


def _hash_file(path: Path, algorithm: str) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(
            stream,
            lambda: hashlib.new(
                algorithm, usedforsecurity=algorithm not in {"md5", "sha1"}
            ),
        ).hexdigest()


async def hash_compute(
    args: dict[str, Any], *, resolve_path: Callable[[str], Any]
) -> dict[str, Any]:
    algorithm = str(args.get("algorithm") or "sha256").lower()
    if algorithm not in {"md5", "sha1", "sha256", "sha512", "sha3_256", "blake2b"}:
        return {"error": "Algorithme non supporté."}
    text = args.get("text")
    file_path = str(args.get("file_path") or "").strip()
    warning = (
        "MD5 et SHA-1 ne résistent plus aux collisions; usage limité à la compatibilité."
        if algorithm in {"md5", "sha1"}
        else None
    )
    try:
        if file_path:
            resolved = Path(resolve_path(file_path))
            if not resolved.is_file():
                return {"error": f"Fichier introuvable : {file_path}"}
            digest = await asyncio.to_thread(_hash_file, resolved, algorithm)
            result = {
                "success": True,
                "algorithm": algorithm.upper(),
                "hash": digest,
                "source": "file",
                "file": str(resolved),
            }
        elif text is not None and str(text) != "":
            encoded = str(text).encode("utf-8")
            if len(encoded) > _MAX_INPUT:
                return {"error": "Texte limité à 1 000 000 octets."}
            digest = hashlib.new(
                algorithm,
                encoded,
                usedforsecurity=algorithm not in {"md5", "sha1"},
            ).hexdigest()
            result = {
                "success": True,
                "algorithm": algorithm.upper(),
                "hash": digest,
                "source": "text",
            }
        else:
            return {"error": "Fournissez 'text' ou 'file_path'."}
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}
    if warning:
        result["warning"] = warning
    return result


async def base64_tool(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "encode").lower()
    data = str(args.get("data") or "")
    url_safe = bool(args.get("url_safe", False))
    if not data:
        return {"error": "Paramètre 'data' requis."}
    if len(data.encode("utf-8")) > _MAX_INPUT:
        return {"error": "Entrée limitée à 1 000 000 octets."}
    try:
        if action == "encode":
            encoder = base64.urlsafe_b64encode if url_safe else base64.b64encode
            result = encoder(data.encode("utf-8")).decode("ascii")
            return {
                "success": True,
                "action": "encode",
                "result": result,
                "length": len(result),
            }
        if action != "decode":
            return {"error": "Action invalide. Utilisez encode ou decode."}
        normalized = data + "=" * (-len(data) % 4)
        if url_safe:
            raw = base64.b64decode(normalized, altchars=b"-_", validate=True)
        else:
            raw = base64.b64decode(normalized, validate=True)
        try:
            decoded = raw.decode("utf-8")
            return {"success": True, "action": "decode", "result": decoded}
        except UnicodeDecodeError:
            return {
                "success": True,
                "action": "decode",
                "binary": True,
                "bytes": len(raw),
                "result": f"<données binaires — {len(raw)} octets>",
            }
    except (ValueError, TypeError) as exc:
        return {"error": f"Base64 invalide : {exc}"}


def _json_depth(value: Any, depth: int = 0) -> int:
    if depth > 100:
        raise ValueError("JSON imbriqué sur plus de 100 niveaux.")
    if isinstance(value, dict):
        return max((_json_depth(item, depth + 1) for item in value.values()), default=depth)
    if isinstance(value, list):
        return max((_json_depth(item, depth + 1) for item in value), default=depth)
    return depth


_PATH_TOKEN = re.compile(r"(?:^|\.)([A-Za-z0-9_-]+)|\[(\d+)\]")


async def json_tool(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "format").lower()
    data = args.get("data") if args.get("data") is not None else args.get("json")
    if not isinstance(data, str) or not data:
        return {"error": "Paramètre 'data' (JSON en texte) requis."}
    if len(data.encode("utf-8")) > _MAX_INPUT:
        return {"error": "JSON limité à 1 000 000 octets."}
    try:
        parsed = json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"Constante non JSON interdite : {value}")
        ))
        _json_depth(parsed)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        return {"error": f"JSON invalide : {exc}", "valid": False}
    if action == "validate":
        return {"success": True, "valid": True, "type": type(parsed).__name__}
    if action == "format":
        result = json.dumps(parsed, ensure_ascii=False, indent=2, allow_nan=False)
    elif action == "minify":
        result = json.dumps(
            parsed, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    elif action == "query":
        path = str(args.get("path") or "")
        if not path or len(path) > 1024:
            return {"error": "Chemin JSON requis et limité à 1024 caractères."}
        current = parsed
        position = 1 if path.startswith("$") else 0
        try:
            while position < len(path):
                match = _PATH_TOKEN.match(path, position)
                if not match:
                    raise KeyError("syntaxe invalide")
                key, index = match.groups()
                current = current[key] if key is not None else current[int(index)]
                position = match.end()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return {"error": f"Chemin introuvable : {path} — {exc}"}
        return {"success": True, "result": current}
    else:
        return {"error": "Action inconnue. Utilisez format, minify, validate ou query."}
    if len(result.encode("utf-8")) > 2 * _MAX_INPUT:
        return {"error": "Le résultat JSON dépasse 2 000 000 octets."}
    return {"success": True, "result": result}


async def text_stats(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text") or "")
    if not text:
        return {"error": "Paramètre 'text' requis."}
    if len(text.encode("utf-8")) > _MAX_INPUT:
        return {"error": "Texte limité à 1 000 000 octets."}
    try:
        top_n = int(args.get("top_words", 10))
    except (TypeError, ValueError):
        return {"error": "top_words doit être un entier."}
    if not 0 <= top_n <= 100:
        return {"error": "top_words doit être compris entre 0 et 100."}
    words = re.findall(r"\b\w+\b", text, flags=re.UNICODE)
    sentences = len(re.findall(r"[.!?]+", text)) or 1
    stopwords = {
        "le", "la", "les", "de", "du", "des", "et", "en", "un", "une", "à",
        "au", "aux", "que", "qui", "dans", "est", "il", "elle", "on", "ce",
        "the", "a", "an", "of", "in", "to", "is", "it", "and", "or", "for",
    }
    frequency = Counter(
        word.casefold()
        for word in words
        if len(word) > 2 and word.casefold() not in stopwords
    )
    seconds = round(len(words) / 250 * 60)
    return {
        "success": True,
        "characters": len(text),
        "chars_no_space": len(re.sub(r"\s", "", text)),
        "words": len(words),
        "sentences": sentences,
        "paragraphs": len([part for part in re.split(r"\n\s*\n", text) if part.strip()]),
        "lines": text.count("\n") + 1,
        "avg_word_length": round(sum(map(len, words)) / max(1, len(words)), 1),
        "avg_words_per_sentence": round(len(words) / sentences, 1),
        "reading_time": f"{seconds // 60}m {seconds % 60}s" if seconds >= 60 else f"{seconds}s",
        "top_words": [
            {"word": word, "count": count}
            for word, count in frequency.most_common(top_n)
        ],
    }


_HEX_COLOR = re.compile(r"^#(?P<value>[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB_COLOR = re.compile(
    r"^rgb\(\s*(?P<r>\d{1,3})\s*,\s*(?P<g>\d{1,3})\s*,\s*(?P<b>\d{1,3})\s*\)$",
    re.IGNORECASE,
)
_HSL_COLOR = re.compile(
    r"^hsl\(\s*(?P<h>\d+(?:\.\d+)?)\s*,\s*"
    r"(?P<s>\d+(?:\.\d+)?)%\s*,\s*(?P<l>\d+(?:\.\d+)?)%\s*\)$",
    re.IGNORECASE,
)


async def color_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Convertit strictement HEX/RGB/HSL et calcule le complément HSL."""
    color = str(args.get("color") or "").strip()
    if not color:
        return {
            "error": (
                "Paramètre 'color' requis. Exemple : #FF5733, "
                "rgb(255,87,51) ou hsl(11,100%,60%)"
            )
        }
    if len(color) > 64:
        return {"error": "La représentation de couleur est limitée à 64 caractères."}
    try:
        hex_match = _HEX_COLOR.fullmatch(color)
        rgb_match = _RGB_COLOR.fullmatch(color)
        hsl_match = _HSL_COLOR.fullmatch(color)
        if hex_match:
            value = hex_match.group("value")
            if len(value) == 3:
                value = "".join(component * 2 for component in value)
            red, green, blue = (
                int(value[0:2], 16),
                int(value[2:4], 16),
                int(value[4:6], 16),
            )
        elif rgb_match:
            red, green, blue = (
                int(rgb_match.group("r")),
                int(rgb_match.group("g")),
                int(rgb_match.group("b")),
            )
            if any(component > 255 for component in (red, green, blue)):
                raise ValueError("Les composantes RGB doivent être comprises entre 0 et 255.")
        elif hsl_match:
            hue = float(hsl_match.group("h"))
            saturation = float(hsl_match.group("s"))
            lightness = float(hsl_match.group("l"))
            if not 0 <= hue <= 360:
                raise ValueError("La teinte HSL doit être comprise entre 0 et 360.")
            if not 0 <= saturation <= 100 or not 0 <= lightness <= 100:
                raise ValueError(
                    "La saturation et la luminosité HSL doivent être comprises entre 0 et 100."
                )
            converted = colorsys.hls_to_rgb(
                (hue % 360) / 360,
                lightness / 100,
                saturation / 100,
            )
            red, green, blue = (round(component * 255) for component in converted)
        else:
            return {
                "error": (
                    f"Format non reconnu : {color}. Utilisez #RRGGBB, "
                    "rgb(r,g,b) ou hsl(h,s%,l%)."
                )
            }

        hue, lightness, saturation = colorsys.rgb_to_hls(
            red / 255, green / 255, blue / 255
        )
        hue_degrees = round(hue * 360, 1)
        saturation_percent = round(saturation * 100, 1)
        lightness_percent = round(lightness * 100, 1)
        complement_rgb = colorsys.hls_to_rgb(
            (hue + 0.5) % 1.0, lightness, saturation
        )
        complementary = "#" + "".join(
            f"{round(component * 255):02X}" for component in complement_rgb
        )
        luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
        return {
            "success": True,
            "input": color,
            "hex": f"#{red:02X}{green:02X}{blue:02X}",
            "rgb": {"r": red, "g": green, "b": blue},
            "rgb_str": f"rgb({red},{green},{blue})",
            "hsl": {
                "h": hue_degrees,
                "s": saturation_percent,
                "l": lightness_percent,
            },
            "hsl_str": (
                f"hsl({hue_degrees},{saturation_percent}%,{lightness_percent}%)"
            ),
            "complementary": complementary,
            "luminance": round(luminance, 3),
            "brightness": "clair" if luminance > 0.5 else "sombre",
        }
    except (TypeError, ValueError) as exc:
        return {"error": str(exc)}
