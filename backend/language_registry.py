"""Single capability matrix for code generation and production certification."""
from __future__ import annotations

from typing import Any


PROFILES: dict[str, dict[str, Any]] = {
    "python": {"aliases": ["py"], "targets": ["windows", "linux"], "level": "certified",
               "toolchain": "Python 3.12.13", "checks": ["compile", "unittest", "typing_contract", "sbom"]},
    "powershell": {"aliases": ["ps1"], "targets": ["windows"], "level": "certified",
                   "toolchain": "Windows Sandbox + PowerShell 5.1", "checks": ["parser", "PSScriptAnalyzer 1.25.0", "Pester 5.8.0"]},
    "bash": {"aliases": ["sh", "shell"], "targets": ["linux"], "level": "certified",
             "toolchain": "Debian 13", "checks": ["bash -n", "ShellCheck 0.11", "Bats 1.13"]},
    "javascript": {"aliases": ["js", "node"], "targets": ["windows", "linux"], "level": "certified",
                   "toolchain": "Node.js 22.23.1", "checks": ["node --check", "node:test", "npm lock", "sbom"]},
    "json": {"aliases": [], "targets": ["windows", "linux"], "level": "certified",
             "toolchain": "Python JSON parser", "checks": ["parse"]},
    "go": {"aliases": ["golang"], "targets": ["linux"], "cross_targets": ["windows"], "level": "certified",
           "toolchain": "Go 1.26.5", "checks": ["gofmt", "go vet", "go test", "GOOS=windows build", "go.sum", "sbom"]},
    "typescript": {"aliases": ["ts"], "targets": ["windows", "linux"], "level": "planned",
                   "toolchain": "TypeScript 6.0", "checks": []},
    "rust": {"aliases": ["rs"], "targets": ["windows", "linux"], "level": "planned",
             "toolchain": "Rust 1.97.0", "checks": []},
    "csharp": {"aliases": ["c#", "cs", "dotnet"], "targets": ["windows", "linux"], "level": "planned",
               "toolchain": ".NET 10 LTS", "checks": []},
    "java": {"aliases": [], "targets": ["windows", "linux"], "level": "planned",
             "toolchain": "JDK LTS", "checks": []},
    "cpp": {"aliases": ["c++", "cc"], "targets": ["windows", "linux"], "level": "planned",
            "toolchain": "Clang/GCC/MSVC", "checks": []},
}


def normalize(value: str) -> str:
    candidate = str(value or "").strip().casefold()
    if candidate in PROFILES:
        return candidate
    for language, profile in PROFILES.items():
        if candidate in profile["aliases"]:
            return language
    return candidate


def profile(language: str) -> dict[str, Any] | None:
    normalized = normalize(language)
    value = PROFILES.get(normalized)
    return {"language": normalized, **value} if value else None


def matrix() -> list[dict[str, Any]]:
    return [profile(language) for language in PROFILES if profile(language) is not None]


def is_certified(language: str, target: str | None = None) -> bool:
    value = profile(language)
    return bool(
        value
        and value["level"] == "certified"
        and (not target or str(target).casefold() in value["targets"])
    )


def can_cross_compile(language: str, target: str) -> bool:
    value = profile(language)
    return bool(value and str(target).casefold() in value.get("cross_targets", []))
