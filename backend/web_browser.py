"""
Accès web par VRAI navigateur (Playwright + Chrome installé).

Pourquoi : l'outil web interne (httpx) se fait bloquer par Google & co. car il
« ressemble » à un bot. Ici on pilote un vrai Chrome (vraie empreinte) → bien
moins bloqué, et on rend le JavaScript (sites dynamiques).

Le navigateur est lancé une fois puis réutilisé (rapide). Best-effort : si le
navigateur est indisponible, les outils retombent sur l'outil web interne.
"""
import asyncio
import base64

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_pw = None
_browser = None
_lock = asyncio.Lock()
_computer_context = None
_computer_page = None
_computer_lock = asyncio.Lock()


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


async def _get_computer_page():
    """Retourne une page persistante réservée aux missions Computer Runtime."""
    global _computer_context, _computer_page
    async with _computer_lock:
        if _computer_page is not None:
            try:
                if not _computer_page.is_closed():
                    return _computer_page
            except Exception:
                pass
        _computer_context = await _new_context()
        _computer_page = await _computer_context.new_page()
        return _computer_page


async def computer_observe(max_elements: int = 80) -> dict:
    page = await _get_computer_page()
    elements = await page.locator(
        "a,button,input,textarea,select,[role],[contenteditable=true]"
    ).evaluate_all(
        """(nodes, limit) => nodes.slice(0, limit).map((node, index) => ({
          index,
          tag: node.tagName.toLowerCase(),
          role: node.getAttribute('role') || ({
            a: node.hasAttribute('href') ? 'link' : '',
            button: 'button',
            textarea: 'textbox',
            select: 'combobox',
            input: ['button', 'submit', 'reset'].includes(
              (node.getAttribute('type') || '').toLowerCase()
            ) ? 'button' : 'textbox'
          }[node.tagName.toLowerCase()] || ''),
          name: (node.getAttribute('aria-label') || node.innerText ||
                 node.getAttribute('placeholder') || node.getAttribute('title') || '')
                .trim().slice(0, 240),
          type: node.getAttribute('type') || '',
          disabled: Boolean(node.disabled),
          visible: Boolean(node.getClientRects().length)
        }))""",
        max(1, min(int(max_elements), 100)),
    )
    screenshot = await page.screenshot(type="png")
    return {
        "success": True,
        "title": await page.title(),
        "url": page.url,
        "text": (await page.locator("body").inner_text())[:20_000],
        "elements": elements,
        "image": "data:image/png;base64," + base64.b64encode(screenshot).decode("ascii"),
        "width": 1280,
        "height": 900,
        "coordinate_space": "browser_viewport_pixels",
    }


async def computer_navigate(url: str, timeout: int = 30_000) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # Résolution publique préalable : le navigateur ne devient pas un proxy SSRF
    # vers les services locaux ou les métadonnées cloud.
    import outbound_http

    parsed, port = outbound_http._parse_public_url(url)
    assert parsed.hostname is not None
    outbound_http._public_addresses(
        await outbound_http._resolve(parsed.hostname, port)
    )
    page = await _get_computer_page()
    await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    return await computer_observe()


async def extract_media_urls(url: str, timeout: int = 30_000) -> dict:
    """Extrait en lecture seule les médias réellement résolus par le navigateur."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    import outbound_http

    parsed, port = outbound_http._parse_public_url(url)
    assert parsed.hostname is not None
    outbound_http._public_addresses(
        await outbound_http._resolve(parsed.hostname, port)
    )
    context = await _new_context()
    async def guard_public_request(route, request):
        try:
            request_parsed, request_port = outbound_http._parse_public_url(request.url)
            assert request_parsed.hostname is not None
            outbound_http._public_addresses(
                await outbound_http._resolve(request_parsed.hostname, request_port)
            )
        except (OSError, ValueError):
            await route.abort()
            return
        await route.continue_()

    await context.route("**/*", guard_public_request)
    page = await context.new_page()
    try:
        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        await page.wait_for_timeout(750)
        images = await page.locator("img").evaluate_all(
            r"""nodes => nodes.slice(0, 2000).flatMap(node => {
              const values = [];
              const add = (url, kind) => { if (url) values.push({
                url, kind, alt: (node.alt || '').slice(0, 500),
                width: node.naturalWidth || 0, height: node.naturalHeight || 0
              }); };
              add(node.currentSrc || node.src, 'image');
              for (const item of (node.srcset || node.dataset.srcset || '').split(',')) {
                add(item.trim().split(/\s+/, 1)[0], 'srcset');
              }
              add(node.dataset.src || node.dataset.lazySrc || node.dataset.original, 'lazy');
              return values;
            })"""
        )
        backgrounds = await page.locator("body *").evaluate_all(
            r"""nodes => nodes.slice(0, 3000).flatMap(node => {
              const value = getComputedStyle(node).backgroundImage || '';
              return [...value.matchAll(/url\\(["']?(.*?)["']?\\)/g)]
                .map(match => ({url: match[1], kind: 'background', alt: ''}));
            })"""
        )
        metadata = await page.locator(
            'meta[property="og:image"],meta[name="twitter:image"],link[rel~="icon"]'
        ).evaluate_all(
            """nodes => nodes.map(node => ({
              url: node.content || node.href || '',
              kind: node.tagName.toLowerCase() === 'link' ? 'icon' : 'social',
              alt: ''
            }))"""
        )
        return {
            "success": True,
            "url": page.url,
            "media": [*images, *backgrounds, *metadata],
        }
    finally:
        await context.close()


def _browser_locator(page, *, control_type: str, name: str, match_index: int):
    role = control_type.strip().lower()
    if role:
        locator = page.get_by_role(role, name=name or None, exact=bool(name))
    elif name:
        locator = page.get_by_text(name, exact=True)
    else:
        raise ValueError("control_type ou name requis pour cibler un élément Web.")
    return locator.nth(max(0, int(match_index)))


async def computer_act(
    action: str,
    *,
    control_type: str = "",
    name: str = "",
    match_index: int = 0,
    text: str = "",
    x: int | None = None,
    y: int | None = None,
    end_x: int | None = None,
    end_y: int | None = None,
) -> dict:
    page = await _get_computer_page()
    if action in {"click", "double_click", "right_click"}:
        if x is not None and y is not None:
            await page.mouse.click(
                x,
                y,
                button="right" if action == "right_click" else "left",
                click_count=2 if action == "double_click" else 1,
            )
        else:
            locator = _browser_locator(
                page,
                control_type=control_type,
                name=name,
                match_index=match_index,
            )
            await locator.click(
                timeout=15_000,
                button="right" if action == "right_click" else "left",
                click_count=2 if action == "double_click" else 1,
            )
    elif action == "move":
        if x is None or y is None:
            raise ValueError("x et y sont requis pour déplacer le pointeur Web.")
        await page.mouse.move(x, y)
    elif action == "drag":
        if None in (x, y, end_x, end_y):
            raise ValueError("x, y, end_x et end_y sont requis pour glisser.")
        await page.mouse.move(x, y)
        await page.mouse.down()
        await page.mouse.move(end_x, end_y, steps=12)
        await page.mouse.up()
    elif action == "type":
        locator = _browser_locator(
            page,
            control_type=control_type,
            name=name,
            match_index=match_index,
        )
        await locator.fill(text, timeout=15_000)
    elif action == "keypress":
        if not text:
            raise ValueError("text doit contenir la touche ou combinaison Playwright.")
        await page.keyboard.press(text)
    elif action == "scroll":
        amount = int(text or 600)
        await page.mouse.wheel(0, max(-5_000, min(amount, 5_000)))
    else:
        raise ValueError(f"Action navigateur non prise en charge : {action}")
    await page.wait_for_timeout(250)
    return await computer_observe()


async def fetch_text(url: str, timeout: int = 25000, max_chars: int = 8000) -> dict:
    """Ouvre une URL dans un vrai navigateur et renvoie son texte lisible."""
    data = await fetch_page(url, timeout=timeout, max_chars=max_chars)
    return {"title": data["title"], "text": data["text"], "url": data["url"]}


async def fetch_page(url: str, timeout: int = 25000, max_chars: int = 100000) -> dict:
    """Rend une page autorisée et restitue son texte ainsi que ses liens absolus."""
    ctx = await _new_context()
    try:
        page = await ctx.new_page()
        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        await page.wait_for_timeout(700)   # laisser le JS se poser
        data = await page.evaluate(
            """() => {
                const links = [...document.querySelectorAll('a[href]')].map(a => a.href);
                document.querySelectorAll('script,style,nav,footer,header,noscript,svg,iframe').forEach(e=>e.remove());
                return {
                    title: document.title || '',
                    text: (document.body && document.body.innerText) || '',
                    links
                };
            }"""
        )
        return {
            "title": data.get("title", ""),
            "text": (data.get("text") or "").strip()[:max_chars],
            "url": page.url,
            "links": list(dict.fromkeys(data.get("links") or []))[:10000],
        }
    finally:
        await ctx.close()


async def close():
    global _browser, _pw, _computer_context, _computer_page
    try:
        if _computer_context:
            await _computer_context.close()
    except Exception:
        pass
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
    _computer_context = None
    _computer_page = None
