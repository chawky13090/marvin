"""Domaine Web : recherche multi-provider, lecture et recherche approfondie."""
from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import outbound_http
import tool_activity

Generator = Callable[..., Awaitable[str]]
GetSetting = Callable[[str], Any]
HttpClientFactory = Callable[[], Any]
CacheGet = Callable[[Any], Any]
CacheSet = Callable[[Any, Any], None]
NetError = Callable[[Exception, str], dict[str, Any]]

async def _missing_generate(prompt: str, **kwargs: Any) -> str:
    raise RuntimeError("G?n?rateur Web non configur?.")
def _missing_setting(key: str) -> Any:
    return None
def _missing_http_client() -> Any:
    raise RuntimeError("Client HTTP Web non configur?.")
def _missing_cache_get(key: Any) -> Any:
    return None
def _missing_cache_set(key: Any, value: Any) -> None:
    return None
def _default_net_error(exc: Exception, what: str) -> dict[str, Any]:
    return {"error": str(exc)}

_generate: Generator = _missing_generate
_get_setting: GetSetting = _missing_setting
_get_http_client: HttpClientFactory = _missing_http_client
_wcache_get: CacheGet = _missing_cache_get
_wcache_set: CacheSet = _missing_cache_set
_net_error: NetError = _default_net_error

def configure(*, generate: Generator, get_setting: GetSetting,
              get_http_client: HttpClientFactory, cache_get: CacheGet,
              cache_set: CacheSet, net_error: NetError) -> None:
    global _generate, _get_setting, _get_http_client, _wcache_get, _wcache_set, _net_error
    _generate = generate
    _get_setting = get_setting
    _get_http_client = get_http_client
    _wcache_get = cache_get
    _wcache_set = cache_set
    _net_error = net_error


async def _execute_web_search_legacy(args: dict) -> dict:
    """Recherche web multi-provider : DuckDuckGo (gratuit) + Brave/Google/SerpAPI si clé dispo."""
    query = str(args.get("query") or "").strip()
    provider = str(args.get("provider") or "auto").strip().lower()
    if not query:
        return {"error": "Requête vide"}
    allowed_providers = {"auto", "duckduckgo", "searxng", "brave", "google", "serpapi"}
    if provider not in allowed_providers:
        return {
            "error": (
                "Provider invalide : auto, duckduckgo, searxng, brave, google "
                "ou serpapi attendu."
            )
        }
    try:
        max_results = max(1, min(int(args.get("max_results", 8)), 20))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'max_results' invalide : entier attendu entre 1 et 20."}

    # ── Cache TTL : une requête identique récente est servie instantanément ────
    _ck = ("ws", provider, query.strip().lower(), int(max_results))
    _cached = _wcache_get(_ck)
    if _cached is not None:
        return {**_cached, "cached": True}

    import credentials_manager as cm

    # ── DuckDuckGo (aucune clé requise) ───────────────────────────────────────
    def _parse_ddg(html_text):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text, "lxml")
        out = []
        for r in soup.select(".result__body")[:max_results]:
            title_el = r.select_one(".result__a")
            snippet_el = r.select_one(".result__snippet")
            if title_el:
                out.append({"title": title_el.get_text(strip=True),
                            "url": title_el.get("href", ""),
                            "snippet": snippet_el.get_text(strip=True) if snippet_el else ""})
        return out

    def _parse_ddg_lite(html_text):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text, "lxml")
        links = soup.select("a.result-link")
        snips = soup.select("td.result-snippet")
        out = []
        for i, a in enumerate(links[:max_results]):
            out.append({"title": a.get_text(strip=True), "url": a.get("href", ""),
                        "snippet": snips[i].get_text(strip=True) if i < len(snips) else ""})
        return out

    async def _ddg(attempt=0):
        # v2.161 : le blocage anti-bot de DuckDuckGo est généralement de courte durée
        # (quelques dizaines de secondes) — 1 seul retry à 1,6s (avant) échouait souvent
        # encore dedans. Passé à 3 tentatives avec un backoff croissant (2s/5s/9s,
        # ~16s cumulés) pour couvrir la fenêtre réelle du blocage sans faire attendre
        # indéfiniment l'utilisateur.
        _BACKOFFS = (2.0, 5.0, 9.0)
        try:
            client = _get_http_client()                       # client partagé (pooling)
            # endpoint principal puis 'lite' (profil anti-bot différent) en secours
            results = []
            for endpoint, parser in (("https://html.duckduckgo.com/html/", _parse_ddg),
                                     ("https://lite.duckduckgo.com/lite/", _parse_ddg_lite)):
                resp = await client.post(endpoint, data={"q": query})
                resp.raise_for_status()
                results = parser(resp.text)
                if results:
                    break
            if not results and attempt < len(_BACKOFFS):
                # 0 résultat sur une requête non vide → souvent une limite anti-bot
                # temporaire → nouvelle tentative espacée.
                await asyncio.sleep(_BACKOFFS[attempt])
                return await _ddg(attempt=attempt + 1)
            if not results:
                return {"success": False, "provider": "DuckDuckGo", "query": query,
                        "count": 0, "results": [], "rate_limited": True,
                        "error": "Recherche web temporairement limitée (anti-bot). Réessayez dans un instant, "
                                 "ou configurez un provider alternatif (SearXNG auto-hébergé, Brave, Google) "
                                 "dans Réglages > Connexions pour ne plus dépendre de DuckDuckGo."}
            return {"success": True, "provider": "DuckDuckGo", "query": query,
                    "count": len(results), "results": results}
        except Exception as e:
            return _net_error(e, "DuckDuckGo")

    # ── SearXNG auto-hébergé (v2.161) ────────────────────────────────────────
    # Méta-moteur open source qu'on héberge soi-même (Docker) — agrège plusieurs
    # moteurs (Google, Bing, Brave, Qwant...) sans jamais exposer NOTRE IP directement
    # à leur anti-bot (SearXNG gère ça lui-même), et sans aucune limite de quota
    # puisqu'on ne dépend d'aucune clé API tierce. Prioritaire en mode auto quand
    # configuré : gratuit, illimité, 100% cohérent avec la doctrine "local d'abord"
    # de Marvin. Nécessite `searxng_url` (Réglages > Connexions) pointant vers une
    # instance avec `formats: [html, json]` activé dans son settings.yml (le JSON
    # n'est PAS activé par défaut sur une install SearXNG standard).
    async def _searxng():
        base = cm.get_credential("searxng_url")
        if not base:
            return None
        try:
            client = _get_http_client()
            resp = await client.get(base.rstrip("/") + "/search",
                                     params={"q": query, "format": "json"})
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in (data.get("results") or [])[:max_results]:
                results.append({"title": item.get("title", ""), "url": item.get("url", ""),
                                 "snippet": item.get("content", "")})
            if not results:
                return {"error": "SearXNG : 0 résultat (instance mal configurée ou JSON désactivé ?)"}
            return {"success": True, "provider": "SearXNG", "query": query,
                    "count": len(results), "results": results}
        except Exception as e:
            return {"error": f"SearXNG ({base}) : {e}"}

    # ── Brave Search ──────────────────────────────────────────────────────────
    async def _brave():
        api_key = cm.get_credential("brave_search_api_key")
        if not api_key:
            return None
        try:
            import httpx
            headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key}
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": max_results},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            results = []
            for item in data.get("web", {}).get("results", [])[:max_results]:
                results.append({"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("description", "")})
            return {"success": True, "provider": "Brave Search", "query": query, "count": len(results), "results": results}
        except Exception as e:
            return {"error": f"Brave: {e}"}

    # ── Google Custom Search ──────────────────────────────────────────────────
    async def _google():
        api_key = cm.get_credential("google_search_api_key")
        cx = cm.get_credential("google_search_cx")
        if not api_key or not cx:
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={"key": api_key, "cx": cx, "q": query, "num": min(max_results, 10)},
                )
                resp.raise_for_status()
                data = resp.json()
            results = []
            for item in data.get("items", [])[:max_results]:
                results.append({"title": item.get("title", ""), "url": item.get("link", ""), "snippet": item.get("snippet", "")})
            return {"success": True, "provider": "Google", "query": query, "count": len(results), "results": results}
        except Exception as e:
            return {"error": f"Google: {e}"}

    # ── SerpAPI ───────────────────────────────────────────────────────────────
    async def _serpapi():
        api_key = cm.get_credential("serpapi_key")
        if not api_key:
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://serpapi.com/search",
                    params={"q": query, "api_key": api_key, "num": max_results},
                )
                resp.raise_for_status()
                data = resp.json()
            results = []
            for item in data.get("organic_results", [])[:max_results]:
                results.append({"title": item.get("title", ""), "url": item.get("link", ""), "snippet": item.get("snippet", "")})
            return {"success": True, "provider": "SerpAPI", "query": query, "count": len(results), "results": results}
        except Exception as e:
            return {"error": f"SerpAPI: {e}"}

    # ── Sélection du provider ─────────────────────────────────────────────────
    if provider == "searxng":
        result = await _searxng()
        return result or {"error": "Instance SearXNG non configurée (réglage 'searxng_url')."}
    if provider == "brave":
        result = await _brave()
        return result or {"error": "Clé Brave Search non configurée"}
    if provider == "google":
        result = await _google()
        return result or {"error": "Clés Google Search non configurées"}
    if provider == "serpapi":
        result = await _serpapi()
        return result or {"error": "Clé SerpAPI non configurée"}
    if provider == "duckduckgo":
        r = await _ddg()
        if r.get("success"):
            _wcache_set(_ck, r)
        return r

    # Auto : SearXNG d'abord (auto-hébergé → gratuit, illimité, aucun anti-bot tiers
    # si configuré), puis brave → google → serpapi → duckduckgo (scraping HTML, en
    # dernier recours seulement — le plus fragile face à l'anti-bot).
    attempts: list[dict[str, str]] = []
    for name, fn in (
        ("SearXNG", _searxng),
        ("Brave Search", _brave),
        ("Google", _google),
        ("SerpAPI", _serpapi),
    ):
        r = await fn()
        if r is None:
            attempts.append({"provider": name, "status": "not_configured"})
            continue
        if r and r.get("success"):
            r["provider_attempts"] = attempts + [{"provider": name, "status": "succeeded"}]
            r["fallback_used"] = name != "SearXNG"
            r["provider_priority"] = "SearXNG"
            _wcache_set(_ck, r)
            return r
        attempts.append({"provider": name, "status": "failed"})
    r = await _ddg()
    if r.get("success"):
        r["provider_attempts"] = attempts + [{"provider": "DuckDuckGo", "status": "succeeded"}]
        r["fallback_used"] = True
        r["provider_priority"] = "SearXNG"
        _wcache_set(_ck, r)
    elif isinstance(r, dict):
        r["provider_attempts"] = attempts + [{"provider": "DuckDuckGo", "status": "failed"}]
        r["fallback_used"] = True
        r["provider_priority"] = "SearXNG"
    return r


async def execute_web_search(args: dict) -> dict:
    """Recherche Web exclusivement via l'instance SearXNG configurée."""
    query = str(args.get("query") or "").strip()
    provider = str(args.get("provider") or "auto").strip().lower()
    if not query:
        return {"success": False, "provider": "SearXNG", "error": "Requête vide"}
    if provider not in {"auto", "searxng"}:
        return {
            "success": False,
            "provider": "SearXNG",
            "error": "Provider invalide : SearXNG est l'unique fournisseur autorisé.",
        }
    try:
        max_results = max(1, min(int(args.get("max_results", 8)), 20))
    except (TypeError, ValueError):
        return {
            "success": False,
            "provider": "SearXNG",
            "error": "Paramètre 'max_results' invalide : entier attendu entre 1 et 20.",
        }

    cache_key = ("ws-searxng-only", query.lower(), max_results)
    cached = _wcache_get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    import credentials_manager as cm
    base = cm.get_credential("searxng_url")
    if not base:
        return {
            "success": False,
            "provider": "SearXNG",
            "query": query,
            "count": 0,
            "results": [],
            "provider_attempts": [{"provider": "SearXNG", "status": "not_configured"}],
            "fallback_used": False,
            "provider_priority": "SearXNG",
            "error": "Instance SearXNG non configurée (réglage 'searxng_url').",
        }
    try:
        client = _get_http_client()
        response = await client.get(
            str(base).rstrip("/") + "/search",
            params={"q": query, "format": "json"},
        )
        response.raise_for_status()
        payload = response.json()
        results = [
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("content") or ""),
            }
            for item in list(payload.get("results") or [])[:max_results]
            if item.get("url")
        ]
        receipt = {
            "success": bool(results),
            "provider": "SearXNG",
            "query": query,
            "count": len(results),
            "results": results,
            "provider_attempts": [{
                "provider": "SearXNG",
                "status": "succeeded" if results else "failed",
            }],
            "fallback_used": False,
            "provider_priority": "SearXNG",
        }
        if not results:
            receipt["error"] = "SearXNG n'a retourné aucun résultat."
        else:
            _wcache_set(cache_key, receipt)
        return receipt
    except Exception as exc:
        return {
            "success": False,
            "provider": "SearXNG",
            "query": query,
            "count": 0,
            "results": [],
            "provider_attempts": [{"provider": "SearXNG", "status": "failed"}],
            "fallback_used": False,
            "provider_priority": "SearXNG",
            "error": f"SearXNG inaccessible : {type(exc).__name__}",
        }


async def _priority_search(query: str, max_results: int) -> dict[str, Any]:
    """Recherche via la chaîne officielle : SearXNG d'abord, replis seulement ensuite."""
    result = await execute_web_search({
        "query": query,
        "provider": "auto",
        "max_results": max_results,
    })
    if not isinstance(result, dict):
        return {"success": False, "results": [], "error": "Réponse de recherche invalide."}
    return result


def _fallback_complement_query(query: str, round_index: int) -> str:
    angles = (
        "sources officielles documentation données primaires",
        "actualités récentes avis indépendants réseaux sociaux",
        "mentions légales registre entreprise chiffres vérification",
    )
    return f"{query} {angles[min(max(round_index, 0), len(angles) - 1)]}"[:150]


def _clean_search_query(value: str) -> str:
    """Neutralise le formatage bavard du LLM sans modifier les termes recherchés."""
    return " ".join(str(value or "").replace('"', " ").replace("'", " ").split())[:150]


async def execute_web_browse(args: dict) -> dict:
    """Récupère et extrait le texte d'une page web."""
    url = str(args.get("url") or "").strip()
    # v2.125 — plafond abaissé (25000/60000 → 12000/20000). Trouvé en conditions réelles :
    # une conversation avec ~15 appels `web_browse` en rafale cumulait jusqu'à 118 000
    # caractères réinjectés au modèle à CHAQUE tour suivant (chaque résultat reste dans
    # l'historique pour tout le reste de la boucle d'outils) — l'appel au modèle cloud
    # devenait de plus en plus lourd et lent à chaque itération, jusqu'à plusieurs minutes
    # sans rien afficher côté utilisateur ("Marvin reste à réfléchir"). 12k caractères
    # suffisent largement pour un résumé/Q&A — un extrait plus long peut toujours être
    # redemandé explicitement via `max_chars` si un cas précis le justifie.
    try:
        max_chars = max(1000, min(int(args.get("max_chars", 12000)), 20000))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'max_chars' invalide : entier attendu entre 1000 et 20000."}
    if not url:
        return {"error": "URL requise"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        from bs4 import BeautifulSoup
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        response = await outbound_http.fetch_public(
            url,
            max_bytes=1_000_000,
            timeout=20.0,
            headers=headers,
        )
        final_url = response.url
        # Don't raise_for_status — instead report the status in the result
        if response.status_code >= 400:
            return {
                "success": False,
                "url": final_url,
                "status": response.status_code,
                "error": f"HTTP {response.status_code} pour {final_url}",
                "content": "",
            }
        soup = BeautifulSoup(
            response.content.decode("utf-8", errors="replace"),
            "lxml",
        )

        # Extraire le titre et la description
        title = (soup.title.string or "").strip() if soup.title else url
        description = ""
        meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if meta_desc:
            description = meta_desc.get("content", "").strip()

        # Supprimer les éléments non-contenu
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form",
                          "iframe", "noscript", "svg", "button", "input", "select"]):
            tag.decompose()

        # Extraire le texte principal (préférer article > main > body)
        main = (soup.find("article") or soup.find("main") or
                soup.find(id="content") or soup.find(class_=["content", "article", "post", "main-content"]) or
                soup.find("body"))
        if main:
            text = main.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        # Nettoyer les lignes vides consécutives
        lines = [l for l in text.splitlines() if l.strip()]
        cleaned = "\n".join(lines)[:max_chars]

        return {
            "success": True,
            "url": final_url,
            "title": title,
            "description": description,
            "content": cleaned,
            "length": len(cleaned),
            "truncated": len(cleaned) >= max_chars,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_url_analyze(args: dict) -> dict:
    """Analyse les métadonnées d'une URL publique via le transport SSRF partagé."""
    url = str(args.get("url") or "").strip()
    if not url:
        return {"error": "Paramètre 'url' requis."}
    if len(url) > 8_192:
        return {"error": "URL limitée à 8 192 caractères."}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        from bs4 import BeautifulSoup

        response = await outbound_http.fetch_public(
            url,
            max_bytes=60_000,
            timeout=10.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MarvinBot/2.368)"},
        )
        content_type = response.headers.get("content-type", "")
        body = (
            response.content.decode("utf-8", errors="replace")
            if "html" in content_type.casefold()
            else ""
        )
        soup = BeautifulSoup(body, "lxml") if body else None
        title = ""
        description = ""
        canonical = ""
        if soup is not None:
            if soup.title:
                title = " ".join(soup.title.get_text(" ", strip=True).split())[:200]
            meta = soup.find(
                "meta",
                attrs={
                    "name": lambda value: (
                        isinstance(value, str)
                        and value.casefold() == "description"
                    )
                },
            )
            if meta:
                description = " ".join(
                    str(meta.get("content") or "").split()
                )[:500]
            for link in soup.find_all("link", href=True):
                relation = link.get("rel") or []
                relations = (
                    [str(item).casefold() for item in relation]
                    if isinstance(relation, list)
                    else str(relation).casefold().split()
                )
                if "canonical" in relations:
                    canonical = str(link.get("href") or "").strip()[:8_192]
                    break
        return {
            "success": True,
            "url": response.url,
            "status": response.status_code,
            "response_time_ms": response.elapsed_ms,
            "title": title,
            "description": description,
            "canonical": canonical,
            "content_type": content_type,
            "server": response.headers.get("server", ""),
            "content_length": response.headers.get("content-length", ""),
        }
    except (OSError, TypeError, ValueError, outbound_http.httpx.HTTPError) as exc:
        return {"error": str(exc)}


async def execute_web_browser_open(args: dict) -> dict:
    """Ouvre une page dans un VRAI navigateur (Chrome) et renvoie son texte lisible.
    À utiliser quand l'outil web interne est bloqué, ou pour un site dynamique (JS)."""
    url = str(args.get("url") or "").strip()
    if not url:
        return {"error": "Paramètre 'url' requis."}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        import web_browser as wb
        r = await wb.fetch_text(url)
        return {"success": True, "title": r.get("title", ""), "url": r.get("url", url),
                "text": r.get("text") or "(page vide ou non textuelle)"}
    except Exception as e:
        return {"error": f"Lecture via navigateur échouée : {str(e)[:160]}"}


async def execute_web_research(args: dict) -> dict:
    """Cherche sur le web avec un VRAI navigateur, lit les meilleurs résultats, en tire
    une réponse sourcée, et ENRICHIT la connaissance de Marvin. Pour « cherche sur internet »,
    « trouve la réponse en ligne », quand l'info manque."""
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        return {"error": "Paramètre 'query' requis."}
    await tool_activity.emit(
        "searching",
        "Recherche SearXNG",
        detail="Interrogation de l'index Web.",
    )
    try:
        import web_browser as wb
        search_receipt = await _priority_search(query, 10)
        results = list(search_receipt.get("results") or [])
    except Exception as e:
        return {"error": f"Recherche navigateur échouée : {str(e)[:160]}"}
    if not results:
        return {
            "success": False,
            "answer": "",
            "sources": [],
            "provider": "SearXNG",
            "provider_attempts": search_receipt.get("provider_attempts", []),
            "fallback_used": False,
            "error": str(search_receipt.get("error") or "SearXNG n'a retourné aucun résultat."),
        }
    # Lire le contenu des N meilleurs résultats (profondeur pilotée par le MODE de performance)
    try:
        web_depth = max(3, min(int(args.get("depth") or _get_setting("web_depth") or 3), 6))
    except Exception:
        web_depth = 3
    pages = []
    await tool_activity.emit(
        "reading",
        "Lecture des meilleures sources",
        current=0,
        total=web_depth,
        metrics={"sources_trouvees": len(results)},
    )
    for page_index, res in enumerate(results[:web_depth], start=1):
        try:
            p = await wb.fetch_text(res["url"], max_chars=2800)
        except Exception:
            p = None
        pages.append((res, p))
        await tool_activity.emit(
            "reading",
            "Lecture des meilleures sources",
            current=page_index,
            total=web_depth,
            metrics={"sources_trouvees": len(results), "pages_lues": page_index},
        )
    if any(p for _, p in pages):
        context = "\n\n".join(
            f"[{i+1}] {res.get('title', '')} ({res['url']})\n{(p['text'] if p else res.get('snippet', ''))[:1500]}"
            for i, (res, p) in enumerate(pages))
    else:
        context = "\n".join(f"- {r.get('title', '')} : {r.get('snippet', '')}" for r in results)
    prompt = (
        "En te basant UNIQUEMENT sur ces résultats web, réponds à la question en français, "
        "concis et factuel. Indique la source (domaine) si pertinent. Si l'info n'y est pas, dis-le.\n\n"
        f"QUESTION : {query}\n\nRÉSULTATS WEB :\n{context}\n\nRÉPONSE :")
    await tool_activity.emit(
        "synthesizing",
        "Synthèse de la réponse",
        metrics={"sources": len(results[:10]), "pages_lues": len(pages)},
    )
    answer = (await _generate(prompt, model=args.get("model"), timeout=180) or "").strip()
    # Enrichir la base de connaissances (apprentissage)
    try:
        import learning
        if len(answer) > 15:
            await learning.add_qa(query, answer)
    except Exception:
        pass
    return {
        "success": True,
        "answer": answer,
        "sources": [
            {"title": r.get("title", ""), "url": r["url"]}
            for r in results[:10]
        ],
        "provider": search_receipt.get("provider"),
        "provider_attempts": search_receipt.get("provider_attempts", []),
        "fallback_used": bool(search_receipt.get("fallback_used", False)),
        "message": (
            f"Réponse trouvée via {search_receipt.get('provider') or 'le Web'} "
            f"avec {len(results[:10])} source(s) et mémorisée."
        ),
    }


async def execute_web_deep_research(args: dict) -> dict:
    """Recherche approfondie multi-passes sur le web : boucle recherche → identifie les
    angles morts → recherche complémentaire ciblée, plusieurs fois, avant de produire un
    rapport structuré avec citations numérotées. BEAUCOUP plus lent que web_research
    (plusieurs minutes) — réservé aux demandes explicites de recherche exhaustive."""
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        return {"error": "Paramètre 'query' requis."}
    try:
        max_rounds = max(1, min(int(args.get("max_rounds", 4)), 6))
    except Exception:
        max_rounds = 4

    try:
        import web_browser as wb
    except Exception as e:
        return {"error": f"Navigateur web indisponible : {str(e)[:160]}"}

    seen_urls = set()
    sources: list[dict] = []
    queries_done = [query]
    search_receipts: list[dict[str, Any]] = []
    min_rounds = min(max_rounds, max(1, min(int(args.get("min_rounds", 3)), 4)))

    for round_idx in range(max_rounds):
        current_query = _clean_search_query(queries_done[-1])
        queries_done[-1] = current_query
        await tool_activity.emit(
            "searching",
            f"Passe de recherche {round_idx + 1}/{max_rounds}",
            detail="Recherche SearXNG d'un nouvel angle.",
            current=round_idx + 1,
            total=max_rounds,
            metrics={"sources_uniques": len(sources)},
        )
        try:
            search_receipt = await _priority_search(current_query, 10)
            results = list(search_receipt.get("results") or [])
            search_receipts.append({
                "query": current_query,
                "provider": search_receipt.get("provider"),
                "count": len(results),
                "fallback_used": bool(search_receipt.get("fallback_used", False)),
                "provider_attempts": search_receipt.get("provider_attempts", []),
            })
        except Exception:
            results = []
        new_pages = 0
        for res in results:
            url = res.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                p = await wb.fetch_text(url, max_chars=3000)
            except Exception:
                p = None
            text = ((p or {}).get("text") or res.get("snippet", "") or "").strip()
            if text:
                sources.append({"title": res.get("title", ""), "url": url, "text": text[:3000]})
                new_pages += 1
                await tool_activity.emit(
                    "reading",
                    f"Lecture des sources · passe {round_idx + 1}",
                    detail=f"{new_pages}/6 nouvelles pages exploitables.",
                    current=new_pages,
                    total=6,
                    metrics={
                        "resultats": len(results),
                        "sources_uniques": len(sources),
                    },
                )
            if new_pages >= 6:  # corpus riche mais borné à 36 pages au maximum
                break

        if not sources:
            break
        if round_idx >= max_rounds - 1:
            break

        # Le modèle juge si c'est suffisant, sinon propose UNE requête complémentaire
        # courte ciblée sur ce qui manque — c'est ce qui distingue une "recherche
        # approfondie" d'une simple recherche répétée à l'identique.
        digest = "\n\n".join(f"[{i+1}] {s['title']} ({s['url']})\n{s['text'][:800]}"
                              for i, s in enumerate(sources[-8:]))
        await tool_activity.emit(
            "checking",
            "Vérification des angles manquants",
            current=round_idx + 1,
            total=max_rounds,
            metrics={"sources_uniques": len(sources)},
        )
        judge_prompt = (
            f"Question de recherche : {query}\n\n"
            f"Sources déjà trouvées (passe {round_idx+1}/{max_rounds}) :\n{digest}\n\n"
            "Ces sources suffisent-elles pour répondre COMPLÈTEMENT et précisément à la "
            "question ? "
            + (
                f"Il reste des angles obligatoires à explorer avant la passe {min_rounds}; "
                "propose donc UNE requête complémentaire distincte. "
                if round_idx + 1 < min_rounds
                else "Réponds UNIQUEMENT par « SUFFISANT » si oui, ou par "
            )
            + "UNE requête de "
            "recherche COURTE (mots-clés seulement, pas une phrase) pour combler ce qui "
            "manque encore — rien d'autre, pas d'explication."
        )
        try:
            verdict = (await _generate(judge_prompt, model=args.get("model"), timeout=60) or "").strip()
        except Exception:
            verdict = "SUFFISANT"
        candidate = _clean_search_query(verdict)
        duplicate = candidate.lower() in [q.strip().lower() for q in queries_done]
        invalid = not candidate or len(candidate) > 150
        sufficient = candidate.upper().startswith("SUFFISANT")
        if round_idx + 1 < min_rounds and (invalid or sufficient or duplicate):
            candidate = _fallback_complement_query(query, round_idx)
            duplicate = candidate.lower() in [q.strip().lower() for q in queries_done]
        elif invalid or sufficient or duplicate:
            break
        if duplicate:
            break
        queries_done.append(candidate)

    if not sources:
        return {"success": True, "answer": "Aucune source trouvée pour cette recherche.", "sources": []}

    context = "\n\n".join(f"[{i+1}] {s['title']} ({s['url']})\n{s['text'][:2000]}"
                           for i, s in enumerate(sources))
    report_prompt = (
        "Rédige un RAPPORT DE RECHERCHE structuré et complet en français, en te basant "
        "UNIQUEMENT sur les sources ci-dessous. Structure : un résumé en 2-3 phrases, puis "
        "des sections thématiques (## titres), avec une citation [n] après chaque "
        "affirmation factuelle en te référant au numéro de la source correspondante. Sois "
        "factuel, ne comble pas les trous par supposition — dis explicitement si un point "
        "reste incertain plutôt que d'inventer.\n\n"
        f"QUESTION : {query}\n\nSOURCES :\n{context}\n\nRAPPORT :"
    )
    await tool_activity.emit(
        "synthesizing",
        "Rédaction du rapport vérifié",
        detail="Structuration des constats et des citations.",
        current=len(search_receipts),
        total=len(search_receipts),
        metrics={"sources": len(sources), "passes": len(search_receipts)},
    )
    report = (await _generate(report_prompt, model=args.get("model"), timeout=240) or "").strip()

    try:
        import learning
        if len(report) > 15:
            await learning.add_qa(query, report[:2000])
    except Exception:
        pass

    return {
        "success": True,
        "answer": report,
        "rounds": len(search_receipts),
        "queries_used": queries_done,
        "sources": [{"title": s["title"], "url": s["url"]} for s in sources],
        "search_receipts": search_receipts,
        "provider_priority": "SearXNG",
        "fallback_used": any(item["fallback_used"] for item in search_receipts),
        "message": f"Recherche approfondie terminée : {len(sources)} source(s) sur {len(queries_done)} passe(s).",
    }
