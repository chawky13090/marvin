"""Contr?les pr?/post-intervention et preuves op?rationnelles, sans ex?cution implicite."""
from __future__ import annotations

import datetime as _dt
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import database as db
from platform_paths import PATHS as _SYSTEM_PATHS

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

async def _missing_tool(_args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "D?pendance documentaire non configur?e."}

_file_create_docx: Tool = _missing_tool
_file_create_pdf: Tool = _missing_tool

def configure(*, file_create_docx: Tool, file_create_pdf: Tool) -> None:
    global _file_create_docx, _file_create_pdf
    _file_create_docx = file_create_docx
    _file_create_pdf = file_create_pdf

def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""

_PRECHECK_TEMPLATES = {
    "deployment": [
        ("Sauvegarde réalisée avant déploiement", "backup", "Sauvegarde complète disponible", "critical"),
        ("Fenêtre de maintenance validée", "planning", "Créneau confirmé avec le client", "warning"),
        ("Espace disque suffisant", "infrastructure", "≥ 20% libre", "warning", "Get-Volume"),
        ("Plan de retour arrière (rollback) préparé", "rollback", "Procédure documentée", "critical"),
        ("Utilisateurs prévenus", "communication", "Notification envoyée", "info"),
        ("Compatibilité vérifiée", "compatibility", "Prérequis logiciels validés", "warning"),
    ],
    "maintenance": [
        ("Sauvegarde récente disponible", "backup", "< 24h", "critical"),
        ("État initial documenté", "documentation", "Captures/logs avant", "warning"),
        ("Fenêtre de maintenance respectée", "planning", "Horaire convenu", "warning"),
        ("Services critiques identifiés", "infrastructure", "Liste à jour", "info"),
    ],
    "change": [
        ("Demande de changement approuvée", "approval", "Ticket validé", "critical"),
        ("Sauvegarde de la configuration", "backup", "Config exportée", "critical"),
        ("Impact évalué", "risk", "Analyse d'impact faite", "warning"),
        ("Plan de rollback prêt", "rollback", "Procédure testée", "critical"),
        ("Communication faite", "communication", "Parties prenantes informées", "info"),
    ],
    "incident": [
        ("Périmètre de l'incident délimité", "scope", "Systèmes affectés identifiés", "warning"),
        ("Sauvegarde avant manipulation", "backup", "Snapshot si possible", "critical"),
        ("Impact métier évalué", "risk", "Criticité confirmée", "warning"),
        ("Ticket ouvert", "documentation", "Référence tracée", "info"),
    ],
    "audit": [
        ("Périmètre d'audit défini", "scope", "Documenté", "info"),
        ("Accès en lecture seule confirmé", "security", "Pas de modification", "critical"),
        ("Outils d'audit prêts", "tools", "Disponibles", "info"),
    ],
    "default": [
        ("Sauvegarde disponible", "backup", "Récente", "critical"),
        ("Impact évalué", "risk", "Analysé", "warning"),
        ("Client informé", "communication", "Notifié", "info"),
        ("Plan de rollback", "rollback", "Préparé", "warning"),
    ],
}

_POSTCHECK_TEMPLATES = {
    "deployment": [
        ("Service/application démarré(e)", "validation", "Statut Running", "critical", "Get-Service"),
        ("Tests fonctionnels OK", "validation", "Fonctionnalités vérifiées", "critical"),
        ("Pas d'erreur dans les logs", "validation", "Journaux propres", "warning", "Get-EventLog -LogName Application -Newest 20 -EntryType Error"),
        ("Performances nominales", "performance", "Temps de réponse normaux", "warning"),
        ("Sauvegarde post-déploiement", "backup", "Nouvelle sauvegarde", "warning"),
        ("Documentation mise à jour", "documentation", "Rapport rédigé", "info"),
        ("Utilisateurs informés de la fin", "communication", "Notification envoyée", "info"),
    ],
    "maintenance": [
        ("Tous les services redémarrés", "validation", "Running", "critical", "Get-Service"),
        ("Espace disque vérifié", "infrastructure", "OK", "warning", "Get-Volume"),
        ("Sauvegardes fonctionnelles", "backup", "Testées", "critical"),
        ("Logs sans erreur critique", "validation", "Propres", "warning"),
        ("Rapport de maintenance rédigé", "documentation", "Document généré", "info"),
    ],
    "change": [
        ("Changement appliqué et vérifié", "validation", "Effectif", "critical"),
        ("Tests de non-régression OK", "validation", "Pas de régression", "critical"),
        ("Logs vérifiés", "validation", "Propres", "warning"),
        ("Rollback non nécessaire", "rollback", "Changement stable", "info"),
        ("Documentation à jour", "documentation", "CMDB mise à jour", "warning"),
    ],
    "incident": [
        ("Service rétabli", "validation", "Fonctionnel", "critical", "Get-Service"),
        ("Cause racine identifiée", "rca", "Documentée", "warning"),
        ("Tests utilisateur OK", "validation", "Confirmé par le client", "critical"),
        ("Mesures préventives notées", "prevention", "Recommandations", "info"),
        ("Ticket clôturé", "documentation", "Résolution tracée", "info"),
    ],
    "audit": [
        ("Rapport d'audit produit", "documentation", "Livré", "critical"),
        ("Recommandations formulées", "recommendation", "Listées", "warning"),
        ("Aucune modification effectuée", "security", "Lecture seule respectée", "critical"),
    ],
    "default": [
        ("Service fonctionnel", "validation", "OK", "critical"),
        ("Tests effectués", "validation", "Passés", "warning"),
        ("Documentation produite", "documentation", "Rapport", "info"),
        ("Client informé", "communication", "Notifié", "info"),
    ],
}

async def execute_ops_checklist_generate(args: dict) -> dict:
    """
    Génère automatiquement les points de contrôle selon le type d'intervention.
    Ne crée PAS de checklist en base — retourne juste les items proposés.
    """
    intervention_type = _text(args.get("intervention_type")) or "default"
    check_type = _text(args.get("check_type")) or "precheck"
    if check_type not in ("precheck", "postcheck"):
        return {"error": "check_type invalide (precheck|postcheck)."}

    templates = _PRECHECK_TEMPLATES if check_type == "precheck" else _POSTCHECK_TEMPLATES
    items_raw = templates.get(intervention_type, templates["default"])

    items = []
    for idx, t in enumerate(items_raw):
        item = {
            "label": t[0],
            "category": t[1],
            "expected": t[2],
            "severity": t[3],
            "order_index": idx,
            "auto_command": t[4] if len(t) > 4 else "",
        }
        items.append(item)

    return {
        "success": True,
        "check_type": check_type,
        "intervention_type": intervention_type,
        "items": items,
        "count": len(items),
        "hint": "Utilisez ops_precheck_create / ops_postcheck_run pour matérialiser cette checklist.",
    }

async def execute_ops_precheck_create(args: dict) -> dict:
    """
    Crée une checklist (pre-check par défaut) liée à une intervention,
    avec des points de contrôle auto-générés selon le type.
    """
    intervention_id = args.get("intervention_id")
    if not intervention_id:
        return {"error": "Paramètre 'intervention_id' requis."}
    check_type = _text(args.get("check_type")) or "precheck"
    if check_type not in ("precheck", "postcheck"):
        return {"error": "check_type invalide (precheck|postcheck)."}

    try:
        # Récupérer le type d'intervention pour générer les bons items
        interv = db.doc_intervention_get(intervention_id)
        if not interv:
            return {"error": "Intervention introuvable"}
        itype = interv.get("intervention_type", "default")

        # Créer la checklist
        title = args.get("title") or (
            f"Pré-check — {interv['title']}" if check_type == "precheck"
            else f"Post-check — {interv['title']}"
        )
        check = db.ops_check_create({
            "intervention_id": intervention_id,
            "check_type": check_type,
            "title": title,
        })

        # Générer + insérer les items (depuis args.items si fourni, sinon auto)
        if args.get("items") and isinstance(args["items"], list):
            items_data = args["items"][:100]
        else:
            gen = await execute_ops_checklist_generate({
                "intervention_type": itype, "check_type": check_type
            })
            items_data = gen["items"]

        for it in items_data:
            db.ops_item_create(check["id"], it)

        return {
            "success": True,
            "message": f"Checklist {check_type} créée ({len(items_data)} points).",
            "check": db.ops_check_get(check["id"]),
        }
    except Exception as e:
        return {"error": str(e)}

async def execute_ops_precheck_run(args: dict) -> dict:
    """
    Enregistre les résultats d'un pre-check (ok/warning/failed/skipped par item).
    NB : n'exécute aucune commande système — l'opérateur fournit les résultats.
    """
    return await _ops_run_check(args, expected_type="precheck")

async def execute_ops_postcheck_run(args: dict) -> dict:
    """Enregistre les résultats d'un post-check (validation après intervention)."""
    return await _ops_run_check(args, expected_type="postcheck")

async def _ops_run_check(args: dict, expected_type: str) -> dict:
    check_id = args.get("check_id")
    results = args.get("results", [])  # [{item_id, status, actual_value, notes}]
    if not check_id:
        return {"error": "Paramètre 'check_id' requis."}
    if not isinstance(results, list):
        return {"error": "Paramètre 'results' invalide : liste attendue."}
    if len(results) > 100:
        return {"error": "Paramètre 'results' limité à 100 éléments."}
    try:
        check = db.ops_check_get(check_id)
        if not check:
            return {"error": "Checklist introuvable"}
        if check.get("check_type") != expected_type:
            return {
                "error": (
                    f"Type de checklist incompatible : attendu {expected_type}, "
                    f"reçu {check.get('check_type') or 'inconnu'}."
                )
            }

        # Enregistrer chaque résultat fourni
        for r in results:
            if not isinstance(r, dict):
                return {"error": "Chaque résultat doit être un objet."}
            status = _text(r.get("status")) or "skipped"
            if status not in ("ok", "warning", "failed", "skipped"):
                return {"error": f"Statut de résultat invalide : {status}."}
            if r.get("item_id"):
                db.ops_result_set(check_id, r["item_id"], {
                    "status": status,
                    "actual_value": r.get("actual_value", ""),
                    "notes": r.get("notes", ""),
                })

        # Recharger et calculer le statut global
        check = db.ops_check_get(check_id)
        statuses = [it.get("result", {}).get("status") if it.get("result") else "skipped"
                    for it in check["items"]]
        n_failed = statuses.count("failed")
        n_warning = statuses.count("warning")
        n_ok = statuses.count("ok")

        # Un échec sur un item critical = checklist failed
        critical_failed = any(
            it.get("severity") == "critical" and
            (it.get("result", {}).get("status") if it.get("result") else "skipped") == "failed"
            for it in check["items"]
        )
        if critical_failed or n_failed > 0:
            global_status = "failed"
        elif n_warning > 0:
            global_status = "partial"
        elif n_ok > 0:
            global_status = "passed"
        else:
            global_status = "running"

        summary = f"{n_ok} OK, {n_warning} avertissement(s), {n_failed} échec(s) sur {len(statuses)} points."
        db.ops_check_update(check_id, {
            "status": global_status,
            "summary": summary,
            "completed_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        return {
            "success": True,
            "global_status": global_status,
            "summary": summary,
            "critical_failed": critical_failed,
            "check": db.ops_check_get(check_id),
        }
    except Exception as e:
        return {"error": str(e)}

async def execute_ops_evidence_add(args: dict) -> dict:
    """
    Associe une preuve à une checklist/item : texte, commande, chemin fichier, capture, log.
    NB : enregistre la référence/contenu — n'exécute rien.
    """
    evidence_type = _text(args.get("evidence_type")) or "text"
    content = _text(args.get("content"))
    if not content:
        return {"error": "Paramètre 'content' requis."}
    if evidence_type not in ("text", "command", "file_path", "screenshot", "log"):
        return {"error": "evidence_type invalide (text|command|file_path|screenshot|log)"}
    try:
        ev = db.ops_evidence_create({
            "check_id": args.get("check_id"),
            "item_id": args.get("item_id"),
            "result_id": args.get("result_id"),
            "intervention_id": args.get("intervention_id"),
            "evidence_type": evidence_type,
            "content": content,
        })
        return {"success": True, "evidence": ev, "message": "Preuve ajoutée."}
    except Exception as e:
        return {"error": str(e)}

async def execute_ops_validation_report_generate(args: dict) -> dict:
    """
    Génère un rapport de validation (pre-check + post-check + preuves) en MD/PDF/DOCX.
    Réutilise les générateurs de documents existants du projet.
    """
    intervention_id = args.get("intervention_id")
    output_format = (_text(args.get("format")) or "pdf").lower()
    if not intervention_id:
        return {"error": "Paramètre 'intervention_id' requis."}
    if output_format not in ("pdf", "docx", "md"):
        return {"error": "Format invalide. Formats acceptés : pdf, docx, md."}
    try:
        interv = db.doc_intervention_get(intervention_id)
        if not interv:
            return {"error": "Intervention introuvable"}

        prechecks = db.ops_check_list(intervention_id, "precheck")
        postchecks = db.ops_check_list(intervention_id, "postcheck")
        evidence = db.ops_evidence_list(intervention_id)

        from datetime import datetime as _dt
        date_str = _dt.now().strftime("%d/%m/%Y %H:%M")

        def render_check_block(checks, label):
            if not checks:
                return f"### {label}\n\n_(aucune checklist)_\n"
            out = f"### {label}\n"
            for c in checks:
                full = db.ops_check_get(c["id"])
                status_emoji = {"passed":"✅","failed":"❌","partial":"⚠️","running":"🔄","pending":"⏳"}.get(full["status"], "•")
                out += f"\n**{status_emoji} {full['title']}** — {full.get('summary','')}\n\n"
                out += "| Point de contrôle | Sévérité | Résultat | Note |\n|---|---|---|---|\n"
                for it in full["items"]:
                    res = it.get("result") or {}
                    rstatus = res.get("status", "skipped")
                    remoji = {"ok":"✅","warning":"⚠️","failed":"❌","skipped":"⬜"}.get(rstatus, "")
                    note = (res.get("notes","") or res.get("actual_value","") or "").replace("|","/")[:60]
                    out += f"| {it['label']} | {it['severity']} | {remoji} {rstatus} | {note} |\n"
                out += "\n"
            return out

        evidence_block = ""
        if evidence:
            evidence_block = "## Preuves collectées\n\n"
            for e in evidence:
                etype = {"text":"📝 Note","command":"⚡ Commande","file_path":"📂 Fichier",
                         "screenshot":"📷 Capture","log":"📋 Log"}.get(e["evidence_type"], e["evidence_type"])
                content_short = (e.get("content","") or "")[:200]
                evidence_block += f"- **{etype}** : `{content_short}`\n"

        content_md = f"""# Rapport de Validation — {interv['number']}

**Intervention :** {interv['title']}
**Date du rapport :** {date_str}
**Technicien :** {interv.get('technician') or '_(non renseigné)_'}
**Statut intervention :** {interv.get('status','')}

---

## Pré-checks (avant intervention)

{render_check_block(prechecks, "Vérification des prérequis")}

## Post-checks (après intervention)

{render_check_block(postchecks, "Validation de l'état final")}

{evidence_block}

---

## Conclusion

{interv.get('resolution') or interv.get('summary') or '_(à compléter)_'}

---
*Rapport de validation généré par Marvin AI (module Operations Safety v2.30).*
"""

        output_path = args.get("output_path") or str(
            Path(_SYSTEM_PATHS["desktop"]) /
            f"validation_{interv['number']}.{output_format}"
        )

        if output_format == "docx":
            result = await _file_create_docx({
                "path": output_path, "title": f"Validation {interv['number']}", "content": content_md,
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
                "path": output_path, "title": f"Validation {interv['number']}", "content": content_md,
            })

        if result.get("error"):
            return result

        # Save in doc_documents
        try:
            doc = db.doc_document_create({
                "intervention_id": intervention_id, "client_id": interv.get("client_id"),
                "doc_type": "report", "format": output_format,
                "title": f"Rapport de validation {interv['number']}",
                "file_path": output_path, "content_md": content_md,
                "template_used": "ops_validation", "size_bytes": result.get("size") or 0,
            })
        except Exception:
            doc = None

        return {
            "success": True,
            "message": f"Rapport de validation généré : {output_path}",
            "path": output_path,
            "document": doc,
            "precheck_count": len(prechecks),
            "postcheck_count": len(postchecks),
            "evidence_count": len(evidence),
        }
    except Exception as e:
        return {"error": str(e)}
