"""Contrôles statiques de la configuration SearXNG versionnée de Marvin."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "docker" / "searxng" / "settings.yml.example"
LAUNCHER_PATH = ROOT / "docker" / "searxng" / "start-searxng.ps1"
COMPOSE_PATH = ROOT / "docker" / "searxng" / "docker-compose.yml"
RESOLVER_PATH = ROOT / "scripts" / "resolve-searxng-port.ps1"
REQUIRED_TAB_COVERAGE = {
    "general": 2,
    "images": 2,
    "videos": 2,
    "news": 2,
    "map": 2,
    "music": 2,
    "it": 2,
    "science": 2,
    "files": 2,
    "social media": 2,
    "shopping": 2,
}


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
        "bandcamp",
        "soundcloud",
        "dailymotion",
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
        "apple maps",
        "reuters",
        "flickr",
        "tmdb",
    }

    assert required_general <= kept
    assert required_specialized <= kept
    assert kept == enabled
    assert "brave" not in kept
    assert "duckduckgo" not in kept
    assert settings["server"]["limiter"] is False
    assert settings["server"]["image_proxy"] is False
    assert {"html", "json"} <= set(settings["search"]["formats"])


def test_every_search_tab_has_redundant_engine_coverage() -> None:
    settings = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
    enabled = {
        engine["name"]: engine
        for engine in settings["engines"]
        if engine.get("disabled") is False
    }

    default_categories = {
        "bing": {"general"},
        "google cse": {"general"},
        "bing images": {"images"},
        "google cse images": {"images"},
        "bing news": {"news"},
        "google news": {"news"},
        "bing videos": {"videos"},
        "youtube": {"videos", "music"},
        "openstreetmap": {"map"},
        "photon": {"map"},
        "github": {"it"},
        "stackoverflow": {"it"},
        "arxiv": {"science"},
        "semantic scholar": {"science"},
        "apple app store": {"files"},
        "google play apps": {"files"},
        "reddit": {"social media"},
        "geizhals": {"shopping"},
        "bandcamp": {"music"},
        "soundcloud": {"music"},
        "dailymotion": {"videos"},
        "apple maps": {"map"},
    }
    coverage = {category: set() for category in REQUIRED_TAB_COVERAGE}
    for name, engine in enabled.items():
        configured = engine.get("categories")
        categories = (
            {configured}
            if isinstance(configured, str)
            else set(configured or default_categories.get(name, set()))
        )
        for category in coverage:
            if category in categories:
                coverage[category].add(name)

    for category, minimum in REQUIRED_TAB_COVERAGE.items():
        assert len(coverage[category]) >= minimum, (
            f"L'onglet {category!r} n'a que {sorted(coverage[category])}; "
            f"{minimum} moteurs actifs sont requis."
        )


def test_network_budgets_are_bounded() -> None:
    settings = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
    outgoing = settings["outgoing"]

    assert 3.0 <= outgoing["request_timeout"] <= 10.0
    assert outgoing["request_timeout"] <= outgoing["max_request_timeout"] <= 20.0
    assert 1 <= outgoing["pool_maxsize"] <= outgoing["pool_connections"] <= 200


def test_launcher_forces_reload_and_checks_effective_config() -> None:
    launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    resolver = RESOLVER_PATH.read_text(encoding="utf-8")

    assert "Set-StrictMode -Version Latest" in launcher
    assert "@('compose', 'up', '-d', '--remove-orphans')" in launcher
    assert "Invoke-DockerComposeUp -DockerPath" in launcher
    assert "$Process.WaitForExit(900000)" in launcher
    assert "MARVIN_SEARXNG_CONFIG_SHA256" in launcher
    assert "MARVIN_SETTINGS_SHA256" in compose
    assert "--force-recreate" not in launcher
    assert 'Invoke-RestMethod -Uri "http://localhost:$port/config"' in launcher
    assert '$tabCount -lt 2' in launcher
    assert "Onglets sans redondance moteur" in launcher
    assert '$settingsPath + ".bak"' in launcher
    assert "resolve-searxng-port.ps1" in launcher
    assert "$env:SEARXNG_PORT" in launcher
    assert "@('port', 'marvin-searxng', '8080/tcp')" in launcher
    assert "Get-ExistingSearxngPort" in launcher
    assert "$Process.WaitForExit(10000)" in launcher
    assert "$Process.WaitForExit()" in launcher
    assert "[System.IO.File]::ReadAllText($Stdout).Trim()" in launcher
    assert "$ServerVersion -match" in launcher
    assert '"http://127.0.0.1:$candidate/config"' in launcher
    assert "127.0.0.1:${SEARXNG_PORT:-8890}:8080" in compose
    assert "TcpListener" in resolver
    assert "runtime\\searxng" in resolver


def test_launcher_recovers_known_docker_socket_crash_without_data_reset() -> None:
    launcher = LAUNCHER_PATH.read_text(encoding="utf-8")

    assert "function Test-DockerStaleSocketCrash" in launcher
    assert "function Repair-DockerStaleSocketCrash" in launcher
    assert "EnableInference = $false" in launcher
    assert "EnableInferenceGPUVariant = $false" in launcher
    assert "pre-marvin-socket-recovery-" in launcher
    assert "docker-secrets-engine" in launcher
    assert "Runtime Docker preserve" in launcher
    assert "Start-Process $dockerDesktop -WindowStyle Hidden" in launcher
    assert "$MaxSocketRecoveryAttempts = 3" in launcher
    assert "Get-Content -LiteralPath $LogPath -Tail 500" in launcher
    assert "UtcNow.AddMinutes(-30)" in launcher
    assert "$script:LastRecoveredDockerCrashLine" in launcher
    assert "function Test-DockerStartupBackoff" in launcher
    assert "function Set-DockerStartupBackoff" in launcher
    assert "function Clear-DockerStartupBackoff" in launcher
    assert "docker-startup-backoff.json" in launcher
    assert "StartupOrigin -eq 'marvin-background'" in launcher
    assert "user_data_modified = $false" in launcher
    assert "Reset to factory defaults" not in launcher
    assert "docker volume rm" not in launcher
    assert "docker system prune" not in launcher


if __name__ == "__main__":
    test_engine_pool_is_broad_explicit_and_private()
    test_every_search_tab_has_redundant_engine_coverage()
    test_network_budgets_are_bounded()
    test_launcher_forces_reload_and_checks_effective_config()
    test_launcher_recovers_known_docker_socket_crash_without_data_reset()
    print("Configuration SearXNG OK")
