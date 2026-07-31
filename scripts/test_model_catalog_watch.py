"""Regression : veille du catalogue de modeles Ollama Cloud (v2.524).

`model_market.RECOMMENDED_CLOUD_MODELS`/`DISCOVERABLE_CLOUD_MODELS` sont codes en dur
et ne se mettent jamais a jour tout seuls. Ces tests verifient, contre le VRAI catalogue
public d'Ollama (`https://ollama.com/api/tags`, endpoint officiel sans authentification),
que la veille detecte reellement des nouveautes, degrade proprement sur toute panne, et
ne declenche JAMAIS d'installation.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import model_catalog_watch as watch
import model_market


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


def _isolate(tmp: Path) -> None:
    watch.STATE_PATH = tmp / "model_catalog_watch.json"


def _check_normalizes_both_cloud_suffix_styles() -> None:
    """`:cloud` et `-cloud` coexistent dans DISCOVERABLE_CLOUD_MODELS ; les deux
    doivent se normaliser vers le nom brut que renvoie le catalogue distant."""
    assert "deepseek-v4-pro:cloud" in model_market.DISCOVERABLE_CLOUD_MODELS
    assert "qwen3.5:397b-cloud" in model_market.DISCOVERABLE_CLOUD_MODELS
    known = watch._known_models()
    assert "deepseek-v4-pro" in known
    assert "qwen3.5:397b" in known
    assert not any(name.endswith(("-cloud", ":cloud")) for name in known)


async def _check_real_catalog_detects_novelty(tmp: Path) -> None:
    """Interroge le VRAI catalogue Ollama. Sauté proprement si hors-ligne."""
    _isolate(tmp)
    try:
        result = await watch.refresh(force=True)
    except Exception:
        print("  (réseau indisponible pendant le test — cas réel sauté, non simulé)")
        return
    if not result.get("success"):
        print(f"  (catalogue distant injoignable maintenant : {result.get('error')} — sauté)")
        return
    assert result["catalog_size"] > 0
    assert isinstance(result["new_models"], list)
    # Deuxième appel immédiat sans force : doit être throttlé, pas un nouvel appel réseau.
    throttled = await watch.refresh(force=False)
    assert throttled.get("skipped") is True
    assert throttled.get("reason") == "too_soon"


async def _check_degrades_on_connection_failure(tmp: Path) -> None:
    _isolate(tmp)
    import outbound_http
    original = outbound_http.fetch_public

    async def boom(*args, **kwargs):
        raise ConnectionError("panne simulée")

    outbound_http.fetch_public = boom
    try:
        result = await watch.refresh(force=True)
    finally:
        outbound_http.fetch_public = original
    assert result.get("success") is False
    assert "panne simulée" in result["error"]
    # L'échec doit être persisté sans jamais lever d'exception vers l'appelant.
    state = watch.status()
    assert state["last_error"]


async def _check_degrades_on_bad_status(tmp: Path) -> None:
    _isolate(tmp)
    import outbound_http
    original = outbound_http.fetch_public

    async def bad_status(*args, **kwargs):
        return _FakeResponse(503, b"")

    outbound_http.fetch_public = bad_status
    try:
        result = await watch.refresh(force=True)
    finally:
        outbound_http.fetch_public = original
    assert result.get("success") is False
    assert "503" in result["error"]


async def _check_degrades_on_schema_change(tmp: Path) -> None:
    """Le fournisseur peut changer son format sans préavis : jamais de crash."""
    _isolate(tmp)
    import outbound_http
    original = outbound_http.fetch_public

    async def weird_schema(*args, **kwargs):
        return _FakeResponse(200, b'{"totally": "different"}')

    outbound_http.fetch_public = weird_schema
    try:
        result = await watch.refresh(force=True)
    finally:
        outbound_http.fetch_public = original
    assert result.get("success") is False
    assert "parse_error" in result["error"]

    async def invalid_json(*args, **kwargs):
        return _FakeResponse(200, b"ceci n'est pas du JSON")

    outbound_http.fetch_public = invalid_json
    try:
        result = await watch.refresh(force=True)
    finally:
        outbound_http.fetch_public = original
    assert result.get("success") is False


async def _check_never_installs(tmp: Path) -> None:
    """La veille ne doit référencer AUCUNE fonction d'installation."""
    source = (BACKEND / "model_catalog_watch.py").read_text(encoding="utf-8")
    for forbidden in ("pull_cloud_model", "winget", "ollama pull", "subprocess"):
        assert forbidden not in source, f"la veille ne doit jamais installer ({forbidden})"


async def _run_all() -> None:
    _check_normalizes_both_cloud_suffix_styles()
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        await _check_real_catalog_detects_novelty(tmp)
        await _check_degrades_on_connection_failure(tmp)
        await _check_degrades_on_bad_status(tmp)
        await _check_degrades_on_schema_change(tmp)
        await _check_never_installs(tmp)


def main() -> int:
    asyncio.run(_run_all())
    print(
        "Model Catalog Watch OK - normalisation des suffixes, degradation propre "
        "sur toute panne, aucune installation automatique."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
