"""Domaine documentation d'intervention : analyse, actifs et livrables op?rationnels."""
from __future__ import annotations
import datetime as _dt
import re as _re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
import database as db
from platform_paths import PATHS as _SYSTEM_PATHS

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
RiskAnalyzer = Callable[[str], dict[str, Any]]
async def _missing_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "D?pendance documentaire non configur?e."}
def _missing_risk(command: str) -> dict[str, Any]:
    return {"risk_level": "unknown", "command": command}
_file_create_docx: Tool = _missing_tool
_file_create_pdf: Tool = _missing_tool
_cmd_extract: Tool = _missing_tool
_analyze_risk: RiskAnalyzer = _missing_risk


def _text(value: Any) -> str:
    """Normalise une entrée utilisateur sans lever sur une valeur non textuelle."""
    return value.strip() if isinstance(value, str) else ""


def _format(value: Any, allowed: tuple[str, ...]) -> tuple[str | None, dict[str, str] | None]:
    fmt = _text(value).lower() or "pdf"
    if fmt not in allowed:
        return None, {"error": f"Format invalide. Formats acceptés : {', '.join(allowed)}."}
    return fmt, None


def _bounded_limit(value: Any, *, default: int = 50, maximum: int = 500) -> int:
    limit = int(value if value is not None else default)
    if not 1 <= limit <= maximum:
        raise ValueError(f"'limit' doit être compris entre 1 et {maximum}.")
    return limit


def configure(*, file_create_docx: Tool, file_create_pdf: Tool,
              cmd_extract: Tool, analyze_risk: RiskAnalyzer) -> None:
    global _file_create_docx, _file_create_pdf, _cmd_extract, _analyze_risk
    _file_create_docx = file_create_docx
    _file_create_pdf = file_create_pdf
    _cmd_extract = cmd_extract
    _analyze_risk = analyze_risk


async def execute_doc_intervention_create(args: dict) -> dict:
    """Crée une nouvelle intervention IT (incident, déploiement, maintenance…)."""
    if not args.get("title"):
        return {"error": "Paramètre 'title' requis."}
    try:
        interv = db.doc_intervention_create(args)
        return {
            "success": True,
            "message": f"Intervention {interv['number']} créée.",
            "intervention": interv,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_intervention_list(args: dict) -> dict:
    """Liste les interventions (filtrable par client_id, status)."""
    try:
        items = db.doc_intervention_list(
            args.get("client_id"), args.get("status"), _bounded_limit(args.get("limit"))
        )
        return {
            "success": True,
            "count": len(items),
            "interventions": items,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_intervention_update(args: dict) -> dict:
    """Met à jour une intervention existante (status, notes, résolution, etc.)."""
    iid = args.get("id")
    if not iid:
        return {"error": "Paramètre 'id' requis."}
    try:
        interv = db.doc_intervention_update(iid, args)
        if not interv:
            return {"error": "Intervention introuvable"}
        return {"success": True, "intervention": interv}
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_analyze_input(args: dict) -> dict:
    """
    Analyse intelligente du contenu brut d'une intervention.
    Extrait : commandes exécutées, services impactés, type d'incident, mots-clés ITIL.
    """
    raw_text = _text(args.get("raw_text"))
    if not raw_text:
        return {"error": "Paramètre 'raw_text' requis."}

    import re as _re

    text = raw_text
    text_lower = text.lower()

    # Extract commands (lines starting with $, #, >, PS>, C:\>, or known commands)
    command_patterns = [
        r"^[\$#>]\s*(.+)$",
        r"^PS\s+[A-Z]:\\[^>]*>\s*(.+)$",
        r"^[A-Z]:\\[^>]*>\s*(.+)$",
        r"^(sudo\s+\S.*)$",
        r"^(systemctl\s+\S.*)$",
        r"^(Get-\S+.*)$",
        r"^(Set-\S+.*)$",
        r"^(net\s+\S.*)$",
        r"^(ping\s+\S.*)$",
        r"^(ipconfig.*)$",
        r"^(nslookup\s+.*)$",
    ]
    commands = []
    for line in text.splitlines():
        line = line.strip()
        for pat in command_patterns:
            m = _re.match(pat, line, _re.MULTILINE)
            if m:
                commands.append(m.group(1).strip())
                break

    # Extract IP addresses
    ips = list(set(_re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)))

    # Extract MAC addresses
    macs = list(set(_re.findall(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", text)))

    # Extract file paths
    paths = list(set(_re.findall(r"[A-Z]:\\[A-Za-z0-9_\\.-]+", text)))[:20]

    # Detect intervention type via keywords
    type_keywords = {
        "incident":    ["panne","ne fonctionne","planté","crashed","erreur","problème","bug","tombé"],
        "deployment":  ["installer","installation","déployer","déploiement","setup","mise en place"],
        "maintenance": ["maintenance","mise à jour","update","patch","upgrade","sauvegarde","backup"],
        "change":      ["modifier","changer","reconfiguration","migration","évolution"],
        "audit":       ["audit","contrôle","vérification","analyse","inventaire"],
        "request":     ["demande","ajout","création de compte","accès","habilitation"],
    }
    detected_types = []
    for itype, kws in type_keywords.items():
        if any(k in text_lower for k in kws):
            detected_types.append(itype)

    # Detect ITIL category
    itil_keywords = {
        "Hardware":      ["disque","cpu","ram","mémoire","carte mère","alimentation","matériel","écran","clavier","souris"],
        "Software":      ["logiciel","application","windows","office","navigateur","bug"],
        "Network":       ["réseau","wifi","internet","switch","routeur","vlan","dns","dhcp","ping"],
        "Security":      ["sécurité","virus","malware","ransomware","pare-feu","firewall","antivirus","piratage"],
        "Database":      ["base de données","sql","mysql","postgresql","sqlite"],
        "Email":         ["mail","email","outlook","exchange","smtp","imap","pop3"],
        "Backup":        ["sauvegarde","backup","restoration","restauration","veeam"],
        "Server":        ["serveur","ad","active directory","dc","gpo","windows server","linux"],
        "User Access":   ["mot de passe","login","compte utilisateur","authentification","sso","mfa"],
    }
    detected_categories = []
    for cat, kws in itil_keywords.items():
        if any(k in text_lower for k in kws):
            detected_categories.append(cat)

    # Detect priority hints
    priority_hints = {
        "critical": ["urgent","critique","production","arrêt","outage","aucun service"],
        "high":     ["important","prioritaire","plusieurs personnes","beaucoup d'utilisateurs"],
        "low":      ["mineur","peu important","demain","quand vous pouvez"],
    }
    suggested_priority = "medium"
    for prio, kws in priority_hints.items():
        if any(k in text_lower for k in kws):
            suggested_priority = prio
            break

    # GDPR/RGPD relevant?
    rgpd_keywords = ["données personnelles","rgpd","gdpr","fuite","exfiltration","nominatif","carte d'identité"]
    rgpd_relevant = any(k in text_lower for k in rgpd_keywords)

    # Suggested tags
    suggested_tags = list(set(detected_categories + detected_types))[:10]

    # ── v2.30 : Command Safety integration (non-destructive add) ──────────────
    # Analyse le risque des commandes via une extraction LARGE (rm, format, iptables…)
    # sans modifier le champ 'extracted_commands' existant (rétro-compatibilité).
    command_safety = None
    try:
        safety_extract = await _cmd_extract({"text": raw_text})
        broad_commands = safety_extract.get("commands", []) if safety_extract.get("success") else commands
        if broad_commands:
            risk_counts = {"safe": 0, "medium": 0, "high": 0, "critical": 0, "blocked": 0}
            analyzed = []
            risk_order = ["safe", "medium", "high", "critical", "blocked"]
            highest = "safe"
            for cmd in broad_commands[:30]:
                a = _analyze_risk(cmd)
                risk_counts[a["risk_level"]] = risk_counts.get(a["risk_level"], 0) + 1
                if risk_order.index(a["risk_level"]) > risk_order.index(highest):
                    highest = a["risk_level"]
                if a["risk_level"] != "safe":
                    analyzed.append({
                        "command": a["command"],
                        "risk_level": a["risk_level"],
                        "explanation": a["risk_explanation"],
                        "safer_alternative": a["safer_alternative"],
                    })
            command_safety = {
                "highest_risk": highest,
                "risk_counts": risk_counts,
                "risky_commands": analyzed,
                "requires_approval": highest in ("critical", "blocked"),
                "has_blocked": risk_counts.get("blocked", 0) > 0,
            }
    except Exception:
        command_safety = None  # Never break doc_analyze_input

    return {
        "success": True,
        "extracted_commands": commands[:30],
        "command_count": len(commands),
        "ip_addresses": ips[:15],
        "mac_addresses": macs[:10],
        "file_paths": paths,
        "detected_intervention_types": detected_types,
        "main_type": detected_types[0] if detected_types else "incident",
        "itil_categories": detected_categories,
        "suggested_priority": suggested_priority,
        "rgpd_relevant": rgpd_relevant,
        "suggested_tags": suggested_tags,
        "word_count": len(text.split()),
        "command_safety": command_safety,
        "hint": "Utilisez ces données pour pré-remplir une intervention via doc_intervention_create.",
    }


def _render_template(template: str, vars: dict) -> str:
    """Simple {{key}} template substitution."""
    out = template
    for k, v in vars.items():
        out = out.replace("{{" + k + "}}", str(v) if v is not None else "")
    # Remove any remaining {{xxx}} placeholders for cleanliness
    import re as _re
    out = _re.sub(r"\{\{[^}]+\}\}", "_(non renseigné)_", out)
    return out


async def execute_doc_generate_report(args: dict) -> dict:
    """
    Génère un rapport d'intervention professionnel en PDF (ou DOCX).
    Format adapté pour un compte rendu client.
    """
    intervention_id = args.get("intervention_id")
    output_format, format_error = _format(args.get("format"), ("pdf", "docx", "md"))
    if format_error:
        return format_error
    template_id = args.get("template_id")  # optional

    if not intervention_id:
        return {"error": "Paramètre 'intervention_id' requis."}

    try:
        interv = db.doc_intervention_get(intervention_id)
        if not interv:
            return {"error": "Intervention introuvable"}

        # Fetch client info if any
        client_block = ""
        if interv.get("client_id"):
            try:
                client = db.billing_client_get(interv["client_id"])
                if client:
                    client_block = (
                        f"**{client.get('name', '')}**\n"
                        f"{client.get('address', '')}\n"
                        f"Contact : {client.get('contact_name', '')} "
                        f"({client.get('contact_email', '')})"
                    )
            except Exception:
                pass

        # Pick template
        if template_id:
            tmpl = db.doc_template_get(template_id)
        else:
            tmpls = db.doc_template_list("report")
            tmpl = tmpls[0] if tmpls else None

        from datetime import datetime as _dt
        date_str = _dt.now().strftime("%d/%m/%Y %H:%M")
        duration = f"{interv['duration_minutes']} min" if interv.get("duration_minutes") else "_(non renseigné)_"

        vars = {
            "number":          interv.get("number", ""),
            "title":           interv.get("title", ""),
            "date":            date_str,
            "technician":      interv.get("technician") or "_(non renseigné)_",
            "duration":        duration,
            "client_block":    client_block or "_(client non renseigné)_",
            "context":         interv.get("raw_notes") or "_(à compléter)_",
            "diagnostic":      interv.get("root_cause") or "_(à compléter)_",
            "actions":         interv.get("summary") or interv.get("raw_notes") or "_(à compléter)_",
            "commands":        interv.get("commands_executed") or "(aucune)",
            "resolution":      interv.get("resolution") or "_(à compléter)_",
            "recommendations": interv.get("recommendations") or "_(aucune recommandation)_",
        }

        if tmpl:
            content_md = _render_template(tmpl["content_md"], vars)
            db.doc_template_use(tmpl["id"])
            template_name = tmpl["name"]
        else:
            # Fallback minimal content
            content_md = f"# Rapport d'intervention {interv['number']}\n\n{interv.get('summary','(vide)')}"
            template_name = "default"

        # Generate the file
        output_path = args.get("output_path") or str(
            Path(_SYSTEM_PATHS["desktop"]) /
            f"rapport_{interv['number']}.{output_format}"
        )

        if output_format == "docx":
            result = await _file_create_docx({
                "path": output_path,
                "title": f"Rapport d'intervention {interv['number']}",
                "content": content_md,
            })
        elif output_format == "md":
            try:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text(content_md, encoding="utf-8")
                size = Path(output_path).stat().st_size
                result = {"success": True, "path": output_path, "size": size}
            except Exception as e:
                result = {"error": str(e)}
        else:
            result = await _file_create_pdf({
                "path": output_path,
                "title": f"Rapport d'intervention {interv['number']}",
                "content": content_md,
            })

        if result.get("error"):
            return result

        # Save in doc_documents table
        try:
            doc = db.doc_document_create({
                "intervention_id": intervention_id,
                "client_id": interv.get("client_id"),
                "doc_type": "report",
                "format": output_format,
                "title": f"Rapport {interv['number']}",
                "file_path": output_path,
                "content_md": content_md,
                "template_used": template_name,
                "size_bytes": result.get("size") or 0,
            })
        except Exception:
            doc = None

        return {
            "success": True,
            "message": f"Rapport généré : {output_path}",
            "path": output_path,
            "document": doc,
            "format": output_format,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_generate_procedure(args: dict) -> dict:
    """Génère une procédure technique pas-à-pas en PDF/DOCX/MD."""
    intervention_id = args.get("intervention_id")
    output_format, format_error = _format(args.get("format"), ("pdf", "docx", "md"))
    if format_error:
        return format_error
    if not intervention_id:
        return {"error": "Paramètre 'intervention_id' requis."}

    try:
        interv = db.doc_intervention_get(intervention_id)
        if not interv:
            return {"error": "Intervention introuvable"}

        tmpls = db.doc_template_list("procedure")
        tmpl = tmpls[0] if tmpls else None

        from datetime import datetime as _dt
        vars = {
            "title":         interv.get("title", "Procédure"),
            "date":          _dt.now().strftime("%d/%m/%Y"),
            "technician":    interv.get("technician") or "Marvin",
            "difficulty":    args.get("difficulty", "Moyenne"),
            "objective":     args.get("objective") or interv.get("summary") or "_(à compléter)_",
            "prerequisites": args.get("prerequisites") or "_(aucun)_",
            "tools_required": args.get("tools_required") or "_(à préciser)_",
            "steps":         args.get("steps") or interv.get("raw_notes") or "_(à compléter)_",
            "commands":      interv.get("commands_executed") or "(aucune)",
            "validation":    args.get("validation") or "_(à compléter)_",
            "rollback":      args.get("rollback") or "_(à compléter)_",
            "notes":         args.get("notes") or "",
        }

        if tmpl:
            content_md = _render_template(tmpl["content_md"], vars)
            db.doc_template_use(tmpl["id"])
        else:
            content_md = f"# Procédure : {vars['title']}\n\n{vars['steps']}"

        output_path = args.get("output_path") or str(
            Path(_SYSTEM_PATHS["desktop"]) /
            f"procedure_{interv['number']}.{output_format}"
        )

        if output_format == "docx":
            result = await _file_create_docx({
                "path": output_path, "title": vars["title"], "content": content_md,
            })
        elif output_format == "md":
            try:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text(content_md, encoding="utf-8")
                result = {"success": True, "path": output_path, "size": Path(output_path).stat().st_size}
            except Exception as e:
                result = {"error": str(e)}
        else:
            result = await _file_create_pdf({
                "path": output_path, "title": vars["title"], "content": content_md,
            })

        if result.get("error"):
            return result

        doc = db.doc_document_create({
            "intervention_id": intervention_id, "client_id": interv.get("client_id"),
            "doc_type": "procedure", "format": output_format,
            "title": f"Procédure : {vars['title']}",
            "file_path": output_path, "content_md": content_md,
            "template_used": tmpl["name"] if tmpl else "default",
            "size_bytes": result.get("size") or 0,
        })
        return {"success": True, "message": f"Procédure générée : {output_path}",
                "path": output_path, "document": doc}
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_generate_client_sheet(args: dict) -> dict:
    """Génère une fiche client complète (infrastructure, contrats, historique)."""
    client_id = args.get("client_id")
    output_format, format_error = _format(args.get("format"), ("pdf", "docx", "md"))
    if format_error:
        return format_error
    if not client_id:
        return {"error": "Paramètre 'client_id' requis."}

    try:
        client = db.billing_client_get(client_id)
        if not client:
            return {"error": "Client introuvable"}

        # Fetch assets
        assets = db.doc_asset_list(client_id)
        workstations = [a for a in assets if a["asset_type"] == "workstation"]
        servers      = [a for a in assets if a["asset_type"] == "server"]
        network      = [a for a in assets if a["asset_type"] in ("firewall","switch","router")]

        # Fetch recent interventions
        interventions = db.doc_intervention_list(client_id, limit=20)

        def fmt_assets(items, title="aucun"):
            if not items:
                return f"_({title})_"
            lines = []
            for a in items:
                line = f"- **{a['name']}**"
                if a.get("os"): line += f" ({a['os']})"
                if a.get("ip_address"): line += f" — {a['ip_address']}"
                if a.get("location"): line += f" — {a['location']}"
                lines.append(line)
            return "\n".join(lines)

        def fmt_history(items):
            if not items:
                return "_(aucune intervention)_"
            lines = []
            for i in items[:10]:
                lines.append(f"- {i.get('created_at','')[:10]} — **{i['number']}** {i['title']} _({i['status']})_")
            return "\n".join(lines)

        from datetime import datetime as _dt
        tmpls = db.doc_template_list("client_sheet")
        tmpl = tmpls[0] if tmpls else None

        client_type_label = {"mairie":"Mairie","pme":"PME","asso":"Association","particulier":"Particulier"}.get(
            client.get("client_type","pme"), client.get("client_type",""))

        vars = {
            "client_name":   client.get("name",""),
            "client_type":   client_type_label,
            "contact":       client.get("contact_name") or "_(non renseigné)_",
            "phone":         client.get("contact_phone") or "—",
            "email":         client.get("contact_email") or "—",
            "presentation":  client.get("notes") or "_(à compléter)_",
            "workstations":  fmt_assets(workstations, "aucun poste enregistré"),
            "servers":       fmt_assets(servers, "aucun serveur enregistré"),
            "network":       fmt_assets(network, "aucun équipement réseau enregistré"),
            "security":      args.get("security") or "_(à compléter)_",
            "backup":        args.get("backup") or "_(à compléter)_",
            "contracts":     args.get("contracts") or "_(aucun contrat enregistré)_",
            "history":       fmt_history(interventions),
            "contacts":      args.get("contacts") or "_(à compléter)_",
            "date":          _dt.now().strftime("%d/%m/%Y"),
        }
        if tmpl:
            content_md = _render_template(tmpl["content_md"], vars)
            db.doc_template_use(tmpl["id"])
        else:
            content_md = f"# Fiche client : {vars['client_name']}\n\n_(template manquant)_"

        output_path = args.get("output_path") or str(
            Path(_SYSTEM_PATHS["desktop"]) /
            f"fiche_client_{client['name'].replace(' ','_')}.{output_format}"
        )

        if output_format == "docx":
            result = await _file_create_docx({
                "path": output_path, "title": f"Fiche client — {client['name']}", "content": content_md,
            })
        elif output_format == "md":
            try:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text(content_md, encoding="utf-8")
                result = {"success": True, "path": output_path, "size": Path(output_path).stat().st_size}
            except Exception as e:
                result = {"error": str(e)}
        else:
            result = await _file_create_pdf({
                "path": output_path, "title": f"Fiche client — {client['name']}", "content": content_md,
            })

        if result.get("error"):
            return result

        doc = db.doc_document_create({
            "client_id": client_id, "doc_type": "client_sheet", "format": output_format,
            "title": f"Fiche client {client['name']}",
            "file_path": output_path, "content_md": content_md,
            "size_bytes": result.get("size") or 0,
        })
        return {"success": True, "message": f"Fiche client générée : {output_path}",
                "path": output_path, "document": doc,
                "assets_count": len(assets), "interventions_count": len(interventions)}
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_generate_recovery_plan(args: dict) -> dict:
    """Génère un Plan de Reprise d'Activité (PRA/PCA) en PDF."""
    client_id = args.get("client_id")
    output_format, format_error = _format(args.get("format"), ("pdf", "docx"))
    if format_error:
        return format_error
    if not client_id:
        return {"error": "Paramètre 'client_id' requis."}

    try:
        client = db.billing_client_get(client_id)
        if not client:
            return {"error": "Client introuvable"}

        tmpls = db.doc_template_list("recovery_plan")
        tmpl = tmpls[0] if tmpls else None

        # Risks table (markdown)
        risks = args.get("risks") or [
            {"name":"Panne matérielle serveur","probability":"Moyenne","impact":"Élevé","priority":"Haute"},
            {"name":"Coupure électrique prolongée","probability":"Faible","impact":"Critique","priority":"Haute"},
            {"name":"Ransomware","probability":"Moyenne","impact":"Critique","priority":"Critique"},
            {"name":"Erreur humaine (suppression)","probability":"Élevée","impact":"Moyen","priority":"Moyenne"},
            {"name":"Sinistre incendie/dégât des eaux","probability":"Faible","impact":"Critique","priority":"Haute"},
        ]
        risks_table = "\n".join([f"| {r['name']} | {r['probability']} | {r['impact']} | {r['priority']} |" for r in risks])

        services = args.get("services") or [
            {"name":"Messagerie","rto":"4 heures","rpo":"1 heure"},
            {"name":"Fichiers partagés","rto":"8 heures","rpo":"24 heures"},
            {"name":"ERP/Métier","rto":"4 heures","rpo":"24 heures"},
            {"name":"Site web","rto":"24 heures","rpo":"24 heures"},
        ]
        services_table = "\n".join([f"| {s['name']} | {s['rto']} | {s['rpo']} |" for s in services])

        from datetime import datetime as _dt
        vars = {
            "client_name":   client.get("name",""),
            "date":          _dt.now().strftime("%d/%m/%Y"),
            "validator":     args.get("validator") or "_(à définir)_",
            "scope":         args.get("scope") or f"Périmètre IT complet de {client.get('name','')}",
            "risks_table":   risks_table,
            "services_table": services_table,
            "backup_arch":   args.get("backup_arch") or "_(à décrire : type sauvegarde, fréquence, rétention, localisation)_",
            "recovery_steps": args.get("recovery_steps") or (
                "1. **Évaluation** : identifier la nature du sinistre (panne, attaque, sinistre physique)\n"
                "2. **Notification** : alerter l'équipe IT et la direction\n"
                "3. **Isolation** : isoler les systèmes affectés\n"
                "4. **Activation du site de repli** ou restauration sauvegarde\n"
                "5. **Vérification** : tests fonctionnels avant remise en production\n"
                "6. **Communication utilisateurs**\n"
                "7. **Post-mortem** et amélioration du PRA"
            ),
            "tests":         args.get("tests") or "Test annuel minimum (restauration complète d'un serveur).",
            "contacts":      args.get("contacts") or "_(à compléter avec numéros 24/7)_",
            "annexes":       args.get("annexes") or "Voir fiches techniques par serveur et procédures associées.",
        }
        content_md = _render_template(tmpl["content_md"] if tmpl else "# PRA\n\n{{scope}}", vars)
        if tmpl: db.doc_template_use(tmpl["id"])

        output_path = args.get("output_path") or str(
            Path(_SYSTEM_PATHS["desktop"]) /
            f"PRA_{client['name'].replace(' ','_')}.{output_format}"
        )

        if output_format == "docx":
            result = await _file_create_docx({
                "path": output_path, "title": f"PRA — {client['name']}", "content": content_md,
            })
        else:
            result = await _file_create_pdf({
                "path": output_path, "title": f"PRA — {client['name']}", "content": content_md,
            })
        if result.get("error"):
            return result

        doc = db.doc_document_create({
            "client_id": client_id, "doc_type": "recovery_plan", "format": output_format,
            "title": f"PRA {client['name']}",
            "file_path": output_path, "content_md": content_md,
            "size_bytes": result.get("size") or 0,
        })
        return {"success": True, "path": output_path, "document": doc,
                "message": f"PRA généré : {output_path}"}
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_generate_maintenance(args: dict) -> dict:
    """Génère une procédure de maintenance préventive (mensuelle/trimestrielle/annuelle)."""
    client_id = args.get("client_id")
    output_format, format_error = _format(args.get("format"), ("pdf", "docx"))
    if format_error:
        return format_error
    if not client_id:
        return {"error": "Paramètre 'client_id' requis."}
    try:
        client = db.billing_client_get(client_id)
        if not client:
            return {"error": "Client introuvable"}

        tmpls = db.doc_template_list("maintenance")
        tmpl = tmpls[0] if tmpls else None

        from datetime import datetime as _dt
        vars = {
            "frequency":         args.get("frequency", "Mensuelle"),
            "client_name":       client.get("name",""),
            "duration":          args.get("duration", "2 heures"),
            "workstation_extra": args.get("workstation_extra", ""),
            "server_extra":      args.get("server_extra", ""),
            "network_extra":     args.get("network_extra", ""),
            "security_extra":    args.get("security_extra", ""),
            "anomalies":         args.get("anomalies", "_(aucune anomalie détectée à ce jour)_"),
            "corrective_actions": args.get("corrective_actions", "_(aucune action urgente)_"),
        }
        content_md = _render_template(tmpl["content_md"] if tmpl else "# Maintenance\n", vars)
        if tmpl: db.doc_template_use(tmpl["id"])

        output_path = args.get("output_path") or str(
            Path(_SYSTEM_PATHS["desktop"]) /
            f"maintenance_{client['name'].replace(' ','_')}.{output_format}"
        )
        if output_format == "docx":
            result = await _file_create_docx({
                "path": output_path, "title": f"Maintenance — {client['name']}", "content": content_md,
            })
        else:
            result = await _file_create_pdf({
                "path": output_path, "title": f"Maintenance — {client['name']}", "content": content_md,
            })
        if result.get("error"):
            return result

        doc = db.doc_document_create({
            "client_id": client_id, "doc_type": "maintenance", "format": output_format,
            "title": f"Procédure maintenance {client['name']}",
            "file_path": output_path, "content_md": content_md,
            "size_bytes": result.get("size") or 0,
        })
        return {"success": True, "path": output_path, "document": doc,
                "message": f"Procédure maintenance générée : {output_path}"}
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_generate_runbook(args: dict) -> dict:
    """Génère un runbook (procédure d'urgence) pour un incident critique."""
    intervention_id = args.get("intervention_id")
    if not intervention_id:
        return {"error": "Paramètre 'intervention_id' requis."}
    output_format, format_error = _format(args.get("format"), ("pdf", "docx"))
    if format_error:
        return format_error
    try:
        interv = db.doc_intervention_get(intervention_id)
        if not interv:
            return {"error": "Intervention introuvable"}

        tmpls = db.doc_template_list("runbook")
        tmpl = tmpls[0] if tmpls else None

        vars = {
            "title":              interv.get("title",""),
            "severity":           {"critical":"🔴 CRITIQUE","high":"🟠 ÉLEVÉE","medium":"🟡 MOYENNE","low":"🟢 BASSE"}.get(interv.get("priority","medium"),"MOYENNE"),
            "service":            args.get("service", "_(à préciser)_"),
            "technician":         interv.get("technician") or "Astreinte",
            "symptoms":           args.get("symptoms") or interv.get("raw_notes") or "_(à décrire)_",
            "business_impact":    args.get("business_impact") or "_(à évaluer)_",
            "diagnostic_steps":   args.get("diagnostic_steps") or "_(à compléter)_",
            "step1":              args.get("step1") or "_(à compléter)_",
            "step2":              args.get("step2") or "_(à compléter)_",
            "step3":              args.get("step3") or "_(à compléter)_",
            "step4":              args.get("step4") or "_(à compléter)_",
            "level1_contact":     args.get("level1_contact", "_(N1)_"),
            "level2_contact":     args.get("level2_contact", "_(N2)_"),
            "level3_contact":     args.get("level3_contact", "_(N3 / Direction)_"),
        }
        content_md = _render_template(tmpl["content_md"] if tmpl else "# Runbook", vars)
        if tmpl: db.doc_template_use(tmpl["id"])

        output_path = args.get("output_path") or str(
            Path(_SYSTEM_PATHS["desktop"]) /
            f"runbook_{interv['number']}.{output_format}"
        )
        if output_format == "docx":
            result = await _file_create_docx({
                "path": output_path, "title": f"Runbook {interv['number']}", "content": content_md,
            })
        else:
            result = await _file_create_pdf({
                "path": output_path, "title": f"Runbook {interv['number']}", "content": content_md,
            })
        if result.get("error"):
            return result
        doc = db.doc_document_create({
            "intervention_id": intervention_id, "client_id": interv.get("client_id"),
            "doc_type": "runbook", "format": output_format,
            "title": f"Runbook {interv['number']}",
            "file_path": output_path, "content_md": content_md,
            "size_bytes": result.get("size") or 0,
        })
        return {"success": True, "path": output_path, "document": doc,
                "message": f"Runbook généré : {output_path}"}
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_generate_schema(args: dict) -> dict:
    """
    Génère un schéma logique en Mermaid à partir d'une configuration réseau.
    Retourne le code Mermaid (que le frontend peut afficher) + un fichier .md.
    """
    network_config = _text(args.get("network_config"))
    title = args.get("title", "Schéma réseau")
    save_to_file = args.get("save", True)

    try:
        # Auto-extract IPs and devices from network_config text
        import re as _re
        ips = list(set(_re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", network_config)))
        # Detect typical devices via patterns
        device_patterns = {
            "Firewall":   [r"firewall", r"pfsense", r"fortigate", r"sophos"],
            "Switch":     [r"switch", r"cisco", r"hp.{0,5}switch"],
            "Router":     [r"routeur", r"router", r"livebox", r"freebox"],
            "Server":     [r"serveur", r"server", r"windows server", r"ad/dc", r"active directory"],
            "NAS":        [r"\bnas\b", r"synology", r"qnap"],
            "Workstation":[r"poste", r"workstation", r"pc utilisateur"],
        }
        devices_found = {}
        text_lower = network_config.lower()
        for kind, pats in device_patterns.items():
            for p in pats:
                if _re.search(p, text_lower):
                    devices_found[kind] = devices_found.get(kind, 0) + 1
                    break

        # Build Mermaid graph
        lines = ["graph TB"]
        lines.append("    WAN[Internet / FAI]")
        if "Firewall" in devices_found:
            lines.append("    FW[Firewall]")
            lines.append("    WAN --> FW")
            uplink = "FW"
        else:
            uplink = "WAN"
        if "Router" in devices_found:
            lines.append(f"    RT[Routeur]")
            lines.append(f"    {uplink} --> RT")
            uplink = "RT"
        if "Switch" in devices_found:
            lines.append(f"    SW[Switch principal]")
            lines.append(f"    {uplink} --> SW")
            uplink = "SW"
        if "Server" in devices_found:
            for i in range(min(devices_found["Server"], 3)):
                lines.append(f"    SRV{i+1}[Serveur {i+1}]")
                lines.append(f"    {uplink} --> SRV{i+1}")
        if "NAS" in devices_found:
            lines.append(f"    NAS[NAS]")
            lines.append(f"    {uplink} --> NAS")
        if "Workstation" in devices_found:
            count = devices_found["Workstation"]
            lines.append(f"    PCS[{count} poste{'s' if count > 1 else ''} utilisateur{'s' if count > 1 else ''}]")
            lines.append(f"    {uplink} --> PCS")
        # If no devices detected, generate a generic template
        if not devices_found:
            lines = [
                "graph TB",
                "    WAN[Internet]",
                "    FW[Firewall]",
                "    SW[Switch]",
                "    SRV[Serveur]",
                "    PCS[Postes utilisateurs]",
                "    WAN --> FW",
                "    FW --> SW",
                "    SW --> SRV",
                "    SW --> PCS",
            ]

        mermaid_code = "\n".join(lines)

        content_md = f"""# {title}

## Schéma de l'infrastructure

```mermaid
{mermaid_code}
```

## Éléments détectés

| Type | Quantité |
|------|----------|
""" + "\n".join([f"| {k} | {v} |" for k, v in devices_found.items()]) + f"""

## Adresses IP relevées
{', '.join(ips[:20]) if ips else '_(aucune)_'}

---
*Schéma généré par Marvin AI à partir de la configuration réseau fournie.*
"""

        path = None
        if save_to_file:
            from datetime import datetime as _dt
            path = args.get("output_path") or str(
                Path(_SYSTEM_PATHS["desktop"]) /
                f"schema_{_dt.now().strftime('%Y%m%d_%H%M%S')}.md"
            )
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content_md, encoding="utf-8")

        return {
            "success": True,
            "mermaid": mermaid_code,
            "markdown": content_md,
            "devices_detected": devices_found,
            "ips_found": ips[:20],
            "path": path,
            "message": (f"Schéma sauvegardé : {path}" if path else "Schéma Mermaid généré (non sauvegardé)"),
        }
    except Exception as e:
        return {"error": str(e)}


async def _doc_export_md(content_md: str, title: str, doc_type: str, output_format: str,
                        output_path: str | None, intervention_id=None, client_id=None,
                        subtitle: str = "") -> dict:
    """Exporte un markdown en PDF/docx + enregistre le document. Mutualisé."""
    fmt, format_error = _format(output_format, ("pdf", "docx"))
    if format_error:
        return format_error
    safe = _re.sub(r"[^\w-]", "_", title.lower())[:40]
    out = output_path or str(Path(_SYSTEM_PATHS["desktop"]) / f"{safe}.{fmt}")
    if fmt == "docx":
        res = await _file_create_docx({"path": out, "title": title, "subtitle": subtitle, "content": content_md})
    else:
        res = await _file_create_pdf({"path": out, "title": title, "subtitle": subtitle, "content": content_md})
    if res.get("error"):
        return res
    out = res.get("path", out)
    try:
        db.doc_document_create({"intervention_id": intervention_id, "client_id": client_id,
                                "doc_type": doc_type, "format": fmt, "title": title,
                                "file_path": out, "content_md": content_md, "size_bytes": res.get("size") or 0})
    except Exception:
        pass
    return {"success": True, "path": out, "markdown": content_md, "message": f"Document généré : {out}"}


async def execute_doc_generate_postmortem(args: dict) -> dict:
    """📋 Génère un POST-MORTEM / analyse de cause racine (RCA) d'un incident."""
    from datetime import datetime as _dt
    interv = db.doc_intervention_get(args["intervention_id"]) if args.get("intervention_id") else {}
    title = args.get("title") or interv.get("title") or "Post-mortem incident"
    sev = {"critical": "🔴 Critique", "high": "🟠 Élevée", "medium": "🟡 Moyenne", "low": "🟢 Basse"}.get(
        args.get("severity") or interv.get("priority", "medium"), "🟡 Moyenne")
    md = [f"## Résumé exécutif\n{args.get('summary') or interv.get('summary') or '_(résumé de l_incident)_'}\n",
          "## Informations clés",
          f"| Champ | Valeur |\n|---|---|\n| Gravité | {sev} |\n| Date de l'incident | {args.get('incident_date', _dt.now().strftime('%d/%m/%Y'))} |"
          f"\n| Durée d'indisponibilité | {args.get('downtime', '_(à préciser)_')} |\n| Services impactés | {args.get('services_impacted', '_(à préciser)_')} |"
          f"\n| Détecté par | {args.get('detected_by', '_(supervision/utilisateur)_')} |\n",
          "## Chronologie des événements",
          args.get("timeline") or "- **HH:MM** — Détection\n- **HH:MM** — Diagnostic\n- **HH:MM** — Mitigation\n- **HH:MM** — Résolution\n",
          "## Cause racine",
          args.get("root_cause") or interv.get("root_cause") or "_(analyse de la cause première — pourquoi ? les 5 pourquoi)_\n",
          "## Impact",
          f"- **Technique** : {args.get('technical_impact', '_(systèmes touchés)_')}\n- **Métier** : {args.get('business_impact', '_(utilisateurs, CA, image)_')}\n",
          "## Résolution",
          args.get("resolution") or interv.get("resolution") or "_(comment l'incident a été résolu)_\n",
          "## Actions correctives & préventives",
          args.get("corrective_actions") or "| Action | Responsable | Échéance | Priorité |\n|---|---|---|---|\n| _(à définir)_ | | | |\n",
          "## Leçons apprises",
          args.get("lessons") or "- _(ce qui a bien fonctionné)_\n- _(ce qui est à améliorer)_\n"]
    return await _doc_export_md("\n".join(md), f"Post-mortem — {title}", "postmortem",
                               args.get("format", "pdf"), args.get("output_path"),
                               args.get("intervention_id"), interv.get("client_id"),
                               subtitle="Analyse de cause racine (RCA)")


async def execute_doc_generate_change(args: dict) -> dict:
    """🔄 Génère une DEMANDE DE CHANGEMENT (Change Request ITIL)."""
    interv = db.doc_intervention_get(args["intervention_id"]) if args.get("intervention_id") else {}
    title = args.get("title") or interv.get("title") or "Demande de changement"
    risk = {"low": "🟢 Faible", "medium": "🟡 Moyen", "high": "🟠 Élevé", "critical": "🔴 Critique"}.get(args.get("risk", "medium"), "🟡 Moyen")
    md = [f"## Objet du changement\n{args.get('description') or '_(description du changement demandé)_'}\n",
          "## Synthèse",
          f"| Champ | Valeur |\n|---|---|\n| Type | {args.get('change_type', 'Normal')} |\n| Niveau de risque | {risk} |"
          f"\n| Demandeur | {args.get('requester', '_(à préciser)_')} |\n| Date souhaitée | {args.get('planned_date', '_(à préciser)_')} |"
          f"\n| Fenêtre de maintenance | {args.get('window', '_(hors heures ouvrées)_')} |\n",
          "## Justification / bénéfices",
          args.get("justification") or "_(pourquoi ce changement est nécessaire)_\n",
          "## Périmètre & systèmes concernés",
          args.get("scope") or "_(serveurs, services, utilisateurs impactés)_\n",
          "## Plan de mise en œuvre",
          args.get("implementation_plan") or "1. _(étape)_\n2. _(étape)_\n3. _(vérification)_\n",
          "## Analyse de risque & impact",
          args.get("risk_analysis") or f"Niveau de risque : {risk}. _(impacts potentiels, interruptions)_\n",
          "## Plan de retour arrière (rollback)",
          args.get("rollback_plan") or "_(comment annuler le changement si problème — point de restauration, sauvegarde)_\n",
          "## Tests de validation",
          args.get("validation_tests") or "- _(test post-changement à réaliser)_\n",
          "## Validation",
          "| Rôle | Nom | Décision | Date |\n|---|---|---|---|\n| Demandeur | | | |\n| Validateur (CAB) | | | |\n"]
    return await _doc_export_md("\n".join(md), f"Change Request — {title}", "change",
                               args.get("format", "pdf"), args.get("output_path"),
                               args.get("intervention_id"), interv.get("client_id"),
                               subtitle="Demande de changement (ITIL)")


async def execute_doc_generate_onboarding(args: dict) -> dict:
    """👤 Génère une fiche d'ARRIVÉE ou de DÉPART IT d'un collaborateur (checklist)."""
    mode = (args.get("mode") or "onboarding").lower()
    person = args.get("person_name", "_(Nom du collaborateur)_")
    is_off = mode in ("offboarding", "départ", "depart", "sortie")
    title = f"{'Départ' if is_off else 'Arrivée'} IT — {person}"
    verb = "Désactiver / récupérer" if is_off else "Créer / fournir"
    accounts = ("- [ ] Désactiver compte AD / Microsoft 365\n- [ ] Bloquer la messagerie + transfert vers le manager\n"
                "- [ ] Révoquer les accès VPN / applications\n- [ ] Changer les mots de passe partagés\n"
                if is_off else
                "- [ ] Créer le compte AD / Microsoft 365\n- [ ] Configurer la messagerie + signature\n"
                "- [ ] Donner les accès applications métiers\n- [ ] Configurer le VPN si télétravail\n")
    hardware = ("- [ ] Récupérer le PC portable + chargeur\n- [ ] Récupérer le téléphone / SIM\n"
                "- [ ] Récupérer badges / clés / périphériques\n- [ ] Effacer et reconditionner le matériel\n"
                if is_off else
                "- [ ] Préparer et configurer le PC\n- [ ] Installer les logiciels nécessaires\n"
                "- [ ] Fournir téléphone / périphériques\n- [ ] Remettre badge / accès locaux\n")
    md = [f"## Collaborateur\n| Champ | Valeur |\n|---|---|\n| Nom | {person} |\n| Poste / Service | {args.get('role', '_(à préciser)_')} |"
          f"\n| Date d'effet | {args.get('date', '_(à préciser)_')} |\n| Manager | {args.get('manager', '_(à préciser)_')} |\n",
          f"## Comptes & accès — {verb}\n{accounts}",
          f"## Matériel — {verb}\n{hardware}",
          "## Données",
          ("- [ ] Sauvegarder/transférer les fichiers et la boîte mail\n- [ ] Réaffecter les documents partagés\n"
           if is_off else "- [ ] Préparer l'espace de stockage / partages\n- [ ] Restaurer les données si mutation\n"),
          "## Sécurité",
          ("- [ ] Vérifier qu'aucun accès résiduel ne subsiste\n- [ ] Journaliser la clôture\n"
           if is_off else "- [ ] Sensibiliser aux bonnes pratiques (phishing, mot de passe)\n- [ ] Activer la double authentification\n"),
          f"## Validation\n| Étape | Responsable | Fait le |\n|---|---|---|\n| Préparation | {args.get('technician', 'IT')} | |\n| Validation manager | | |\n"]
    return await _doc_export_md("\n".join(md), title, "onboarding",
                               args.get("format", "pdf"), args.get("output_path"),
                               None, None,
                               subtitle="Checklist " + ("offboarding" if is_off else "onboarding"))


async def execute_doc_template_list(args: dict) -> dict:
    """Liste les templates de documentation disponibles."""
    try:
        templates = db.doc_template_list(args.get("doc_type"))
        return {"success": True, "count": len(templates), "templates": templates}
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_asset_create(args: dict) -> dict:
    """Crée un asset (CMDB-lite) : poste, serveur, équipement réseau…"""
    if not args.get("name"):
        return {"error": "Paramètre 'name' requis."}
    try:
        asset = db.doc_asset_create(args)
        return {"success": True, "asset": asset, "message": f"Asset '{asset['name']}' créé."}
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_asset_list(args: dict) -> dict:
    """Liste les assets (par client_id optionnel)."""
    try:
        assets = db.doc_asset_list(args.get("client_id"))
        return {"success": True, "count": len(assets), "assets": assets}
    except Exception as e:
        return {"error": str(e)}


async def execute_doc_knowledge_search(args: dict) -> dict:
    """Cherche dans la base de connaissances (interventions passées) par mot-clé."""
    query = _text(args.get("query")).lower()
    if not query:
        return {"error": "Paramètre 'query' requis."}
    try:
        all_interv = db.doc_intervention_list(limit=500)
        results = []
        for i in all_interv:
            score = 0
            haystack = " ".join([
                i.get("title",""), i.get("raw_notes",""), i.get("summary",""),
                i.get("resolution",""), i.get("root_cause","")
            ]).lower()
            if query in haystack:
                score += haystack.count(query)
                results.append({
                    "id": i["id"], "number": i["number"], "title": i["title"],
                    "intervention_type": i.get("intervention_type"),
                    "status": i.get("status"),
                    "snippet": (i.get("resolution") or i.get("summary") or i.get("raw_notes",""))[:300],
                    "score": score,
                    "created_at": i.get("created_at",""),
                })
        results.sort(key=lambda r: r["score"], reverse=True)
        return {
            "success": True,
            "query": query,
            "count": len(results),
            "results": results[:20],
            "hint": "Utilisez cette knowledge base pour résoudre rapidement des incidents similaires.",
        }
    except Exception as e:
        return {"error": str(e)}
