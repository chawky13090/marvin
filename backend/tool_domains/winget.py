"""Gestion Winget non interactive avec confirmations sur les mutations."""
from __future__ import annotations

import asyncio
import os
import re as _re
import subprocess
from typing import Any


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""

def _bounded_limit(value: Any, *, default: int = 20, maximum: int = 50) -> int:
    limit = int(value if value is not None else default)
    if not 1 <= limit <= maximum:
        raise ValueError(f"'limit' doit ?tre compris entre 1 et {maximum}.")
    return limit

def _valid_identifier(value: str) -> bool:
    return bool(_re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,199}", value))

def _winget_exe() -> str | None:
    """Chemin de winget.exe (résout le souci de PATH des apps WindowsApps)."""
    import shutil as _sh
    p = _sh.which("winget")
    if p:
        return p
    # Repli : emplacement réel des alias WindowsApps
    base = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe")
    return base if os.path.exists(base) else None

def _winget_run(args: list, timeout: int = 90) -> dict:
    """Exécute winget avec les drapeaux non-interactifs et renvoie {ok, stdout, stderr, code}."""
    exe = _winget_exe()
    if not exe:
        return {"ok": False, "error": "winget introuvable. Installe « App Installer » depuis le Microsoft Store."}
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        r = subprocess.run(
            [exe] + args + ["--disable-interactivity"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=flags,
        )
        return {"ok": r.returncode == 0, "code": r.returncode,
                "stdout": r.stdout or "", "stderr": (r.stderr or "").strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Délai dépassé ({timeout}s) — opération winget trop longue."}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def _parse_winget_table(text: str, available_col: bool = False) -> list:
    """Parse la sortie tabulaire de winget de façon ROBUSTE, par POSITIONS DE COLONNES
    fixes (et non par espaces — un nom long laisse parfois 1 seul espace avant l'ID).
    Étapes : 1) `split('\\r')[-1]` retire le spinner de progression et réaligne l'en-tête
    sur la colonne 0 ; 2) les débuts de mots de l'en-tête donnent les bornes de colonnes ;
    3) chaque ligne de données est découpée à ces bornes (Nom, ID, Version, [Disponible], …, Source)."""
    rows = []
    lines = [ln.split("\r")[-1] for ln in (text or "").split("\n")]
    # En-tête = 1re ligne où 'ID' apparaît comme token isolé.
    hi = -1
    for i, l in enumerate(lines):
        if _re.search(r"(?<!\S)(?:ID|Id)(?!\S)", l):
            hi = i
            break
    if hi < 0:
        return rows
    header = lines[hi]
    words = list(_re.finditer(r"\S+", header))
    if len(words) < 2:
        return rows
    starts = [m.start() for m in words]
    head_lc = [m.group(0).lower() for m in words]
    bounds = [(starts[k], starts[k + 1] if k + 1 < len(starts) else None) for k in range(len(starts))]
    # Index de la colonne « Disponible/Available » (pour les mises à jour).
    avail_idx = next((k for k, w in enumerate(head_lc) if w.startswith(("dispo", "avail"))), None)

    def _cell(l, b):
        a, e = b
        if a >= len(l):
            return ""
        return (l[a:e] if e is not None else l[a:]).strip()

    for l in lines[hi + 1:]:
        s = l.strip()
        if not s or set(s) <= set("-—– "):               # vide / ligne de tirets
            continue
        low = s.lower()
        if any(k in low for k in ("mises à niveau", "mises a niveau", "package(s)",
                                  "upgrades available", "disponible.", "aucun ", "no installed",
                                  "--include-unknown", "ne peuvent pas", "no applicable")):
            continue                                     # lignes de résumé / notes
        vals = [_cell(l, b) for b in bounds]
        pid = vals[1] if len(vals) > 1 else ""
        if not pid or " " in pid:                        # ligne non alignée / parasite
            continue
        item = {"name": vals[0], "id": pid, "version": vals[2] if len(vals) > 2 else "",
                "source": vals[-1]}
        if available_col:
            if avail_idx is not None and avail_idx < len(vals):
                item["available"] = vals[avail_idx]
            elif len(vals) >= 4:
                item["available"] = vals[-2]
        rows.append(item)
    return rows

async def execute_winget_search(args: dict) -> dict:
    """Recherche des paquets disponibles via winget."""
    query = _text(args.get("query"))
    if not query:
        return {"error": "Paramètre 'query' requis."}
    try:
        limit = _bounded_limit(args.get("limit"))
    except (TypeError, ValueError) as exc:
        return {"error": str(exc)}
    cmd = ["search", query, "--accept-source-agreements", "--count", str(limit)]
    source = _text(args.get("source"))
    if source:
        if not _valid_identifier(source):
            return {"error": "Source Winget invalide."}
        cmd += ["--source", source]
    r = await asyncio.to_thread(_winget_run, cmd, timeout=70)
    if not r.get("ok") and not r.get("stdout"):
        return {"error": r.get("error") or r.get("stderr") or "Échec winget search."}
    results = _parse_winget_table(r.get("stdout", ""))
    return {"success": True, "query": query, "count": len(results), "results": results}

async def execute_winget_list_upgrades(args: dict) -> dict:
    """Liste les paquets installés ayant une mise à jour disponible."""
    r = await asyncio.to_thread(_winget_run, ["upgrade", "--include-unknown", "--accept-source-agreements"], timeout=90)
    if not r.get("ok") and not r.get("stdout"):
        return {"error": r.get("error") or r.get("stderr") or "Échec winget upgrade (liste)."}
    upgrades = _parse_winget_table(r.get("stdout", ""), available_col=True)
    return {"success": True, "count": len(upgrades), "upgrades": upgrades}

async def execute_winget_list_installed(args: dict) -> dict:
    """Liste les logiciels INSTALLÉS (filtrable), pour les voir et les désinstaller."""
    cmd = ["list", "--accept-source-agreements"]
    q = _text(args.get("query"))
    if q:
        cmd += ["--query", q]
    r = await asyncio.to_thread(_winget_run, cmd, timeout=90)
    if not r.get("ok") and not r.get("stdout"):
        return {"error": r.get("error") or r.get("stderr") or "Échec winget list."}
    apps = _parse_winget_table(r.get("stdout", ""))
    # On ne garde que les entrées avec un vrai ID winget (désinstallables proprement).
    apps = [a for a in apps if a.get("id") and a["id"].lower() not in ("id",)]
    return {"success": True, "count": len(apps), "apps": apps}


async def _installed_exact(package_id: str) -> dict | None:
    """Retourne l'entrée installée exacte, sans se fier au seul code de Winget."""
    r = await asyncio.to_thread(
        _winget_run,
        ["list", "--id", package_id, "-e", "--accept-source-agreements"],
        timeout=90,
    )
    if not r.get("ok") and not r.get("stdout"):
        raise RuntimeError(
            r.get("error") or r.get("stderr") or
            "L'inventaire Winget est indisponible."
        )
    apps = _parse_winget_table(r.get("stdout", ""))
    return next(
        (
            app
            for app in apps
            if str(app.get("id") or "").casefold() == package_id.casefold()
        ),
        None,
    )


async def _resolve_installed_id(query: str) -> tuple[str | None, list[dict]]:
    listing = await execute_winget_list_installed({"query": query})
    apps = listing.get("apps", []) if listing.get("success") else []
    exact = [
        app for app in apps
        if str(app.get("id") or "").casefold() == query.casefold()
        or str(app.get("name") or "").casefold() == query.casefold()
    ]
    if len(exact) == 1:
        return str(exact[0]["id"]), apps
    if len(apps) == 1:
        return str(apps[0]["id"]), apps
    return None, apps


async def execute_winget_install(args: dict) -> dict:
    """Installe un paquet en mode SILENCIEUX (nécessite confirmation)."""
    explicit_id = _text(args.get("id"))
    query = _text(args.get("query"))
    if not explicit_id and not query:
        return {"error": "Paramètre 'id' (ou 'query') requis."}
    if explicit_id and not _valid_identifier(explicit_id):
        return {"error": "Identifiant Winget invalide."}

    resolved_id = explicit_id
    # v2.113 — bug réel constaté : le LLM appelle parfois avec 'query' (nom flou, ex.
    # "Victoria") au lieu du 'id' exact renvoyé par un winget_search précédent (ex.
    # "Victoria.Victoria") → winget refuse tout net ("Plusieurs packages correspondent")
    # même si un SEUL paquet porte exactement ce nom. On résout nous-mêmes AVANT de
    # demander confirmation, plutôt que de dépendre du LLM pour rejouer avec le bon id.
    if not resolved_id:
        search = await execute_winget_search({"query": query, "limit": 20})
        candidates = search.get("results", []) if search.get("success") else []
        exact = [c for c in candidates if c.get("name", "").strip().lower() == query.lower()]
        if len(exact) == 1:
            resolved_id = exact[0]["id"]
        elif len(candidates) == 1:
            resolved_id = candidates[0]["id"]
        elif len(candidates) > 1:
            options = ", ".join(f"{c.get('name')} ({c.get('id')})" for c in candidates[:8])
            return {"error": f"Plusieurs paquets correspondent à « {query} » — précise avec le paramètre 'id' : {options}"}
        else:
            return {"error": f"Aucun paquet trouvé pour « {query} »."}

    pkg_label = resolved_id or query
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"Installer le paquet « {pkg_label} » via winget ?"}
    selector = ["--id", resolved_id, "-e"] if resolved_id else [query]
    r = await asyncio.to_thread(_winget_run, ["install"] + selector + ["--silent", "--accept-package-agreements",
                     "--accept-source-agreements"], timeout=900)
    installed = await _installed_exact(resolved_id) if r.get("ok") else None
    success = bool(r.get("ok") and installed)
    return {
        "success": success,
        "package": pkg_label,
        "code": r.get("code"),
        "changed": success,
        "verification": {
            "expected": "installed",
            "observed": "installed" if installed else "not_found",
            "package": installed,
        },
        "message": (
            "Installé et vérifié dans l'inventaire Winget."
            if success
            else "Échec : Winget n'a pas confirmé le paquet dans l'inventaire installé."
        ),
        "output": (
            r.get("stdout", "")[-600:]
            if r.get("stdout")
            else r.get("error") or r.get("stderr")
        ),
    }

async def execute_winget_upgrade(args: dict) -> dict:
    """Met à jour un paquet précis, ou TOUT (`all=true`). Nécessite confirmation."""
    do_all = bool(args.get("all"))
    pkg = _text(args.get("id"))
    if not do_all and not pkg:
        return {"error": "Fournis 'id' (un paquet) ou all=true (tout mettre à jour)."}
    if pkg and not _valid_identifier(pkg):
        return {"error": "Identifiant Winget invalide."}
    target = "TOUS les paquets" if do_all else f"« {pkg} »"
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"Mettre à jour {target} via winget ?"}
    if do_all:
        cmd = ["upgrade", "--all", "--silent", "--accept-package-agreements",
               "--accept-source-agreements", "--include-unknown"]
    else:
        cmd = ["upgrade", "--id", pkg, "-e", "--silent", "--accept-package-agreements",
               "--accept-source-agreements"]
    r = await asyncio.to_thread(_winget_run, cmd, timeout=1800)
    return {"success": r.get("ok", False), "target": target, "code": r.get("code"),
            "message": ("✅ Mise à jour terminée." if r.get("ok") else "❌ Échec (certains paquets ont pu échouer)."),
            "output": (r.get("stdout", "")[-800:] if r.get("stdout") else r.get("error") or r.get("stderr"))}

async def execute_winget_uninstall(args: dict) -> dict:
    """Désinstalle un paquet en mode silencieux (nécessite confirmation)."""
    explicit_id = _text(args.get("id"))
    query = _text(args.get("query"))
    pkg = explicit_id or query
    if not pkg:
        return {"error": "Paramètre 'id' (ou 'query') requis."}
    if explicit_id and not _valid_identifier(explicit_id):
        return {"error": "Identifiant Winget invalide."}
    resolved_id = explicit_id
    if not resolved_id:
        resolved_id, candidates = await _resolve_installed_id(query)
        if not resolved_id:
            if not candidates:
                return {
                    "success": True,
                    "changed": False,
                    "package": query,
                    "verification": {"expected": "absent", "observed": "absent"},
                    "message": "Le logiciel est déjà absent de l'inventaire Winget.",
                }
            options = ", ".join(
                f"{item.get('name')} ({item.get('id')})"
                for item in candidates[:8]
            )
            return {
                "error": (
                    f"Plusieurs logiciels installés correspondent à « {query} ». "
                    f"Précisez l'identifiant exact : {options}"
                )
            }
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": (
                f"Désinstaller l'application « {resolved_id} » ? "
                "Les données du profil utilisateur ne seront pas supprimées."
            ),
        }
    before = await _installed_exact(resolved_id)
    if before is None:
        return {
            "success": True,
            "changed": False,
            "package": resolved_id,
            "verification": {"expected": "absent", "observed": "absent"},
            "message": "Le logiciel est déjà absent de l'inventaire Winget.",
        }
    selector = ["--id", resolved_id, "-e"]
    r = await asyncio.to_thread(_winget_run, ["uninstall"] + selector + ["--silent"], timeout=600)
    remaining = await _installed_exact(resolved_id)
    success = remaining is None
    return {
        "success": success,
        "package": resolved_id,
        "code": r.get("code"),
        "changed": success,
        "verification": {
            "expected": "absent",
            "observed": "absent" if success else "still_installed",
            "before": before,
            "remaining": remaining,
        },
        "message": (
            "Désinstallé et absence vérifiée dans l'inventaire Winget. "
            "Les données du profil utilisateur ont été conservées."
            if success
            else "Échec : le logiciel apparaît encore dans l'inventaire Winget."
        ),
        "output": (
            r.get("stdout", "")[-600:]
            if r.get("stdout")
            else r.get("error") or r.get("stderr")
        ),
    }
