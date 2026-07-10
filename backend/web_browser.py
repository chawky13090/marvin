"""
Accès web par VRAI navigateur (Playwright + Chrome installé).

Pourquoi : l'outil web interne (httpx) se fait bloquer par Google & co. car il
« ressemble » à un bot. Ici on pilote un vrai Chrome (vraie empreinte) → bien
moins bloqué, et on rend le JavaScript (sites dynamiques).

Le navigateur est lancé une fois puis réutilisé (rapide). Best-effort : si le
navigateur est indisponible, les outils retombent sur l'outil web interne.
"""
import asyncio
import urllib.parse

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_pw = None
_browser = None
_lock = asyncio.Lock()


async def _get_browser():
    global _pw, _browser
    async with _lock:
        if _browser is not None:
            try:
                if _browser.is_connected():
                    return _browser
            except Exception:
                pass
        from playwright.async_api import async_playwright
        if _pw is None:
            _pw = await async_playwright().start()
        args = ["--disable-blink-features=AutomationControlled", "--no-sandbox",
                "--disable-dev-shm-usage"]
        try:
            _browser = await _pw.chromium.launch(channel="chrome", headless=True, args=args)
        except Exception:
            # repli : chromium intégré de Playwright (si « playwright install » a été fait)
            _browser = await _pw.chromium.launch(headless=True, args=args)
        return _browser


async def _new_context():
    b = await _get_browser()
    return await b.new_context(user_agent=_UA, viewport={"width": 1280, "height": 900},
                               locale="fr-FR", extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"})


def _decode_ddg(url: str) -> str:
    """Les liens DuckDuckGo sont des redirections (…/l/?uddg=…) → on extrait l'URL réelle."""
    if "uddg=" in url:
        try:
            q = urllib.parse.urlparse(url).query
            uddg = urllib.parse.parse_qs(q).get("uddg", [None])[0]
            if uddg:
                return urllib.parse.unquote(uddg)
        except Exception:
            pass
    if url.startswith("//"):
        return "https:" + url
    return url


async def fetch_text(url: str, timeout: int = 25000, max_chars: int = 8000) -> dict:
    """Ouvre une URL dans un vrai navigateur et renvoie son texte lisible."""
    ctx = await _new_context()
    try:
        page = await ctx.new_page()
        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        await page.wait_for_timeout(700)   # laisser le JS se poser
        data = await page.evaluate(
            """() => {
                document.querySelectorAll('script,style,nav,footer,header,noscript,svg,iframe').forEach(e=>e.remove());
                return { title: document.title || '', text: (document.body && document.body.innerText) || '' };
            }"""
        )
        return {"title": data.get("title", ""), "text": (data.get("text") or "").strip()[:max_chars], "url": page.url}
    finally:
        await ctx.close()


async def search(query: str, n: int = 6) -> list:
    """Recherche web via DuckDuckGo (HTML, peu bloquant) avec un vrai navigateur."""
    ctx = await _new_context()
    try:
        page = await ctx.new_page()
        await page.goto("https://duckduckgo.com/html/?q=" + urllib.parse.quote(query),
                        timeout=25000, wait_until="domcontentloaded")
        results = await page.evaluate(
            """(n) => {
                const out=[];
                document.querySelectorAll('.result, .web-result').forEach(r=>{
                    const a = r.querySelector('.result__a, a.result__url, h2 a');
                    const s = r.querySelector('.result__snippet');
                    if (a) out.push({ title:(a.innerText||'').trim(), url:a.href, snippet:(s?s.innerText:'').trim() });
                });
                return out.slice(0, n);
            }""", n)
        for r in results:
            r["url"] = _decode_ddg(r.get("url", ""))
        return [r for r in results if r.get("url", "").startswith("http")]
    finally:
        await ctx.close()


async def close():
    global _browser, _pw
    try:
        if _browser:
            await _browser.close()
    except Exception:
        pass
    try:
        if _pw:
            await _pw.stop()
    except Exception:
        pass
    _browser = None
    _pw = None
