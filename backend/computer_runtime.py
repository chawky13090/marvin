"""Computer Runtime piloté par le LLM, protégé aux frontières d'effet.

Le modèle choisit librement ses actions dans une boucle perception/action. Cette
façade fournit des primitives visuelles et des accélérateurs sémantiques ; le
gateway reste l'unique autorité pour les permissions et les engagements.
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


Executor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
_executors: dict[str, Executor] = {}

READ_ACTIONS = frozenset(
    {"observe", "verify", "screenshot", "list_windows", "wait"}
)
MUTATING_ACTIONS = frozenset(
    {
        "open", "focus", "click", "double_click", "right_click", "move",
        "drag", "type", "keypress", "scroll", "navigate", "commit",
    }
)
ACTIONS = READ_ACTIONS | MUTATING_ACTIONS

_STATE_TTL_SECONDS = 300.0
_MAX_STATE_ITEMS = 512


@dataclass(frozen=True, slots=True)
class VisualFrame:
    created_at: float
    origin_x: int
    origin_y: int
    scale_x: float
    scale_y: float
    width: int
    height: int
    window: str
    surface: str


_frames: dict[str, VisualFrame] = {}
_element_refs: dict[str, dict[str, Any]] = {}


def configure(executors: dict[str, Executor]) -> None:
    required = {
        "pc_app_launch",
        "pc_window_list",
        "pc_window_focus",
        "pc_gui_read",
        "pc_gui_click",
        "pc_gui_type",
        "pc_screenshot",
        "web_browser_open",
    }
    missing = required - set(executors)
    if missing:
        raise RuntimeError(
            "Computer Runtime incomplet : " + ", ".join(sorted(missing))
        )
    _executors.clear()
    _executors.update({name: executors[name] for name in required})


def _prune_state() -> None:
    cutoff = time.monotonic() - _STATE_TTL_SECONDS
    for key, value in list(_frames.items()):
        if value.created_at < cutoff:
            _frames.pop(key, None)
    for key, value in list(_element_refs.items()):
        if float(value.get("created_at") or 0) < cutoff:
            _element_refs.pop(key, None)
    while len(_frames) > _MAX_STATE_ITEMS:
        _frames.pop(next(iter(_frames)))
    while len(_element_refs) > _MAX_STATE_ITEMS:
        _element_refs.pop(next(iter(_element_refs)))


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    executor = _executors.get(name)
    if executor is None:
        return {"error": f"Moteur indisponible : {name}"}
    result = await executor(arguments)
    return result if isinstance(result, dict) else {"success": True, "result": result}


def _issue_element_refs(
    elements: list[dict[str, Any]],
    *,
    surface: str,
    window: str,
) -> list[dict[str, Any]]:
    _prune_state()
    issued: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        public = dict(element)
        token = "el_" + secrets.token_urlsafe(12)
        _element_refs[token] = {
            "created_at": time.monotonic(),
            "surface": surface,
            "window": window,
            "control_type": str(
                element.get("control_type")
                or element.get("role")
                or element.get("tag")
                or ""
            ),
            "name": str(element.get("name") or ""),
            "automation_id": str(element.get("automation_id") or ""),
            "match_index": int(element.get("match_index", element.get("index", 0))),
        }
        public["element_ref"] = token
        issued.append(public)
    return issued


def _resolve_element_ref(args: dict[str, Any]) -> dict[str, Any]:
    token = str(args.get("element_ref") or "").strip()
    if not token:
        return dict(args)
    _prune_state()
    reference = _element_refs.get(token)
    if reference is None:
        raise ValueError(
            "element_ref expiré ou inconnu : observe de nouveau l'interface."
        )
    merged = dict(args)
    for key in (
        "surface", "window", "control_type", "name",
        "automation_id", "match_index",
    ):
        if not merged.get(key) and reference.get(key) not in (None, ""):
            merged[key] = reference[key]
    return merged


def _find_window_rect(search: str) -> tuple[int, int, int, int, str] | None:
    if not search:
        return None
    import win32gui

    found: tuple[int, int, int, int, str] | None = None
    needle = search.casefold()

    def callback(hwnd, _extra):
        nonlocal found
        if found is not None or not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title and needle in title.casefold():
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right > left and bottom > top:
                found = (left, top, right, bottom, title)

    win32gui.EnumWindows(callback, None)
    return found


def _capture_visual_sync(window: str) -> dict[str, Any]:
    from PIL import ImageGrab
    import win32api
    import win32con

    rect = _find_window_rect(window)
    if rect:
        left, top, right, bottom, title = rect
        image = ImageGrab.grab(bbox=(left, top, right, bottom))
        origin_x, origin_y = left, top
    else:
        origin_x = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        origin_y = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        title = ""
        image = ImageGrab.grab(all_screens=True)

    source_width, source_height = image.size
    display = image.copy()
    display.thumbnail((1600, 1000))
    display_width, display_height = display.size
    scale_x = display_width / max(source_width, 1)
    scale_y = display_height / max(source_height, 1)
    buffer = io.BytesIO()
    display.save(buffer, format="PNG", optimize=True)
    frame_id = "fr_" + secrets.token_urlsafe(12)
    _frames[frame_id] = VisualFrame(
        created_at=time.monotonic(),
        origin_x=origin_x,
        origin_y=origin_y,
        scale_x=scale_x,
        scale_y=scale_y,
        width=display_width,
        height=display_height,
        window=title,
        surface="desktop",
    )
    _prune_state()
    return {
        "success": True,
        "image": "data:image/png;base64,"
        + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "frame_id": frame_id,
        "width": display_width,
        "height": display_height,
        "coordinate_space": "frame_pixels",
        "window_title": title or None,
    }


def _register_browser_frame(observation: dict[str, Any]) -> dict[str, Any]:
    if not observation.get("image"):
        return observation
    width = max(1, int(observation.get("width") or 1280))
    height = max(1, int(observation.get("height") or 900))
    frame_id = "fr_" + secrets.token_urlsafe(12)
    _frames[frame_id] = VisualFrame(
        created_at=time.monotonic(),
        origin_x=0,
        origin_y=0,
        scale_x=1.0,
        scale_y=1.0,
        width=width,
        height=height,
        window=str(observation.get("title") or ""),
        surface="browser",
    )
    _prune_state()
    observation["frame_id"] = frame_id
    return observation


async def _capture_visual(window: str) -> dict[str, Any]:
    return await asyncio.to_thread(_capture_visual_sync, window)


async def _observe(
    window: str,
    max_elements: int,
    *,
    visual: bool,
) -> dict[str, Any]:
    observation: dict[str, Any] = {"engine": "windows_hybrid"}
    if window:
        ui = await _call(
            "pc_gui_read",
            {"window": window, "max_elements": max_elements},
        )
        if isinstance(ui.get("elements"), list):
            ui["elements"] = _issue_element_refs(
                ui["elements"],
                surface="desktop",
                window=str(ui.get("window_title") or window),
            )
        observation["ui"] = ui
    else:
        observation["windows"] = await _call("pc_window_list", {})
    if visual:
        observation["visual"] = await _capture_visual(window)
    return observation


def _evidence_text(observation: dict[str, Any]) -> str:
    chunks: list[str] = []
    stack: list[Any] = [observation]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(
                child
                for key, child in value.items()
                if key not in {"image"}
            )
        elif isinstance(value, list):
            stack.extend(value[:500])
        elif isinstance(value, (str, int, float, bool)):
            chunks.append(str(value))
    return "\n".join(chunks).casefold()


def _frame_point(
    args: dict[str, Any],
    x_key: str,
    y_key: str,
    *,
    expected_surface: str = "desktop",
) -> tuple[int, int]:
    try:
        x = float(args[x_key])
        y = float(args[y_key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{x_key} et {y_key} sont requis et numériques.") from exc
    frame_id = str(args.get("frame_id") or "").strip()
    if frame_id:
        _prune_state()
        frame = _frames.get(frame_id)
        if frame is None:
            raise ValueError("frame_id expiré : prends une nouvelle capture.")
        if frame.surface != expected_surface:
            raise ValueError("frame_id associé à une autre surface : observe de nouveau.")
        if not (0 <= x < frame.width and 0 <= y < frame.height):
            raise ValueError("Coordonnées hors de la capture référencée.")
        return (
            frame.origin_x + round(x / max(frame.scale_x, 0.0001)),
            frame.origin_y + round(y / max(frame.scale_y, 0.0001)),
        )
    return round(x), round(y)


_KEY_ALIASES = {
    "ENTER": "{ENTER}", "RETURN": "{ENTER}", "TAB": "{TAB}", "ESC": "{ESC}",
    "ESCAPE": "{ESC}", "BACKSPACE": "{BACKSPACE}", "DELETE": "{DELETE}",
    "SPACE": "{SPACE}", "HOME": "{HOME}", "END": "{END}",
    "PAGEUP": "{PGUP}", "PAGEDOWN": "{PGDN}",
    "UP": "{UP}", "DOWN": "{DOWN}", "LEFT": "{LEFT}", "RIGHT": "{RIGHT}",
    "WIN": "{LWIN}", "LWIN": "{LWIN}", "RWIN": "{RWIN}", "SUPER": "{LWIN}",
}
_MODIFIER_NAMES = {"CTRL": "^", "CONTROL": "^", "ALT": "%", "SHIFT": "+"}


def _keypress_sequence(text: str) -> str:
    value = str(text or "").strip()
    if not value or len(value) > 80:
        raise ValueError("Combinaison clavier absente ou trop longue.")
    parts = [part.strip().upper() for part in value.split("+") if part.strip()]
    prefix = "".join(_MODIFIER_NAMES[part] for part in parts[:-1] if part in _MODIFIER_NAMES)
    key = parts[-1] if parts else ""
    if any(part not in _MODIFIER_NAMES for part in parts[:-1]):
        raise ValueError("Combinaison clavier non reconnue.")
    if key in _KEY_ALIASES:
        return prefix + _KEY_ALIASES[key]
    if len(key) == 1 and key.isalnum():
        return prefix + key.lower()
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return prefix + "{" + key + "}"
    raise ValueError("Touche non reconnue.")


# v2.538 — Incident réel reproduit (conversation « Ouvrir IT Connect sur Firefox ») :
# le modèle envoie des combinaisons de touches via action=type (pas keypress) en
# syntaxe SendKeys/AutoHotkey qu'il connaît par cœur — "{Enter}", "{enter}",
# "%{ALT}%{TAB}", "%{WIN}" — TOUTES rejetées par pywinauto avec "Unknown code: X"
# car cette syntaxe n'est interprétée que par action=keypress, en majuscules
# strictes. Plutôt qu'exiger que le modèle mémorise la bonne action et la bonne
# casse, on détecte cette syntaxe dans action=type et on la route vers le même
# normalisateur que keypress — le texte littéral non concerné n'est jamais affecté
# (fullmatch strict : un vrai texte contenant des accolades reste tapé tel quel).
_KEY_COMBO_TOKEN = re.compile(r"\{([A-Za-z][A-Za-z0-9]*)\}|([%^+])")
_KEY_COMBO_FULL = re.compile(r"(?:\{[A-Za-z][A-Za-z0-9]*\}|[%^+])+")


def _parse_key_combo(text: str) -> str | None:
    value = str(text or "").strip()
    if not value or len(value) > 40 or not _KEY_COMBO_FULL.fullmatch(value):
        return None
    modifiers: list[str] = []
    key_candidates: list[str] = []
    for bracket, symbol in _KEY_COMBO_TOKEN.findall(value):
        if symbol:
            modifiers.append(_MODIFIER_NAMES.get(
                {"%": "ALT", "^": "CTRL", "+": "SHIFT"}[symbol], symbol
            ))
            continue
        token = bracket.upper()
        if token in _MODIFIER_NAMES:
            modifiers.append(_MODIFIER_NAMES[token])
        else:
            key_candidates.append(token)
    if not key_candidates:
        return None
    key = key_candidates[-1]
    prefix = "".join(dict.fromkeys(modifiers))
    if key in _KEY_ALIASES:
        return prefix + _KEY_ALIASES[key]
    if len(key) == 1 and key.isalnum():
        return prefix + key.lower()
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return prefix + "{" + key + "}"
    return None


def _desktop_input_sync(action: str, args: dict[str, Any]) -> dict[str, Any]:
    import win32api
    import win32con
    from pywinauto.keyboard import send_keys

    if action in {"click", "double_click", "right_click", "move", "drag", "commit"}:
        x, y = _frame_point(args, "x", "y", expected_surface="desktop")
        win32api.SetCursorPos((x, y))
        if action == "move":
            return {"success": True, "message": f"Pointeur déplacé vers ({x}, {y})."}
        if action == "drag":
            end_x, end_y = _frame_point(
                args, "end_x", "end_y", expected_surface="desktop"
            )
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            steps = 12
            for step in range(1, steps + 1):
                px = round(x + (end_x - x) * step / steps)
                py = round(y + (end_y - y) * step / steps)
                win32api.SetCursorPos((px, py))
                time.sleep(0.02)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            return {"success": True, "message": "Glisser-déposer effectué."}
        right = action == "right_click"
        down = (
            win32con.MOUSEEVENTF_RIGHTDOWN if right
            else win32con.MOUSEEVENTF_LEFTDOWN
        )
        up = (
            win32con.MOUSEEVENTF_RIGHTUP if right
            else win32con.MOUSEEVENTF_LEFTUP
        )
        repetitions = 2 if action == "double_click" else 1
        for _ in range(repetitions):
            win32api.mouse_event(down, 0, 0, 0, 0)
            win32api.mouse_event(up, 0, 0, 0, 0)
            time.sleep(0.08)
        return {"success": True, "message": f"Clic effectué à ({x}, {y})."}
    if action == "keypress":
        send_keys(_keypress_sequence(str(args.get("text") or "")), pause=0.03)
        return {"success": True, "message": "Raccourci clavier envoyé."}
    if action == "type":
        text = str(args.get("text") or "")
        if not text:
            raise ValueError("text est requis.")
        combo = _parse_key_combo(text)
        if combo is not None:
            send_keys(combo, pause=0.03)
            return {"success": True, "message": "Raccourci clavier envoyé."}
        if len(text) > 20_000:
            raise ValueError("text dépasse la limite de 20 000 caractères.")
        send_keys(
            text,
            pause=0.01,
            with_spaces=True,
            with_tabs=True,
            with_newlines=True,
            vk_packet=True,
        )
        return {"success": True, "message": "Texte saisi au clavier."}
    if action == "scroll":
        try:
            amount = max(-10_000, min(int(args.get("amount", args.get("text", -600))), 10_000))
        except (TypeError, ValueError) as exc:
            raise ValueError("amount doit être un entier.") from exc
        win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, amount, 0)
        return {"success": True, "message": f"Défilement {amount} effectué."}
    raise ValueError(f"Action visuelle Windows inconnue : {action}")


async def _desktop_input(action: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_desktop_input_sync, action, args)
    except Exception as exc:
        return {"error": str(exc)}


# v2.537 — Incident réel reproduit (conversation « Liste des éléments du bureau ») :
# un seul appel `computer_control` (action focus) a mis 525s avant d'être annulé —
# non par un timeout propre à l'outil, mais par le budget temporel GLOBAL du tour
# (agent_tool_batch.py), qui peut être bien plus large. Un plafond interne, propre
# à cet outil et indépendant du budget du tour, fait échouer vite avec un
# diagnostic clair plutôt que de silencieusement consommer plusieurs minutes.
_INTERNAL_TIMEOUT_SECONDS = 45


async def execute(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(_execute_body(args), timeout=_INTERNAL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": (
                f"L'action a dépassé le délai interne de {_INTERNAL_TIMEOUT_SECONDS}s "
                "et a été annulée proprement."
            ),
            "timeout": True,
            "needs_repair": True,
        }


async def _execute_body(args: dict[str, Any]) -> dict[str, Any]:
    try:
        resolved_args = _resolve_element_ref(args)
    except ValueError as exc:
        return {"error": str(exc), "needs_repair": True}
    action = str(resolved_args.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return {"error": "Action invalide.", "allowed_actions": sorted(ACTIONS)}
    if action == "commit" and not str(
        resolved_args.get("commitment_summary") or ""
    ).strip():
        return {
            "error": "commitment_summary est obligatoire pour l'engagement final.",
            "needs_repair": True,
        }
    window = str(resolved_args.get("window") or "").strip()
    surface = str(resolved_args.get("surface") or "auto").strip().lower()
    if surface not in {"auto", "desktop", "browser"}:
        return {"error": "surface doit valoir auto, desktop ou browser."}
    expected = str(resolved_args.get("expected") or "").strip()
    visual = bool(resolved_args.get("visual", True))
    try:
        max_elements = max(1, min(int(resolved_args.get("max_elements", 80)), 100))
    except (TypeError, ValueError):
        return {"error": "max_elements doit être un entier entre 1 et 100."}

    started = time.monotonic()
    before = None
    if action in MUTATING_ACTIONS and bool(resolved_args.get("capture_before", True)):
        if surface == "browser" or action == "navigate":
            import web_browser
            before = {
                "engine": "playwright",
                "browser": await web_browser.computer_observe(max_elements),
            }
        else:
            before = await _observe(window, max_elements, visual=visual)

    if action in {"observe", "list_windows"}:
        if action == "observe" and surface == "browser":
            import web_browser
            result = await web_browser.computer_observe(max_elements)
            result = _register_browser_frame(result)
            if isinstance(result.get("elements"), list):
                result["elements"] = _issue_element_refs(
                    result["elements"], surface="browser", window=""
                )
        else:
            result = await _observe(
                window if action == "observe" else "",
                max_elements,
                visual=visual and action == "observe",
            )
    elif action == "screenshot":
        if surface == "browser":
            import web_browser
            result = _register_browser_frame(
                await web_browser.computer_observe(max_elements)
            )
        else:
            result = await _capture_visual(window)
    elif action == "verify":
        if surface == "browser":
            import web_browser
            result = await web_browser.computer_observe(max_elements)
            result = _register_browser_frame(result)
        else:
            result = await _observe(window, max_elements, visual=visual)
    elif action == "wait":
        try:
            delay_ms = max(50, min(int(resolved_args.get("duration_ms", 500)), 10_000))
        except (TypeError, ValueError):
            return {"error": "duration_ms doit être un entier entre 50 et 10000."}
        await asyncio.sleep(delay_ms / 1000)
        if surface == "browser":
            import web_browser
            result = await web_browser.computer_observe(max_elements)
            result = _register_browser_frame(result)
        else:
            result = await _observe(window, max_elements, visual=visual)
    elif action == "open":
        result = await _call(
            "pc_app_launch",
            {
                "app_name": str(resolved_args.get("target") or "").strip(),
                "url": str(resolved_args.get("url") or "").strip(),
            },
        )
    elif action == "navigate":
        target_url = str(resolved_args.get("target") or "").strip()
        # v2.542 — Incident réel reproduit (conversation « Ouvrir France Travail ») :
        # malgré l'avertissement du schéma (v2.541), le modèle a de nouveau enchaîné
        # open (sans url) puis navigate séparément. navigate pilotait TOUJOURS un
        # Chromium headless Playwright, quelle que soit `surface` — Marvin a vu la
        # page se charger dans ce navigateur invisible et a conclu à tort que la
        # demande était accomplie, sans jamais revérifier la fenêtre desktop visible.
        # Correctif : navigate cible désormais le navigateur VISIBLE par défaut sauf
        # si surface="browser" est explicitement demandé (automatisation programmatique
        # d'une page — clic/remplissage d'éléments via element_ref, qui nécessite bien
        # le contexte Playwright partagé entre appels).
        if surface == "browser":
            try:
                import web_browser
                result = await web_browser.computer_navigate(target_url)
            except Exception as exc:
                result = {"error": str(exc)}
        else:
            result = await _call(
                "pc_app_launch", {"app_name": "", "url": target_url}
            )
    elif action == "focus":
        result = await _call(
            "pc_window_focus",
            {
                "search": window or str(resolved_args.get("target") or "").strip(),
                "hwnd": resolved_args.get("hwnd"),
            },
        )
    elif (
        action in {"click", "type", "commit"}
        and surface != "browser"
        and (
            resolved_args.get("element_ref")
            or resolved_args.get("control_type")
            or resolved_args.get("automation_id")
        )
    ):
        call_args = {
            "window": window,
            "control_type": str(resolved_args.get("control_type") or "").strip(),
            "name": str(resolved_args.get("name") or "").strip(),
            "automation_id": str(resolved_args.get("automation_id") or "").strip(),
            "match_index": resolved_args.get("match_index", 0),
            "confirmed": bool(resolved_args.get("confirmed")),
        }
        if action == "type":
            call_args["text"] = str(resolved_args.get("text") or "")
        result = await _call(
            "pc_gui_click" if action == "commit" else f"pc_gui_{action}",
            call_args,
        )
    elif action in {
        "click", "double_click", "right_click", "move", "drag",
        "type", "keypress", "scroll", "commit",
    } and surface != "browser":
        if window:
            focus_result = await _call("pc_window_focus", {"search": window})
            if focus_result.get("error"):
                return {"error": focus_result["error"], "needs_repair": True}
        # v2.538 — Incident réel reproduit (conversation « Ouvrir IT Connect sur
        # Firefox ») : le modèle appelle action=click avec seulement `window`,
        # pensant que cela suffit à cliquer dans la fenêtre déjà mise au premier
        # plan par le focus ci-dessus. Un message clair évite plusieurs allers-
        # retours avant de comprendre qu'un point ou un élément est nécessaire.
        if (
            action in {"click", "double_click", "right_click"}
            and resolved_args.get("x") is None
            and resolved_args.get("y") is None
            and not resolved_args.get("element_ref")
            and not resolved_args.get("control_type")
            and not resolved_args.get("automation_id")
        ):
            return {
                "error": (
                    "La fenêtre a été mise au premier plan, mais cliquer exige "
                    "aussi x/y (coordonnées de frame_id) ou un élément "
                    "(element_ref, ou control_type+name) issu d'une observation "
                    "récente. Utilise action=focus si tu voulais seulement "
                    "amener la fenêtre au premier plan."
                ),
                "needs_repair": True,
            }
        result = await _desktop_input(action, resolved_args)
    elif action in {
        "click", "double_click", "right_click", "move", "drag",
        "type", "keypress", "scroll", "commit",
    } and surface == "browser":
        try:
            import web_browser
            x = y = end_x = end_y = None
            if resolved_args.get("x") is not None or resolved_args.get("y") is not None:
                x, y = _frame_point(
                    resolved_args,
                    "x",
                    "y",
                    expected_surface="browser",
                )
            if action == "drag":
                end_x, end_y = _frame_point(
                    resolved_args,
                    "end_x",
                    "end_y",
                    expected_surface="browser",
                )
            result = await web_browser.computer_act(
                "click" if action == "commit" else action,
                control_type=str(resolved_args.get("control_type") or ""),
                name=str(resolved_args.get("name") or ""),
                match_index=int(resolved_args.get("match_index", 0)),
                text=str(resolved_args.get("text") or ""),
                x=x,
                y=y,
                end_x=end_x,
                end_y=end_y,
            )
        except Exception as exc:
            result = {"error": str(exc)}
    else:
        return {
            "error": f"L'action {action} n'est pas disponible pour {surface}.",
            "capability_status": "degraded",
        }

    after = None
    if action in MUTATING_ACTIONS and not result.get("error"):
        if action == "navigate" or surface == "browser":
            result = _register_browser_frame(result)
            if isinstance(result.get("elements"), list):
                result["elements"] = _issue_element_refs(
                    result["elements"], surface="browser", window=""
                )
            after = {"engine": "playwright", "browser": result}
        else:
            after = await _observe(window, max_elements, visual=visual)
    observation = after or result
    verified = expected.casefold() in _evidence_text(observation) if expected else None

    return {
        "success": not bool(result.get("error")),
        "action": action,
        "engine": (
            "playwright"
            if action == "navigate" or surface == "browser"
            else "windows_hybrid"
        ),
        "result": result,
        "before": before,
        "observation": observation,
        "expected": expected or None,
        "verified": verified,
        "needs_repair": bool(result.get("error")) or verified is False,
        "next_step": (
            "Observe la nouvelle capture et choisis librement une autre action."
            if bool(result.get("error")) or verified is False
            else "Poursuis jusqu'au résultat métier demandé."
        ),
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
