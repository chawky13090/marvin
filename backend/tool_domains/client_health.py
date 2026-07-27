"""Score de sant? client, recommandations et synth?se mensuelle."""
from __future__ import annotations

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

def _bounded_limit(value: Any, *, default: int = 12, maximum: int = 120) -> int:
    limit = int(value if value is not None else default)
    if not 1 <= limit <= maximum:
        raise ValueError(f"'limit' doit ?tre compris entre 1 et {maximum}.")
    return limit

async def execute_client_health_compute(args: dict) -> dict:
    """
    Calcule le score de santé opérationnelle d'un client (0-100 par axe).
    Axes : backup, security, documentation, infrastructure, incident.
    """
    client_id = args.get("client_id")
    if not client_id:
        return {"error": "Paramètre 'client_id' requis."}
    try:
        client = db.billing_client_get(client_id)
        if not client:
            return {"error": "Client introuvable"}

        # ── Collecte des données ──
        interventions = db.doc_intervention_list(client_id, limit=500)
        assets = db.doc_asset_list(client_id)
        documents = db.doc_document_list(client_id=client_id)
        cmd_reviews = []
        for iv in interventions:
            cmd_reviews.extend(db.cmd_review_list(iv["id"], limit=200))

        from datetime import datetime as _dt, timedelta as _td
        now = _dt.now()

        def parse_dt(s):
            try:
                return _dt.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None

        items = []
        recommendations = []

        # ── 1. DOCUMENTATION (0-100) ──
        doc_score = 100.0
        has_client_sheet = any(d["doc_type"] == "client_sheet" for d in documents)
        if not has_client_sheet:
            doc_score -= 35
            items.append({"category":"documentation","label":"Fiche client","points":0,"max_points":35,"status":"failed","detail":"Aucune fiche client générée"})
            recommendations.append({"priority":"high","category":"documentation","title":"Créer une fiche client","description":"Générez une fiche client complète (infrastructure, contacts, contrats)."})
        else:
            items.append({"category":"documentation","label":"Fiche client","points":35,"max_points":35,"status":"ok","detail":"Présente"})

        recent_docs = [d for d in documents if (pd := parse_dt(d.get("created_at",""))) and (now - pd).days < 90]
        if not recent_docs:
            doc_score -= 25
            items.append({"category":"documentation","label":"Documents récents (90j)","points":0,"max_points":25,"status":"warning","detail":"Aucun document récent"})
            recommendations.append({"priority":"medium","category":"documentation","title":"Documenter les interventions récentes","description":"Générez des rapports pour les dernières interventions."})
        else:
            items.append({"category":"documentation","label":"Documents récents (90j)","points":25,"max_points":25,"status":"ok","detail":f"{len(recent_docs)} document(s)"})

        # Interventions sans post-check
        interv_without_postcheck = 0
        for iv in interventions:
            if iv["status"] in ("resolved", "closed"):
                postchecks = db.ops_check_list(iv["id"], "postcheck")
                if not postchecks:
                    interv_without_postcheck += 1
        if interv_without_postcheck > 0:
            penalty = min(40, interv_without_postcheck * 10)
            doc_score -= penalty
            items.append({"category":"documentation","label":"Post-checks","points":40-penalty,"max_points":40,"status":"warning","detail":f"{interv_without_postcheck} intervention(s) sans post-check"})
            recommendations.append({"priority":"medium","category":"validation","title":"Réaliser des post-checks","description":f"{interv_without_postcheck} intervention(s) résolue(s) sans validation post-intervention."})
        else:
            items.append({"category":"documentation","label":"Post-checks","points":40,"max_points":40,"status":"ok","detail":"Toutes validées"})
        doc_score = max(0, doc_score)

        # ── 2. INFRASTRUCTURE (0-100) ──
        infra_score = 100.0
        if not assets:
            infra_score -= 50
            items.append({"category":"infrastructure","label":"Inventaire CMDB","points":0,"max_points":50,"status":"warning","detail":"Aucun asset enregistré"})
            recommendations.append({"priority":"medium","category":"infrastructure","title":"Inventorier les assets","description":"Ajoutez les postes/serveurs/équipements dans la CMDB."})
        else:
            items.append({"category":"infrastructure","label":"Inventaire CMDB","points":50,"max_points":50,"status":"ok","detail":f"{len(assets)} asset(s)"})
            critical_assets = [a for a in assets if a.get("criticality") in ("high","critical")]
            undocumented_critical = [a for a in critical_assets if not a.get("specs") and not a.get("os")]
            if undocumented_critical:
                penalty = min(50, len(undocumented_critical) * 15)
                infra_score -= penalty
                items.append({"category":"infrastructure","label":"Assets critiques documentés","points":50-penalty,"max_points":50,"status":"warning","detail":f"{len(undocumented_critical)} asset(s) critique(s) peu documenté(s)"})
                recommendations.append({"priority":"high","category":"infrastructure","title":"Documenter les assets critiques","description":f"{len(undocumented_critical)} asset(s) critique(s) sans specs/OS renseignés."})
            else:
                items.append({"category":"infrastructure","label":"Assets critiques documentés","points":50,"max_points":50,"status":"ok","detail":"OK"})
        infra_score = max(0, infra_score)

        # ── 3. INCIDENT (0-100) ──
        incident_score = 100.0
        open_critical = [iv for iv in interventions
                         if iv.get("priority") == "critical" and iv["status"] in ("open","in_progress")]
        if open_critical:
            penalty = min(60, len(open_critical) * 30)
            incident_score -= penalty
            items.append({"category":"incident","label":"Incidents critiques ouverts","points":60-penalty,"max_points":60,"status":"failed","detail":f"{len(open_critical)} ouvert(s)"})
            recommendations.append({"priority":"critical","category":"incident","title":"Traiter les incidents critiques","description":f"{len(open_critical)} incident(s) critique(s) non résolu(s)."})
        else:
            items.append({"category":"incident","label":"Incidents critiques ouverts","points":60,"max_points":60,"status":"ok","detail":"Aucun"})

        # Incidents récurrents (même type)
        from collections import Counter as _C
        type_counts = _C(iv.get("itil_category","") for iv in interventions if iv.get("itil_category"))
        recurring = [(k,v) for k,v in type_counts.items() if v >= 3]
        if recurring:
            incident_score -= 40
            items.append({"category":"incident","label":"Incidents récurrents","points":0,"max_points":40,"status":"warning","detail":f"{len(recurring)} catégorie(s) récurrente(s)"})
            recommendations.append({"priority":"high","category":"incident","title":"Traiter les causes récurrentes","description":f"Catégories répétées : {', '.join(k for k,v in recurring)}. Action de fond recommandée."})
        else:
            items.append({"category":"incident","label":"Incidents récurrents","points":40,"max_points":40,"status":"ok","detail":"Pas de récurrence forte"})
        incident_score = max(0, incident_score)

        # ── 4. SECURITY (0-100) ──
        security_score = 100.0
        # Commandes high/critical/blocked dans l'historique
        risky_cmds = [r for r in cmd_reviews if r.get("risk_level") in ("high","critical","blocked")]
        if risky_cmds:
            penalty = min(50, len(risky_cmds) * 10)
            security_score -= penalty
            blocked = [r for r in risky_cmds if r.get("risk_level") == "blocked"]
            items.append({"category":"security","label":"Commandes à risque","points":50-penalty,"max_points":50,"status":"failed" if blocked else "warning","detail":f"{len(risky_cmds)} commande(s) risquée(s), {len(blocked)} bloquée(s)"})
            if blocked:
                recommendations.append({"priority":"critical","category":"security","title":"Commandes destructives détectées","description":f"{len(blocked)} commande(s) bloquée(s) dans l'historique. Revue de sécurité requise."})
        else:
            items.append({"category":"security","label":"Commandes à risque","points":50,"max_points":50,"status":"ok","detail":"Aucune"})

        # Approbations en attente
        try:
            pending_approvals = db.approval_list("pending")
        except Exception:
            pending_approvals = []
        if pending_approvals:
            security_score -= 20
            items.append({"category":"security","label":"Approbations en attente","points":0,"max_points":20,"status":"warning","detail":f"{len(pending_approvals)} en attente"})
        else:
            items.append({"category":"security","label":"Approbations","points":20,"max_points":20,"status":"ok","detail":"Aucune en attente"})

        # RGPD
        rgpd_interv = [iv for iv in interventions if iv.get("rgpd_relevant")]
        if rgpd_interv:
            items.append({"category":"security","label":"Interventions RGPD","points":30,"max_points":30,"status":"warning","detail":f"{len(rgpd_interv)} intervention(s) sensible(s) RGPD"})
        else:
            items.append({"category":"security","label":"RGPD","points":30,"max_points":30,"status":"ok","detail":"RAS"})
        security_score = max(0, security_score)

        # ── 5. BACKUP (0-100) ──
        backup_score = 100.0
        has_recovery_plan = any(d["doc_type"] == "recovery_plan" for d in documents)
        if not has_recovery_plan:
            backup_score -= 50
            items.append({"category":"backup","label":"Plan de reprise (PRA)","points":0,"max_points":50,"status":"failed","detail":"Aucun PRA/PCA"})
            recommendations.append({"priority":"high","category":"backup","title":"Établir un plan de reprise (PRA)","description":"Aucun PRA/PCA documenté. Risque majeur en cas de sinistre."})
        else:
            items.append({"category":"backup","label":"Plan de reprise (PRA)","points":50,"max_points":50,"status":"ok","detail":"Présent"})

        has_maintenance = any(d["doc_type"] == "maintenance" for d in documents)
        if not has_maintenance:
            backup_score -= 50
            items.append({"category":"backup","label":"Plan de maintenance","points":0,"max_points":50,"status":"warning","detail":"Aucun plan de maintenance"})
            recommendations.append({"priority":"medium","category":"backup","title":"Mettre en place une maintenance préventive","description":"Aucun plan de maintenance documenté."})
        else:
            items.append({"category":"backup","label":"Plan de maintenance","points":50,"max_points":50,"status":"ok","detail":"Présent"})
        backup_score = max(0, backup_score)

        # ── GLOBAL ──
        global_score = round(
            (backup_score + security_score + doc_score + infra_score + incident_score) / 5, 1
        )
        if global_score >= 80:
            risk_level = "low"
        elif global_score >= 60:
            risk_level = "medium"
        elif global_score >= 40:
            risk_level = "high"
        else:
            risk_level = "critical"

        # Persist
        score_data = {
            "client_id": client_id,
            "backup_score": round(backup_score, 1),
            "security_score": round(security_score, 1),
            "documentation_score": round(doc_score, 1),
            "infrastructure_score": round(infra_score, 1),
            "incident_score": round(incident_score, 1),
            "global_score": global_score,
            "risk_level": risk_level,
        }
        saved = db.health_score_create(score_data, items, recommendations)

        return {
            "success": True,
            "client": client.get("name"),
            "scores": {
                "backup": round(backup_score, 1),
                "security": round(security_score, 1),
                "documentation": round(doc_score, 1),
                "infrastructure": round(infra_score, 1),
                "incident": round(incident_score, 1),
                "global": global_score,
            },
            "risk_level": risk_level,
            "items": items,
            "recommendations": recommendations,
            "score_id": saved["id"],
            "data_analyzed": {
                "interventions": len(interventions),
                "assets": len(assets),
                "documents": len(documents),
                "command_reviews": len(cmd_reviews),
            },
        }
    except Exception as e:
        return {"error": str(e)}

async def execute_client_health_get(args: dict) -> dict:
    """Récupère le dernier score de santé calculé pour un client."""
    client_id = args.get("client_id")
    if not client_id:
        return {"error": "Paramètre 'client_id' requis."}
    try:
        score = db.health_score_latest(client_id)
        if not score:
            return {"success": True, "score": None, "message": "Aucun score calculé. Lancez client_health_compute."}
        return {"success": True, "score": score}
    except Exception as e:
        return {"error": str(e)}

async def execute_client_health_history(args: dict) -> dict:
    """Historique des scores de santé d'un client (évolution dans le temps)."""
    client_id = args.get("client_id")
    if not client_id:
        return {"error": "Paramètre 'client_id' requis."}
    try:
        history = db.health_score_history(client_id, _bounded_limit(args.get("limit")))
        return {"success": True, "count": len(history), "history": history}
    except Exception as e:
        return {"error": str(e)}

async def execute_client_recommendations_generate(args: dict) -> dict:
    """Génère/liste les recommandations issues du dernier score de santé."""
    client_id = args.get("client_id")
    if not client_id:
        return {"error": "Paramètre 'client_id' requis."}
    try:
        # Recompute to get fresh recommendations if asked
        if args.get("recompute"):
            comp = await execute_client_health_compute({"client_id": client_id})
            if comp.get("error"):
                return comp
        status = _text(args.get("status")) or "open"
        if status not in ("open", "accepted", "dismissed", "done", "all"):
            return {"error": "Statut invalide."}
        recos = db.health_recommendations_list(client_id, status)
        # Sort by priority
        prio_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recos.sort(key=lambda r: prio_order.get(r.get("priority", "medium"), 2))
        return {"success": True, "count": len(recos), "recommendations": recos}
    except Exception as e:
        return {"error": str(e)}

async def execute_client_monthly_summary_generate(args: dict) -> dict:
    """
    Génère un compte-rendu mensuel pour un client (interventions, score santé, recommandations)
    en MD/PDF/DOCX.
    """
    client_id = args.get("client_id")
    output_format = (_text(args.get("format")) or "pdf").lower()
    if not client_id:
        return {"error": "Paramètre 'client_id' requis."}
    if output_format not in ("pdf", "docx", "md"):
        return {"error": "Format invalide. Formats acceptés : pdf, docx, md."}
    try:
        client = db.billing_client_get(client_id)
        if not client:
            return {"error": "Client introuvable"}

        from datetime import datetime as _dt, timedelta as _td
        now = _dt.now()
        month_ago = now - _td(days=30)

        def parse_dt(s):
            try: return _dt.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            except Exception: return None

        all_interv = db.doc_intervention_list(client_id, limit=500)
        month_interv = [iv for iv in all_interv if (pd := parse_dt(iv.get("created_at",""))) and pd >= month_ago]

        # Compute fresh health score
        comp = await execute_client_health_compute({"client_id": client_id})
        scores = comp.get("scores", {}) if comp.get("success") else {}
        risk_level = comp.get("risk_level", "?")
        recos = comp.get("recommendations", [])

        # Build markdown
        interv_table = ""
        for iv in month_interv[:30]:
            interv_table += f"| {iv.get('created_at','')[:10]} | {iv['number']} | {iv['title'][:40]} | {iv.get('intervention_type','')} | {iv.get('status','')} |\n"
        if not interv_table:
            interv_table = "| — | — | Aucune intervention ce mois-ci | — | — |\n"

        reco_block = ""
        for r in sorted(recos, key=lambda x: {"critical":0,"high":1,"medium":2,"low":3}.get(x.get("priority"),2))[:10]:
            pe = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢"}.get(r.get("priority"),"•")
            reco_block += f"- {pe} **{r.get('title','')}** — {r.get('description','')}\n"
        if not reco_block:
            reco_block = "_(aucune recommandation — situation saine)_\n"

        risk_emoji = {"low":"🟢","medium":"🟡","high":"🟠","critical":"🔴"}.get(risk_level,"")

        content_md = f"""# Compte-rendu mensuel — {client['name']}

**Période :** {month_ago.strftime('%d/%m/%Y')} → {now.strftime('%d/%m/%Y')}
**Généré le :** {now.strftime('%d/%m/%Y %H:%M')}

---

## 📊 Score de santé opérationnelle

**Score global : {scores.get('global','?')}/100** {risk_emoji} (risque : {risk_level})

| Axe | Score |
|-----|-------|
| 🔐 Sécurité | {scores.get('security','?')}/100 |
| 💾 Sauvegarde / PRA | {scores.get('backup','?')}/100 |
| 📄 Documentation | {scores.get('documentation','?')}/100 |
| 🖥️ Infrastructure | {scores.get('infrastructure','?')}/100 |
| 🚨 Incidents | {scores.get('incident','?')}/100 |

## 📋 Interventions du mois ({len(month_interv)})

| Date | N° | Titre | Type | Statut |
|------|----|----|------|--------|
{interv_table}

## 🎯 Recommandations

{reco_block}

---
*Compte-rendu généré automatiquement par Marvin AI (Operations Safety v2.30).*
"""

        output_path = args.get("output_path") or str(
            Path(_SYSTEM_PATHS["desktop"]) /
            f"CR_mensuel_{client['name'].replace(' ','_')}_{now.strftime('%Y%m')}.{output_format}"
        )

        if output_format == "docx":
            result = await _file_create_docx({
                "path": output_path, "title": f"CR mensuel — {client['name']}", "content": content_md,
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
                "path": output_path, "title": f"CR mensuel — {client['name']}", "content": content_md,
            })
        if result.get("error"):
            return result

        try:
            doc = db.doc_document_create({
                "client_id": client_id, "doc_type": "report", "format": output_format,
                "title": f"CR mensuel {client['name']} {now.strftime('%Y-%m')}",
                "file_path": output_path, "content_md": content_md,
                "template_used": "monthly_summary", "size_bytes": result.get("size") or 0,
            })
        except Exception:
            doc = None

        return {
            "success": True,
            "message": f"Compte-rendu mensuel généré : {output_path}",
            "path": output_path,
            "document": doc,
            "interventions_this_month": len(month_interv),
            "global_score": scores.get("global"),
        }
    except Exception as e:
        return {"error": str(e)}
