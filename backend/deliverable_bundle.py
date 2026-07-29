"""Safe multi-file deliverables and reproducibility gates for Code Forge."""
from __future__ import annotations

import json
import re
import shlex
import tomllib
from collections import Counter
from pathlib import PurePosixPath
from typing import Any


MAX_FILES = 48
MAX_FILE_BYTES = 200_000
MAX_BUNDLE_BYTES = 800_000
BLOCK_RE = re.compile(r"```([^\n`]*)\n([\s\S]*?)```", re.MULTILINE)
PRIMARY_NAMES = {
    "python": "main.py",
    "powershell": "main.ps1",
    "bash": "main.sh",
    "javascript": "main.mjs",
    "json": "main.json",
    "go": "main.go",
}
LANGUAGE_ALIASES = {
    "py": "python", "python": "python", "ps1": "powershell",
    "powershell": "powershell", "sh": "bash", "shell": "bash",
    "bash": "bash", "js": "javascript", "javascript": "javascript",
    "json": "json",
    "go": "go", "golang": "go",
}


class BundleError(ValueError):
    """Raised when a generated artifact bundle is unsafe or ambiguous."""


def normalize_path(raw_path: str) -> str:
    value = str(raw_path or "").strip().replace("\\", "/")
    if not value or any(ord(char) < 32 for char in value) or re.match(r"^[A-Za-z]:", value):
        raise BundleError("Chemin de livrable vide, absolu ou invalide.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BundleError(f"Chemin de livrable non relatif ou traversant : {value}")
    reserved = {"con", "prn", "aux", "nul", *{f"com{i}" for i in range(1, 10)}, *{f"lpt{i}" for i in range(1, 10)}}
    for part in path.parts:
        stem = part.split(".", 1)[0].casefold()
        if part.endswith((" ", ".")) or re.search(r'[<>:"|?*]', part) or stem in reserved:
            raise BundleError(f"Segment incompatible avec Windows : {part}")
    if path.parts[0].casefold() in {".git", ".svn", "node_modules", ".venv"}:
        raise BundleError(f"Répertoire de livrable interdit : {path.parts[0]}")
    normalized = path.as_posix()
    if len(normalized) > 240:
        raise BundleError("Chemin de livrable trop long.")
    return normalized


def _block_metadata(info: str) -> tuple[str, str | None]:
    try:
        parts = shlex.split(str(info or "").strip())
    except ValueError:
        parts = str(info or "").strip().split()
    language = ""
    path: str | None = None
    for index, part in enumerate(parts):
        if index == 0 and "=" not in part:
            language = part.casefold()
            continue
        key, separator, value = part.partition("=")
        if separator and key.casefold() in {"file", "path", "filename"}:
            # Certains modèles échappent les guillemets du metadata Markdown
            # (`file=\"src/app.py\"`). Ils ne font pas partie du chemin.
            path = value.strip().strip("'\"")
    return language, path


def _library_primary(files: dict[str, str], language: str) -> str | None:
    """Select a conventional package entry without inventing an executable main file."""
    if language == "python" and "pyproject.toml" in files:
        try:
            pyproject = tomllib.loads(files["pyproject.toml"])
        except (tomllib.TOMLDecodeError, AttributeError):
            pyproject = {}
        scripts = (pyproject.get("project") or {}).get("scripts") or {}
        for target in scripts.values() if isinstance(scripts, dict) else ():
            module = str(target).split(":", 1)[0].strip()
            candidate = "src/" + module.replace(".", "/") + ".py"
            if candidate in files:
                return candidate
        package_mains = sorted(
            path for path in files
            if path.startswith("src/") and path.endswith("/__main__.py")
        )
        if package_mains:
            return package_mains[0]
        package_sources = sorted(
            (
                path for path in files
                if path.startswith("src/")
                and path.endswith(".py")
                and not path.endswith("/__init__.py")
            ),
            key=lambda path: (-len(files[path]), path),
        )
        if package_sources:
            return package_sources[0]
        package_inits = sorted(
            path for path in files
            if path.startswith("src/") and path.endswith("/__init__.py")
        )
        if package_inits:
            return package_inits[0]
        sources = sorted(
            path for path in files
            if path.endswith(".py") and not path.startswith(("tests/", "test/"))
        )
        if len(sources) == 1:
            return sources[0]
    if language == "javascript" and "package.json" in files:
        try:
            package = json.loads(files["package.json"])
        except json.JSONDecodeError:
            package = {}
        declared = str(package.get("module") or package.get("main") or "").removeprefix("./")
        if declared in files:
            return declared
        for candidate in ("src/index.mjs", "src/index.js", "index.mjs", "index.js"):
            if candidate in files:
                return candidate
    return None


def parse(raw: str, *, default_language: str = "") -> dict[str, Any]:
    files: dict[str, str] = {}
    unnamed: list[dict[str, str]] = []
    errors: list[str] = []
    total_bytes = 0
    named_languages: list[str] = []
    for info, content in BLOCK_RE.findall(str(raw or "")):
        language, raw_path = _block_metadata(info)
        code = content.strip()
        if not code:
            continue
        size = len(code.encode("utf-8"))
        total_bytes += size
        if raw_path is None:
            if size > MAX_FILE_BYTES:
                errors.append("Bloc sans nom trop volumineux.")
            unnamed.append({"language": language, "content": code})
            continue
        if language:
            named_languages.append(language)
        try:
            path = normalize_path(raw_path)
        except BundleError as exc:
            errors.append(str(exc))
            continue
        if size > MAX_FILE_BYTES:
            errors.append(f"Fichier trop volumineux : {path}")
        elif path.casefold() in {item.casefold() for item in files}:
            errors.append(f"Chemin dupliqué : {path}")
        else:
            files[path] = code
    if len(files) > MAX_FILES:
        errors.append(f"Trop de fichiers : {len(files)} > {MAX_FILES}")
    if total_bytes > MAX_BUNDLE_BYTES:
        errors.append(f"Bundle trop volumineux : {total_bytes} octets")

    language = str(default_language or "").casefold()
    language = LANGUAGE_ALIASES.get(language, language)
    if language not in PRIMARY_NAMES and named_languages:
        language = Counter(
            LANGUAGE_ALIASES.get(item, item) for item in named_languages
        ).most_common(1)[0][0]
    primary_name = PRIMARY_NAMES.get(language)
    if not files and len(unnamed) > 1:
        errors.append("Plusieurs blocs de code sans attribut file= ; livrable ambigu.")
    elif not files and unnamed:
        primary = max(unnamed, key=lambda item: len(item["content"]))
        if language not in PRIMARY_NAMES:
            language = LANGUAGE_ALIASES.get(primary["language"], primary["language"])
        primary_name = PRIMARY_NAMES.get(language)
        if primary_name:
            files[primary_name] = primary["content"]
    elif unnamed:
        errors.append("Bloc de code sans attribut file= dans un livrable multi-fichiers.")

    if files and not primary_name:
        primary_name = max(files, key=lambda item: len(files[item]))
    elif primary_name and files and primary_name not in files:
        source_suffixes = {
            "python": ".py", "powershell": ".ps1", "bash": ".sh",
            "javascript": (".js", ".mjs", ".cjs"), "json": ".json",
            "go": ".go",
        }
        suffix = source_suffixes.get(language)
        candidates = [
            path for path in files
            if (
                (isinstance(suffix, tuple) and path.endswith(suffix))
                or (isinstance(suffix, str) and path.endswith(suffix))
            )
        ]
        library_primary = _library_primary(files, language)
        if library_primary:
            primary_name = library_primary
        elif len(candidates) == 1:
            original = candidates[0]
            files[primary_name] = files.pop(original)
        else:
            errors.append(f"Point d'entrée obligatoire absent : {primary_name}")

    return {
        "files": files,
        "primary": primary_name,
        "language": language,
        "errors": errors,
        "file_count": len(files),
        "total_bytes": sum(len(value.encode("utf-8")) for value in files.values()),
    }


def reproducibility_checks(files: dict[str, str], language: str) -> list[dict[str, Any]]:
    normalized = {normalize_path(path): str(content) for path, content in files.items()}
    checks: list[dict[str, Any]] = [{
        "name": "bundle_paths_safe",
        "passed": True,
        "detail": f"{len(normalized)} chemin(s) relatif(s) validé(s).",
    }]
    if language == "javascript" and "package.json" in normalized:
        try:
            package = json.loads(normalized["package.json"])
        except json.JSONDecodeError as exc:
            checks.append({"name": "package_json_valid", "passed": False, "detail": str(exc)})
        else:
            dependencies = {
                **(package.get("dependencies") or {}),
                **(package.get("devDependencies") or {}),
            }
            locked = "package-lock.json" in normalized or "npm-shrinkwrap.json" in normalized
            lock_name = "package-lock.json" if "package-lock.json" in normalized else "npm-shrinkwrap.json"
            lock_valid = True
            if locked:
                try:
                    lock_data = json.loads(normalized[lock_name])
                    lock_valid = isinstance(lock_data.get("lockfileVersion"), int)
                except (json.JSONDecodeError, AttributeError):
                    lock_valid = False
            checks.append({
                "name": "javascript_dependencies_locked",
                "passed": not dependencies or (locked and lock_valid),
                "detail": "Dépendances absentes ou verrou npm valide présent."
                if not dependencies or (locked and lock_valid)
                else "package.json déclare des dépendances sans verrou npm valide.",
            })
    if language == "python" and "pyproject.toml" in normalized:
        try:
            pyproject = tomllib.loads(normalized["pyproject.toml"])
            project = pyproject.get("project") or {}
            has_dependencies = bool(
                project.get("dependencies") or project.get("optional-dependencies")
            )
            pyproject_valid = True
        except (tomllib.TOMLDecodeError, AttributeError):
            has_dependencies = True
            pyproject_valid = False
        checks.append({
            "name": "pyproject_toml_valid",
            "passed": pyproject_valid,
            "detail": "pyproject.toml valide." if pyproject_valid else "pyproject.toml invalide.",
        })
        pinned_requirements = False
        for name in ("requirements.lock", "requirements.txt"):
            if name not in normalized:
                continue
            lines = [line.strip() for line in normalized[name].splitlines()]
            requirements = [line for line in lines if line and not line.startswith("#")]
            pinned_requirements = bool(requirements) and all(
                "==" in line and not line.startswith(("-e ", "--")) for line in requirements
            )
        pylock_valid = False
        if "pylock.toml" in normalized:
            try:
                tomllib.loads(normalized["pylock.toml"])
                pylock_valid = True
            except tomllib.TOMLDecodeError:
                pylock_valid = False
        locked = pylock_valid or pinned_requirements
        checks.append({
            "name": "python_dependencies_locked",
            "passed": not has_dependencies or locked,
            "detail": "Dépendances absentes ou verrou Python présent." if not has_dependencies or locked
            else "pyproject.toml déclare des dépendances sans pylock.toml ni requirements entièrement épinglé.",
        })
    if language == "go":
        go_mod = normalized.get("go.mod", "")
        module_valid = bool(re.search(r"(?m)^\s*module\s+\S+", go_mod))
        checks.append({
            "name": "go_module_valid",
            "passed": module_valid,
            "detail": "go.mod contient un module valide." if module_valid else "go.mod absent ou sans directive module.",
        })
        external = bool(re.search(r"(?m)^\s*require\s+(?:\(|\S+)", go_mod))
        checksum = bool(normalized.get("go.sum", "").strip())
        checks.append({
            "name": "go_dependencies_locked",
            "passed": not external or checksum,
            "detail": "Aucune dépendance externe ou go.sum présent." if not external or checksum
            else "go.mod déclare des dépendances sans go.sum.",
        })
    return checks


def supporting_files(bundle: dict[str, Any]) -> dict[str, str]:
    primary = bundle.get("primary")
    return {
        path: content
        for path, content in dict(bundle.get("files") or {}).items()
        if path != primary
    }
