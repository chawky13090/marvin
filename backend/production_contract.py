"""Deterministic production evidence gate for generated deliverable bundles."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
import uuid
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import deliverable_bundle


SOURCE_SUFFIXES = {
    "python": {".py"},
    "javascript": {".js", ".mjs", ".cjs"},
    "powershell": {".ps1", ".psm1"},
    "bash": {".sh"},
    "json": {".json"},
    "go": {".go"},
}
STATIC_STEPS = {
    "python": {"python_compile"},
    "javascript": {"node_check"},
    "powershell": {"powershell_parser", "psscriptanalyzer", "powershell_parser_vm", "psscriptanalyzer_vm"},
    "bash": {"bash_syntax", "shellcheck"},
    "json": {"json_parse"},
    "go": {"gofmt", "go_vet"},
}


def _check(name: str, passed: bool, detail: str, *, blocking: bool = True) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail, "blocking": blocking}


def has_external_dependencies(files: dict[str, str], language: str) -> bool:
    if language == "javascript" and "package.json" in files:
        try:
            package = json.loads(files["package.json"])
        except json.JSONDecodeError:
            return True
        return bool(package.get("dependencies") or package.get("optionalDependencies"))
    if language == "python":
        for name in ("requirements.lock", "requirements.txt"):
            if name in files and any(
                line.strip() and not line.lstrip().startswith(("#", "-r "))
                for line in files[name].splitlines()
            ):
                return True
        if "pyproject.toml" in files:
            try:
                project = (tomllib.loads(files["pyproject.toml"]).get("project") or {})
            except tomllib.TOMLDecodeError:
                return True
            return bool(project.get("dependencies") or project.get("optional-dependencies"))
    if language == "go":
        return bool(re.search(r"(?m)^\s*require\s+(?:\(|\S+)", files.get("go.mod", "")))
    return False


def _python_annotation_contract(files: dict[str, str]) -> tuple[bool, str]:
    public_functions = 0
    fully_typed = 0
    parse_errors: list[str] = []
    for path, content in files.items():
        if not path.endswith(".py") or PurePosixPath(path).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError as exc:
            parse_errors.append(f"{path}:{exc.lineno}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
                continue
            public_functions += 1
            positional = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            relevant = [item for item in positional if item.arg not in {"self", "cls"}]
            if node.returns is not None and all(item.annotation is not None for item in relevant):
                fully_typed += 1
    if parse_errors:
        return False, "Sources Python invalides : " + ", ".join(parse_errors)
    if public_functions == 0:
        return True, "Aucune fonction publique à typer."
    ratio = fully_typed / public_functions
    return ratio == 1.0, f"Fonctions publiques entièrement annotées : {fully_typed}/{public_functions}."


def _requirements_components(files: dict[str, str]) -> list[dict[str, str]]:
    for name in ("requirements.lock", "requirements.txt"):
        if name not in files:
            continue
        components = []
        for raw in files[name].splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "--", "-r ")) or "==" not in line:
                continue
            package, version = line.split("==", 1)
            version = version.split(";", 1)[0].strip().split()[0]
            package = package.strip()
            if package and version:
                components.append({"type": "library", "name": package, "version": version,
                                   "purl": f"pkg:pypi/{quote(package)}@{quote(version)}"})
        return components
    return []


def _pylock_components(files: dict[str, str]) -> list[dict[str, str]]:
    if "pylock.toml" not in files:
        return []
    try:
        lock = tomllib.loads(files["pylock.toml"])
    except tomllib.TOMLDecodeError:
        return []
    components = []
    for package in lock.get("packages") or []:
        if not isinstance(package, dict) or not package.get("name") or not package.get("version"):
            continue
        name, version = str(package["name"]), str(package["version"])
        components.append({"type": "library", "name": name, "version": version,
                           "purl": f"pkg:pypi/{quote(name)}@{quote(version)}"})
    return components


def _npm_components(files: dict[str, str]) -> list[dict[str, str]]:
    lock_name = "package-lock.json" if "package-lock.json" in files else "npm-shrinkwrap.json"
    if lock_name not in files:
        return []
    try:
        lock = json.loads(files[lock_name])
    except json.JSONDecodeError:
        return []
    components = []
    for path, metadata in (lock.get("packages") or {}).items():
        if not path or not isinstance(metadata, dict) or not metadata.get("version"):
            continue
        name = metadata.get("name") or path.rsplit("node_modules/", 1)[-1]
        version = str(metadata["version"])
        component = {"type": "library", "name": str(name), "version": version,
                     "purl": f"pkg:npm/{quote(str(name), safe='@/')}@{quote(version)}"}
        if metadata.get("integrity"):
            component["evidence"] = "integrity-present"
        components.append(component)
    if not components:
        def visit(dependencies: dict[str, Any]) -> None:
            for name, metadata in dependencies.items():
                if not isinstance(metadata, dict) or not metadata.get("version"):
                    continue
                version = str(metadata["version"])
                components.append({"type": "library", "name": str(name), "version": version,
                                   "purl": f"pkg:npm/{quote(str(name), safe='@/')}@{quote(version)}"})
                visit(metadata.get("dependencies") or {})
        visit(lock.get("dependencies") or {})
    return components


def generate_sbom(files: dict[str, str], language: str) -> dict[str, Any]:
    if language == "go":
        seen: set[tuple[str, str]] = set()
        components = []
        for line in files.get("go.sum", "").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            name, version = parts[0], parts[1].removesuffix("/go.mod")
            if (name, version) in seen:
                continue
            seen.add((name, version))
            components.append({"type": "library", "name": name, "version": version,
                               "purl": f"pkg:golang/{quote(name, safe='/')}@{quote(version)}"})
    else:
        components = (
        _npm_components(files)
        if language == "javascript"
        else (_pylock_components(files) or _requirements_components(files))
        )
    components.sort(key=lambda item: (item["name"].casefold(), item["version"]))
    fingerprint = hashlib.sha256(
        json.dumps(components, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, fingerprint)}",
        "version": 1,
        "components": components,
    }


def evaluate(
    files: dict[str, str],
    language: str,
    test_report: dict[str, Any],
    *,
    request: str = "",
) -> dict[str, Any]:
    normalized = {deliverable_bundle.normalize_path(path): str(value) for path, value in files.items()}
    checks = list(deliverable_bundle.reproducibility_checks(normalized, language))
    for item in checks:
        item.setdefault("blocking", True)

    suffixes = SOURCE_SUFFIXES.get(language, set())
    sources = [path for path in normalized if PurePosixPath(path).suffix.casefold() in suffixes]
    checks.append(_check("source_inventory", bool(sources), f"{len(sources)} source(s) inventoriée(s)."))

    passed_steps = {
        str(item.get("name")) for item in test_report.get("steps", []) if item.get("passed") is True
    }
    required_static = STATIC_STEPS.get(language, set())
    static_ok = bool(passed_steps & required_static)
    checks.append(_check(
        "static_analysis_evidence", static_ok,
        "Preuve d'analyse statique présente." if static_ok else "Aucune preuve d'analyse statique reconnue.",
    ))
    tests_executed = bool(test_report.get("tests_executed")) or (
        language == "json" and "json_parse" in passed_steps
    )
    checks.append(_check(
        "behavior_tests_executed", tests_executed,
        "Une suite comportementale a été exécutée." if tests_executed else "Aucune suite comportementale exécutée.",
    ))

    if language == "python":
        typed, detail = _python_annotation_contract(normalized)
        checks.append(_check("python_public_api_typed", typed, detail))

    dependencies = has_external_dependencies(normalized, language)
    online = bool(test_report.get("online_executed"))
    checks.append(_check(
        "dependency_installation_proof",
        not dependencies or online,
        "Aucune dépendance externe." if not dependencies else
        "Installation des dépendances exécutée en environnement jetable." if online else
        "Des dépendances existent sans preuve d'installation en environnement jetable.",
    ))
    sbom = generate_sbom(normalized, language)
    sbom_ok = not dependencies or bool(sbom["components"])
    checks.append(_check(
        "cyclonedx_sbom",
        sbom_ok,
        f"SBOM CycloneDX 1.6 : {len(sbom['components'])} composant(s)." if sbom_ok else
        "Impossible de produire un inventaire CycloneDX depuis le verrou fourni.",
    ))

    failed = [item for item in checks if item.get("blocking") and not item.get("passed")]
    return {
        "success": not failed,
        "profile": "production_bundle" if len(sources) > 1 or dependencies else "production_script",
        "language": language,
        "checks": checks,
        "failed_checks": failed,
        "source_files": sources,
        "external_dependencies": dependencies,
        "sbom": sbom,
        "request_fingerprint": hashlib.sha256(request.encode("utf-8")).hexdigest()[:16],
    }
