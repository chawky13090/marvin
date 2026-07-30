"""Contrôles statiques de la configuration SearXNG versionnée de Marvin."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "docker" / "searxng" / "settings.yml.example"
LAUNCHER_PATH = ROOT / "docker" / "searxng" / "start-searxng.ps1"


def test_engine_pool_is_broad_explicit_and_private() -> None:
    settings = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
    kept = set(settings["use_default_settings"]["engines"]["keep_only"])
    enabled = {
        engine["name"]
        for engine in settings["engines"]
        if engine.get("disabled") is False
    }

    required_general = {
        "bing",
        "google cse",
        "dogpile",
        "yandex",
        "baidu",
        "naver",
        "seznam",
    }
    required_specialized = {
        "bing news",
        "google news",
        "bing images",
        "google cse images",
        "github",
        "stackoverflow",
        "arxiv",
        "semantic scholar",
        "openalex",
        "pubmed",
        "crossref",
        "youtube",
        "lemmy posts",
        "mastodon users",
        "pinterest",
        "hackernews",
        "gitlab",
        "huggingface",
        "apple app store",
        "google play apps",
        "geizhals",
        "openstreetmap",
        "reuters",
    }

    assert required_general <= kept
    assert required_specialized <= kept
    assert kept == enabled
    assert "brave" not in kept
    assert "duckduckgo" not in kept
    assert settings["server"]["limiter"] is False
    assert settings["server"]["image_proxy"] is False
    assert {"html", "json"} <= set(settings["search"]["formats"])


def test_network_budgets_are_bounded() -> None:
    settings = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
    outgoing = settings["outgoing"]

    assert 3.0 <= outgoing["request_timeout"] <= 10.0
    assert outgoing["request_timeout"] <= outgoing["max_request_timeout"] <= 20.0
    assert 1 <= outgoing["pool_maxsize"] <= outgoing["pool_connections"] <= 200


def test_launcher_forces_reload_and_checks_effective_config() -> None:
    launcher = LAUNCHER_PATH.read_text(encoding="utf-8")

    assert "Set-StrictMode -Version Latest" in launcher
    assert "docker compose up -d --force-recreate" in launcher
    assert 'Invoke-RestMethod -Uri "http://localhost:$port/config"' in launcher
    assert '$settingsPath + ".bak"' in launcher


if __name__ == "__main__":
    test_engine_pool_is_broad_explicit_and_private()
    test_network_budgets_are_bounded()
    test_launcher_forces_reload_and_checks_effective_config()
    print("Configuration SearXNG OK")
