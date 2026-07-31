"""Analyse statique et approbation des commandes, sans ex?cution."""
from __future__ import annotations

import re as _re
from typing import Any

import database as db


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _bounded_limit(value: Any, *, default: int = 100, maximum: int = 500) -> int:
    limit = int(value if value is not None else default)
    if not 1 <= limit <= maximum:
        raise ValueError(f"'limit' doit ?tre compris entre 1 et {maximum}.")
    return limit


def _detect_command_platform(cmd: str) -> str:
    """Détecte la plateforme d'une commande par heuristique."""
    c = cmd.lower().strip()
    if _re.search(r"\b(get-|set-|new-|remove-item|stop-process|restart-service|"
                  r"start-service|remove-localuser|set-executionpolicy|gpupdate|"
                  r"restart-computer|netsh)\b", c):
        return "powershell"
    if _re.search(r"\b(qm|pct|pveceph|pvesm|pvecm|vzdump)\b", c):
        return "proxmox"
    if _re.search(r"(erase\s+startup-config|write\s+(erase|memory)|show\s+ip\s+int|"
                  r"conf\s+t|configure\s+terminal|no\s+shutdown)", c):
        return "cisco"
    if _re.search(r"(advfirewall|clear\s+configure|set\s+firewall|access-list)", c):
        return "firewall"
    if _re.search(r"^\s*(diskpart|format|del\s+/|reg\s+|net\s+user|ipconfig|"
                  r"tasklist|sfc|chkdsk)\b", c):
        return "cmd"
    if _re.search(r"\b(sudo|rm|chmod|chown|systemctl|apt|yum|dnf|dd|mkfs|"
                  r"iptables|kill|mount|umount|fdisk|crontab)\b", c):
        return "linux"
    if _re.search(r"^\s*(bash|sh|\./|export\s+)", c):
        return "bash"
    return "unknown"

def _analyze_command_risk(cmd: str) -> dict:
    """
    Analyse statique du risque d'une commande contre les règles en base.
    Retourne le niveau de risque le plus élevé qui matche.
    """
    cmd_stripped = _text(cmd)
    platform = _detect_command_platform(cmd_stripped)

    risk_order = {"safe": 0, "medium": 1, "high": 2, "critical": 3, "blocked": 4}
    best = {
        "command": cmd_stripped,
        "platform": platform,
        "risk_level": "safe",
        "risk_explanation": "Aucun motif à risque détecté. Commande considérée comme sûre.",
        "safer_alternative": "",
        "requires_approval": False,
        "matched_rule": "",
    }

    try:
        rules = db.cmd_rules_list(active_only=True)
    except Exception:
        rules = []

    for rule in rules:
        try:
            if _re.search(rule["pattern"], cmd_stripped, _re.IGNORECASE):
                if risk_order.get(rule["risk_level"], 0) > risk_order.get(best["risk_level"], 0):
                    best = {
                        "command": cmd_stripped,
                        "platform": rule.get("platform") or platform,
                        "risk_level": rule["risk_level"],
                        "risk_explanation": rule.get("explanation", ""),
                        "safer_alternative": rule.get("safer_alternative", ""),
                        "requires_approval": rule["risk_level"] in ("critical", "blocked"),
                        "matched_rule": rule["pattern"],
                    }
        except Exception:
            continue
    return best

async def execute_cmd_extract_from_text(args: dict) -> dict:
    """Extrait les commandes (PowerShell/CMD/Bash/Linux/Proxmox/Cisco/FW) d'un texte."""
    text = _text(args.get("text"))
    if not text:
        return {"error": "Paramètre 'text' requis."}

    # Lignes ressemblant à des commandes
    command_patterns = [
        r"^[\$#>]\s*(.+)$",
        r"^PS\s+[A-Z]:\\[^>]*>\s*(.+)$",
        r"^[A-Z]:\\[^>]*>\s*(.+)$",
        r"^(sudo\s+\S.*)$",
        r"^(rm\s+\S.*)$", r"^(chmod\s+\S.*)$", r"^(chown\s+\S.*)$",
        r"^(systemctl\s+\S.*)$", r"^(dd\s+\S.*)$", r"^(mkfs\S*\s+.*)$",
        r"^(iptables\s+\S.*)$", r"^(kill\s+\S.*)$",
        r"^(Get-\S+.*)$", r"^(Set-\S+.*)$", r"^(New-\S+.*)$",
        r"^(Remove-\S+.*)$", r"^(Stop-\S+.*)$", r"^(Start-\S+.*)$",
        r"^(Restart-\S+.*)$", r"^(netsh\s+\S.*)$", r"^(reg\s+\S.*)$",
        r"^(net\s+\S.*)$", r"^(diskpart.*)$", r"^(format\s+\S.*)$",
        r"^(del\s+\S.*)$", r"^(qm\s+\S.*)$", r"^(pct\s+\S.*)$",
        r"^(pveceph\s+\S.*)$", r"^(ipconfig.*)$", r"^(ping\s+\S.*)$",
        r"^(nslookup\s+.*)$", r"^(write\s+(erase|memory).*)$",
        r"^(erase\s+startup-config.*)$",
    ]
    commands = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Une commande peut être précédée de prose ("Lance: ...", "Exécutez : ...") :
        # on retente aussi sur les segments après ':' / ';' en plus de la ligne entière.
        candidates = [line] + [seg.strip() for seg in _re.split(r"[:;]", line) if seg.strip()]
        matched = False
        for candidate in candidates:
            for pat in command_patterns:
                m = _re.match(pat, candidate, _re.IGNORECASE)
                if m:
                    cmd = m.group(1).strip() if m.lastindex else candidate
                    if cmd and cmd not in commands:
                        commands.append(cmd)
                    matched = True
                    break
            if matched:
                break
    return {
        "success": True,
        "commands": commands[:50],
        "count": len(commands),
    }

async def execute_cmd_analyze_risk(args: dict) -> dict:
    """
    Analyse le risque d'une ou plusieurs commandes. Journalise chaque analyse.
    Niveaux : safe, medium, high, critical, blocked.
    """
    command = _text(args.get("command"))
    commands = args.get("commands", [])
    if not isinstance(commands, list):
        return {"error": "Paramètre 'commands' invalide : liste attendue."}
    intervention_id = args.get("intervention_id")

    if command and not commands:
        commands = [command]
    if not commands:
        return {"error": "Paramètre 'command' ou 'commands' requis."}

    analyses = []
    risk_counts = {"safe": 0, "medium": 0, "high": 0, "critical": 0, "blocked": 0}
    for cmd in commands[:50]:
        if not cmd or not str(cmd).strip():
            continue
        analysis = _analyze_command_risk(str(cmd))
        risk_counts[analysis["risk_level"]] = risk_counts.get(analysis["risk_level"], 0) + 1
        # Journalise
        try:
            review = db.cmd_review_create({**analysis, "intervention_id": intervention_id})
            analysis["review_id"] = review["id"]
        except Exception:
            analysis["review_id"] = None
        analyses.append(analysis)

    # Verdict global
    highest = "safe"
    risk_order = ["safe", "medium", "high", "critical", "blocked"]
    for a in analyses:
        if risk_order.index(a["risk_level"]) > risk_order.index(highest):
            highest = a["risk_level"]

    blocked_or_critical = [a for a in analyses if a["risk_level"] in ("blocked", "critical")]

    return {
        "success": True,
        "analyses": analyses,
        "count": len(analyses),
        "risk_counts": risk_counts,
        "highest_risk": highest,
        "requires_approval": len(blocked_or_critical) > 0,
        "blocked_commands": [a["command"] for a in analyses if a["risk_level"] == "blocked"],
        "verdict": (
            "🚫 BLOQUÉ — commande(s) destructive(s) détectée(s)" if highest == "blocked"
            else "🔴 CRITIQUE — approbation requise" if highest == "critical"
            else "🟠 RISQUE ÉLEVÉ — vérification recommandée" if highest == "high"
            else "🟡 RISQUE MODÉRÉ" if highest == "medium"
            else "🟢 SÛR"
        ),
    }

async def execute_cmd_suggest_safer_alternative(args: dict) -> dict:
    """Propose une alternative plus sûre pour une commande risquée."""
    command = _text(args.get("command"))
    if not command:
        return {"error": "Paramètre 'command' requis."}
    analysis = _analyze_command_risk(command)
    if analysis["safer_alternative"]:
        return {
            "success": True,
            "command": command,
            "risk_level": analysis["risk_level"],
            "explanation": analysis["risk_explanation"],
            "safer_alternative": analysis["safer_alternative"],
        }
    return {
        "success": True,
        "command": command,
        "risk_level": analysis["risk_level"],
        "safer_alternative": "",
        "message": "Aucune alternative spécifique — commande déjà sûre ou pas de règle dédiée. Bonnes pratiques générales : faire une sauvegarde, tester en pré-prod, vérifier les cibles.",
    }

async def execute_cmd_require_approval(args: dict) -> dict:
    """Crée une demande d'approbation pour une commande destructive."""
    command = _text(args.get("command"))
    if not command:
        return {"error": "Paramètre 'command' requis."}
    try:
        review = None
        if args.get("command_review_id"):
            review_id = args["command_review_id"]
        else:
            analysis = _analyze_command_risk(command)
            review = db.cmd_review_create({**analysis, "intervention_id": args.get("intervention_id")})
            review_id = review["id"]
        req = db.approval_create({
            "command_review_id": review_id,
            "command": command,
            "requested_by": args.get("requested_by", ""),
            "reason": args.get("reason", ""),
        })
        return {
            "success": True,
            "approval_request": req,
            "message": "Demande d'approbation créée. La commande NE sera PAS exécutée tant qu'elle n'est pas approuvée.",
        }
    except Exception as e:
        return {"error": str(e)}

async def execute_cmd_review_history(args: dict) -> dict:
    """Historique des analyses de commandes (journal)."""
    try:
        reviews = db.cmd_review_list(
            args.get("intervention_id"), args.get("risk_level"),
            _bounded_limit(args.get("limit"))
        )
        return {"success": True, "count": len(reviews), "reviews": reviews}
    except Exception as e:
        return {"error": str(e)}
