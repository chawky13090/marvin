"""
SecretaryAI Backend — Couche base de données SQLite.
Source de vérité pour data/secretary.db (v2.111 : le frontend Next.js n'y accède plus
en direct que pour getSetting/setSetting — conversations/notes/tasks/projects/mémoire
passent tous par ce module via des proxys /api/*, voir le changelog v2.107-111 dans
CLAUDE.md §9 pour le détail de cette consolidation).
Utilise le module sqlite3 standard de Python (thread-safe avec check_same_thread=False).
"""
import json
import uuid
from db_connection import db, get_conn, row_to_dict
from db_migrations import apply_migrations
from repositories.billing import (
    billing_catalog_create,
    billing_catalog_delete,
    billing_catalog_list,
    billing_client_create,
    billing_client_delete,
    billing_client_get,
    billing_client_list,
    billing_client_update,
    billing_contract_create,
    billing_contract_list,
    billing_invoice_create,
    billing_invoice_delete,
    billing_invoice_get,
    billing_invoice_list,
    billing_invoice_update,
    billing_quote_create,
    billing_quote_delete,
    billing_quote_get,
    billing_quote_list,
    billing_quote_update,
    repository as billing_repository,
)
from repositories.conversations import (
    create_conversation,
    create_message,
    delete_conversation,
    get_conversation,
    get_messages_by_conversation,
    get_recent_user_messages,
    list_conversations,
    search_conversations,
    set_conversation_pinned,
    update_conversation_project,
    update_conversation_title,
    upgrade_conversation_title_silent,
)
from repositories.cron_jobs import (
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    list_cron_jobs,
    repository as cron_job_repository,
    update_cron_job,
)
from repositories.events import (
    count_events_by_source,
    create_event,
    delete_event,
    delete_events_by_source,
    events_needing_reminder,
    get_event,
    list_events,
    replace_external_events,
    repository as event_repository,
    update_event,
)
from repositories.executions import (
    get_conversation_trace,
    get_execution_stats,
    get_tool_reliability,
    list_executions,
    log_execution,
    repository as execution_repository,
)
from repositories.logos import create_logo, list_logos
from repositories.memories import (
    clear_all_memories,
    create_memory,
    delete_memory,
    get_memories,
    update_memory,
)
from repositories.notes import (
    create_note,
    delete_note,
    get_note,
    list_notes,
    update_note,
)
from repositories.operations import (
    ops_check_create,
    ops_check_delete,
    ops_check_get,
    ops_check_list,
    ops_check_update,
    ops_evidence_create,
    ops_evidence_list,
    ops_item_create,
    ops_result_set,
    repository as operations_repository,
)
from repositories.network_inventory import (
    get_network_devices,
    repository as network_inventory_repository,
    set_network_device_notes,
    upsert_network_device,
)
from repositories.projects import (
    create_project,
    delete_project,
    get_project,
    get_projects,
    update_project,
)
from repositories.screenshots import create_screenshot, list_screenshots
from repositories.ssh_connections import (
    delete_ssh_connection,
    get_ssh_connection,
    list_ssh_connections,
    save_ssh_connection,
    set_ssh_test_result,
    touch_ssh_connection,
    update_ssh_connection,
)
from repositories.settings import get_setting, set_setting
from repositories.system_snapshots import (
    get_system_snapshots,
    repository as system_snapshot_repository,
    save_system_snapshot,
)
from repositories.tasks import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task,
)
from repositories.tool_templates import (
    delete_template,
    get_template,
    list_templates,
    repository as tool_template_repository,
    save_template,
)
from repositories.workflows import (
    create_workflow,
    create_workflow_run,
    delete_workflow,
    finish_workflow_run,
    get_workflow,
    list_workflow_runs,
    list_workflows,
    update_workflow,
)


# ── Mémoires ──────────────────────────────────────────────────────────────────

# ── Tâches ────────────────────────────────────────────────────────────────────

# ── Notes ─────────────────────────────────────────────────────────────────────

# ── Agenda / Événements (store local) ───────────────────────────────────────────

# ── Paramètres ────────────────────────────────────────────────────────────────

# ── Projets ───────────────────────────────────────────────────────────────────
# Table normalement créée par lib/database/init.js (Next.js) au premier lancement du
# frontend — CREATE TABLE IF NOT EXISTS défensif ici aussi pour une install où le
# backend Python démarrerait avant le frontend (v2.107, même schéma que le JS).

# ── Captures d'écran (v2.175) ───────────────────────────────────────────────
# Persiste chaque capture attachée au chat (jusqu'ici jetée après un seul tour,
# cf. mémoire document-identity-toc-v2174) + son analyse (légende + texte relevé)
# pour permettre plus tard une génération de documentation à partir de plusieurs
# captures d'une même conversation.

# ── Logos générés (v2.183) ──────────────────────────────────────────────────
# Registre des logos générés localement (local_image.py) — permet de les RÉUTILISER
# pour un client/contexte déjà rencontré au lieu de regénérer à chaque document (né d'un
# vrai échec : Marvin n'avait aucun moyen de créer/retrouver un logo, cf. mémoire session).

# ── Historique d'exécution ────────────────────────────────────────────────────

# ── CRUD pour billing_clients ────────────────────────────────────────────────

# ── CRUD pour billing_quotes ─────────────────────────────────────────────────

# ── Catalogue de services ────────────────────────────────────────────────────

# ── Factures (facturation) ────────────────────────────────────────────────────

# ── Contrats récurrents (MRR/ARR) ─────────────────────────────────────────────

def _ensure_doc_tables(conn):
    """Tables pour l'agent IA de documentation technique."""
    # CMDB-lite : assets gérés (postes, serveurs, équipements réseau)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_assets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            asset_type TEXT NOT NULL DEFAULT 'workstation'
                CHECK(asset_type IN ('workstation','server','firewall','switch','router','printer','phone','nas','vm','other')),
            client_id TEXT,
            ip_address TEXT DEFAULT '',
            mac_address TEXT DEFAULT '',
            os TEXT DEFAULT '',
            specs TEXT DEFAULT '',
            location TEXT DEFAULT '',
            criticality TEXT NOT NULL DEFAULT 'medium'
                CHECK(criticality IN ('low','medium','high','critical')),
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Interventions : événements terrain (incidents, déploiements, maintenance)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_interventions (
            id TEXT PRIMARY KEY,
            number TEXT NOT NULL,
            title TEXT NOT NULL,
            intervention_type TEXT NOT NULL DEFAULT 'incident'
                CHECK(intervention_type IN ('incident','request','change','problem','deployment','maintenance','audit','other')),
            status TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open','in_progress','resolved','closed','cancelled')),
            priority TEXT NOT NULL DEFAULT 'medium'
                CHECK(priority IN ('low','medium','high','critical')),
            client_id TEXT,
            asset_ids TEXT DEFAULT '[]',
            technician TEXT DEFAULT '',
            started_at TEXT,
            resolved_at TEXT,
            duration_minutes INTEGER,
            -- Inputs (matières premières pour la documentation)
            raw_notes TEXT DEFAULT '',
            commands_executed TEXT DEFAULT '',
            ticket_refs TEXT DEFAULT '',
            client_emails TEXT DEFAULT '',
            network_config TEXT DEFAULT '',
            screenshots TEXT DEFAULT '[]',
            attachments TEXT DEFAULT '[]',
            -- Synthèse (générée ou rédigée)
            summary TEXT DEFAULT '',
            root_cause TEXT DEFAULT '',
            resolution TEXT DEFAULT '',
            recommendations TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            -- ITIL / Compliance
            itil_category TEXT DEFAULT '',
            rgpd_relevant INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Documents générés (PDF, DOCX, etc.) liés aux interventions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_documents (
            id TEXT PRIMARY KEY,
            intervention_id TEXT,
            client_id TEXT,
            doc_type TEXT NOT NULL
                CHECK(doc_type IN ('procedure','report','client_sheet','recovery_plan','maintenance','schema','runbook','knowledge_base','custom')),
            format TEXT NOT NULL DEFAULT 'pdf'
                CHECK(format IN ('pdf','docx','md','html','mermaid')),
            title TEXT NOT NULL,
            file_path TEXT,
            content_md TEXT DEFAULT '',
            template_used TEXT DEFAULT '',
            size_bytes INTEGER DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            tags TEXT DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Templates réutilisables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            description TEXT DEFAULT '',
            content_md TEXT NOT NULL,
            is_builtin INTEGER NOT NULL DEFAULT 0,
            usage_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_interv_client ON doc_interventions(client_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_interv_status ON doc_interventions(status, priority)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_interv ON doc_documents(intervention_id, doc_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_client ON doc_assets(client_id, asset_type)")

    # Seed default templates if empty
    count = conn.execute("SELECT COUNT(*) FROM doc_templates").fetchone()[0]
    if count == 0:
        _seed_doc_templates(conn)


def _seed_doc_templates(conn):
    """Templates IT professionnels par défaut."""
    import uuid as _u
    templates = [
        ("report",
         "Rapport d'intervention standard",
         "Compte rendu professionnel d'une intervention sur site ou à distance",
         """# Compte rendu d'intervention {{number}}

**Date :** {{date}}    **Technicien :** {{technician}}    **Durée :** {{duration}}

## Client
{{client_block}}

## Contexte
{{context}}

## Diagnostic
{{diagnostic}}

## Actions réalisées
{{actions}}

## Commandes exécutées
```
{{commands}}
```

## Résultat
{{resolution}}

## Recommandations
{{recommendations}}

---
*Rapport généré automatiquement par Marvin AI.*
"""),
        ("procedure",
         "Procédure technique pas-à-pas",
         "Procédure reproductible pour intervention type (déploiement, configuration…)",
         """# Procédure : {{title}}

**Version :** 1.0    **Date :** {{date}}    **Auteur :** {{technician}}    **Difficulté :** {{difficulty}}

## Objectif
{{objective}}

## Prérequis
{{prerequisites}}

## Matériel/Outils nécessaires
{{tools_required}}

## Procédure détaillée

{{steps}}

## Commandes
```
{{commands}}
```

## Vérification & validation
{{validation}}

## Retour arrière (rollback)
{{rollback}}

## Notes & pièges à éviter
{{notes}}

---
*Procédure documentée par Marvin AI.*
"""),
        ("client_sheet",
         "Fiche client (infrastructure)",
         "Synthèse complète de l'infrastructure d'un client",
         """# Fiche client : {{client_name}}

**Type :** {{client_type}}    **Contact principal :** {{contact}}    **Téléphone :** {{phone}}    **Email :** {{email}}

## Présentation
{{presentation}}

## Infrastructure

### Postes de travail
{{workstations}}

### Serveurs
{{servers}}

### Réseau
{{network}}

### Sécurité
{{security}}

### Sauvegarde
{{backup}}

## Contrats en cours
{{contracts}}

## Historique des interventions (12 derniers mois)
{{history}}

## Contacts techniques
{{contacts}}

---
*Fiche maintenue par Marvin AI. Dernière mise à jour : {{date}}.*
"""),
        ("recovery_plan",
         "Plan de reprise d'activité (PRA/PCA)",
         "Plan formel de continuité et reprise après sinistre",
         """# Plan de Reprise d'Activité — {{client_name}}

**Version :** 1.0    **Date :** {{date}}    **Validé par :** {{validator}}

## 1. Périmètre
{{scope}}

## 2. Analyse de risques
| Risque | Probabilité | Impact | Priorité |
|--------|-------------|--------|----------|
{{risks_table}}

## 3. Indicateurs de continuité

| Service | RTO (Recovery Time) | RPO (Recovery Point) |
|---------|---------------------|----------------------|
{{services_table}}

## 4. Architecture de sauvegarde
{{backup_arch}}

## 5. Procédure de reprise
{{recovery_steps}}

## 6. Tests réguliers
{{tests}}

## 7. Contacts d'urgence
{{contacts}}

## 8. Annexes
{{annexes}}

---
*PRA généré par Marvin AI conformément aux bonnes pratiques ISO 22301.*
"""),
        ("maintenance",
         "Procédure de maintenance préventive",
         "Checklist de maintenance régulière (mensuelle/trimestrielle/annuelle)",
         """# Procédure de maintenance préventive

**Périodicité :** {{frequency}}    **Client :** {{client_name}}    **Durée estimée :** {{duration}}

## Checklist

### 🖥️ Postes de travail
- [ ] Mises à jour Windows
- [ ] Mises à jour applicatives (navigateurs, Office, etc.)
- [ ] Analyse antivirus complète
- [ ] Nettoyage fichiers temporaires
- [ ] Vérification espace disque
- [ ] Tests de sauvegarde
{{workstation_extra}}

### 🖥️ Serveurs
- [ ] Mises à jour Windows Server / Linux
- [ ] Vérification logs système (erreurs critiques)
- [ ] Vérification état RAID / disques
- [ ] Vérification sauvegardes (intégrité + restauration)
- [ ] Vérification certificats SSL/TLS
- [ ] Mise à jour antivirus serveur
{{server_extra}}

### 🌐 Réseau
- [ ] État liens WAN/LAN
- [ ] Logs firewall (tentatives d'intrusion)
- [ ] Vérification Wi-Fi (puissance, perfs)
- [ ] Sauvegarde configuration équipements
{{network_extra}}

### 🔐 Sécurité
- [ ] Revue des accès utilisateurs
- [ ] Vérification politique mots de passe
- [ ] Test restauration sauvegarde
- [ ] Mises à jour antivirus
{{security_extra}}

## Anomalies détectées
{{anomalies}}

## Actions correctives recommandées
{{corrective_actions}}

---
*Maintenance documentée par Marvin AI.*
"""),
        ("runbook",
         "Runbook (procédure d'urgence)",
         "Procédure d'intervention rapide en cas d'incident critique",
         """# 🚨 RUNBOOK — {{title}}

**Sévérité :** {{severity}}    **Service impacté :** {{service}}    **Auteur :** {{technician}}

## ⚡ Symptômes
{{symptoms}}

## 🎯 Impact business
{{business_impact}}

## 🔍 Diagnostic rapide
{{diagnostic_steps}}

## 🛠️ Actions de remédiation

### Étape 1 — Mitigation immédiate
{{step1}}

### Étape 2 — Investigation
{{step2}}

### Étape 3 — Résolution
{{step3}}

### Étape 4 — Vérification
{{step4}}

## 📞 Escalade
- **Niveau 1 :** {{level1_contact}}
- **Niveau 2 :** {{level2_contact}}
- **Niveau 3 (urgence) :** {{level3_contact}}

## 📋 Post-mortem
À remplir après l'incident :
- Cause racine identifiée :
- Actions préventives à mettre en place :
- Documentation à mettre à jour :

---
*Runbook Marvin AI.*
"""),
        ("schema",
         "Schéma logique (Mermaid)",
         "Schéma d'architecture réseau ou logique en Mermaid",
         """```mermaid
graph TB
    subgraph "Internet"
        WAN[FAI / Internet]
    end
    subgraph "DMZ"
        FW[Firewall]
        WAN --> FW
    end
    subgraph "LAN"
        SW[Switch Principal]
        FW --> SW
        SV[Serveur AD/DC]
        SF[Serveur Fichiers]
        SW --> SV
        SW --> SF
    end
    subgraph "Postes"
        SW --> PC1[Poste 1]
        SW --> PC2[Poste 2]
        SW --> PCN[...Poste N]
    end
```
"""),
    ]
    for dtype, name, desc, content in templates:
        conn.execute("""
            INSERT INTO doc_templates (id, name, doc_type, description, content_md, is_builtin)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (str(_u.uuid4()), name, dtype, desc, content))


# ── CRUD interventions ──────────────────────────────────────────────────────

def doc_intervention_create(data: dict) -> dict:
    import uuid as _u, json as _j
    iid = str(_u.uuid4())
    with db() as conn:
        _ensure_doc_tables(conn)
        from datetime import datetime as _dt
        year = _dt.now().year
        count = conn.execute(
            "SELECT COUNT(*) FROM doc_interventions WHERE number LIKE ?",
            (f"INT-{year}-%",)
        ).fetchone()[0]
        number = data.get("number") or f"INT-{year}-{count+1:04d}"

        # Serialize JSON fields
        asset_ids = data.get("asset_ids", [])
        screenshots = data.get("screenshots", [])
        attachments = data.get("attachments", [])
        tags = data.get("tags", [])

        conn.execute("""
            INSERT INTO doc_interventions
            (id, number, title, intervention_type, status, priority, client_id, asset_ids,
             technician, started_at, resolved_at, duration_minutes,
             raw_notes, commands_executed, ticket_refs, client_emails, network_config,
             screenshots, attachments, summary, root_cause, resolution, recommendations,
             tags, itil_category, rgpd_relevant)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            iid, number,
            data.get("title", "Intervention sans titre"),
            data.get("intervention_type", "incident"),
            data.get("status", "open"),
            data.get("priority", "medium"),
            data.get("client_id"),
            _j.dumps(asset_ids if isinstance(asset_ids, list) else []),
            data.get("technician", ""),
            data.get("started_at"),
            data.get("resolved_at"),
            int(data.get("duration_minutes") or 0) if data.get("duration_minutes") else None,
            data.get("raw_notes", ""),
            data.get("commands_executed", ""),
            data.get("ticket_refs", ""),
            data.get("client_emails", ""),
            data.get("network_config", ""),
            _j.dumps(screenshots if isinstance(screenshots, list) else []),
            _j.dumps(attachments if isinstance(attachments, list) else []),
            data.get("summary", ""),
            data.get("root_cause", ""),
            data.get("resolution", ""),
            data.get("recommendations", ""),
            _j.dumps(tags if isinstance(tags, list) else []),
            data.get("itil_category", ""),
            1 if data.get("rgpd_relevant") else 0,
        ))
    return doc_intervention_get(iid)


def doc_intervention_get(iid: str) -> dict | None:
    import json as _j
    with db() as conn:
        _ensure_doc_tables(conn)
        row = conn.execute("SELECT * FROM doc_interventions WHERE id = ?", (iid,)).fetchone()
    if not row:
        return None
    d = row_to_dict(row)
    for field in ("asset_ids", "screenshots", "attachments", "tags"):
        try:
            d[field] = _j.loads(d.get(field) or "[]")
        except Exception:
            d[field] = []
    return d


def doc_intervention_list(client_id: str | None = None, status: str | None = None,
                            limit: int = 100) -> list[dict]:
    import json as _j
    with db() as conn:
        _ensure_doc_tables(conn)
        sql = "SELECT * FROM doc_interventions WHERE 1=1"
        params = []
        if client_id:
            sql += " AND client_id = ?"; params.append(client_id)
        if status:
            sql += " AND status = ?"; params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = row_to_dict(r)
        for field in ("asset_ids", "screenshots", "attachments", "tags"):
            try:
                d[field] = _j.loads(d.get(field) or "[]")
            except Exception:
                d[field] = []
        result.append(d)
    return result


def doc_intervention_update(iid: str, data: dict) -> dict | None:
    import json as _j
    cols, vals = [], []
    json_fields = {"asset_ids", "screenshots", "attachments", "tags"}
    for key in ("title","intervention_type","status","priority","client_id","technician",
                "started_at","resolved_at","duration_minutes","raw_notes","commands_executed",
                "ticket_refs","client_emails","network_config","summary","root_cause",
                "resolution","recommendations","itil_category","rgpd_relevant","number"):
        if key in data:
            cols.append(f"{key} = ?")
            v = data[key]
            if key == "rgpd_relevant":
                v = 1 if v else 0
            vals.append(v)
    for key in json_fields:
        if key in data:
            cols.append(f"{key} = ?")
            v = data[key]
            if isinstance(v, (list, dict)):
                v = _j.dumps(v, ensure_ascii=False)
            vals.append(v)
    if not cols:
        return doc_intervention_get(iid)
    vals.append(iid)
    with db() as conn:
        conn.execute(
            f"UPDATE doc_interventions SET {', '.join(cols)}, updated_at = datetime('now') WHERE id = ?",
            vals
        )
    return doc_intervention_get(iid)


def doc_intervention_delete(iid: str):
    with db() as conn:
        conn.execute("DELETE FROM doc_interventions WHERE id = ?", (iid,))
        conn.execute("DELETE FROM doc_documents WHERE intervention_id = ?", (iid,))


# ── CRUD documents générés ──────────────────────────────────────────────────

def doc_document_create(data: dict) -> dict:
    import uuid as _u, json as _j
    did = str(_u.uuid4())
    tags = data.get("tags", [])
    with db() as conn:
        _ensure_doc_tables(conn)
        conn.execute("""
            INSERT INTO doc_documents
            (id, intervention_id, client_id, doc_type, format, title,
             file_path, content_md, template_used, size_bytes, version, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            did, data.get("intervention_id"), data.get("client_id"),
            data.get("doc_type", "custom"),
            data.get("format", "pdf"),
            data.get("title", "Document"),
            data.get("file_path", ""),
            data.get("content_md", ""),
            data.get("template_used", ""),
            int(data.get("size_bytes") or 0),
            int(data.get("version") or 1),
            _j.dumps(tags if isinstance(tags, list) else [])
        ))
    with db() as conn:
        row = conn.execute("SELECT * FROM doc_documents WHERE id = ?", (did,)).fetchone()
    return row_to_dict(row)


def doc_document_list(intervention_id: str | None = None,
                       client_id: str | None = None,
                       doc_type: str | None = None) -> list[dict]:
    with db() as conn:
        _ensure_doc_tables(conn)
        sql = "SELECT * FROM doc_documents WHERE 1=1"
        params = []
        if intervention_id:
            sql += " AND intervention_id = ?"; params.append(intervention_id)
        if client_id:
            sql += " AND client_id = ?"; params.append(client_id)
        if doc_type:
            sql += " AND doc_type = ?"; params.append(doc_type)
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(r) for r in rows]


def doc_document_delete(did: str):
    with db() as conn:
        conn.execute("DELETE FROM doc_documents WHERE id = ?", (did,))


# ── Templates ───────────────────────────────────────────────────────────────

def doc_template_list(doc_type: str | None = None) -> list[dict]:
    with db() as conn:
        _ensure_doc_tables(conn)
        if doc_type:
            rows = conn.execute(
                "SELECT * FROM doc_templates WHERE doc_type = ? ORDER BY usage_count DESC",
                (doc_type,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM doc_templates ORDER BY doc_type, usage_count DESC"
            ).fetchall()
    return [row_to_dict(r) for r in rows]


def doc_template_get(tid: str) -> dict | None:
    with db() as conn:
        _ensure_doc_tables(conn)
        row = conn.execute("SELECT * FROM doc_templates WHERE id = ?", (tid,)).fetchone()
    return row_to_dict(row) if row else None


def doc_template_use(tid: str):
    with db() as conn:
        conn.execute("UPDATE doc_templates SET usage_count = usage_count + 1 WHERE id = ?", (tid,))


# ── Assets (CMDB-lite) ──────────────────────────────────────────────────────

def doc_asset_create(data: dict) -> dict:
    import uuid as _u
    aid = str(_u.uuid4())
    with db() as conn:
        _ensure_doc_tables(conn)
        conn.execute("""
            INSERT INTO doc_assets
            (id, name, asset_type, client_id, ip_address, mac_address, os, specs, location, criticality, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (aid,
              data.get("name", "Asset"),
              data.get("asset_type", "workstation"),
              data.get("client_id"),
              data.get("ip_address", ""),
              data.get("mac_address", ""),
              data.get("os", ""),
              data.get("specs", ""),
              data.get("location", ""),
              data.get("criticality", "medium"),
              data.get("notes", "")))
    with db() as conn:
        row = conn.execute("SELECT * FROM doc_assets WHERE id = ?", (aid,)).fetchone()
    return row_to_dict(row)


def doc_asset_list(client_id: str | None = None) -> list[dict]:
    with db() as conn:
        _ensure_doc_tables(conn)
        if client_id:
            rows = conn.execute(
                "SELECT * FROM doc_assets WHERE client_id = ? ORDER BY asset_type, name",
                (client_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM doc_assets ORDER BY asset_type, name"
            ).fetchall()
    return [row_to_dict(r) for r in rows]


def doc_asset_delete(aid: str):
    with db() as conn:
        conn.execute("DELETE FROM doc_assets WHERE id = ?", (aid,))


# ══════════════════════════════════════════════════════════════════════════════
# v2.30.0 — Operations Safety : Module 1 — Pre-Check / Post-Check
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# v2.30.0 — Operations Safety : Module 2 — Command Safety / Guardrails
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_cmd_safety_tables(conn):
    """Tables pour l'analyse de risque des commandes."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS command_reviews (
            id TEXT PRIMARY KEY,
            intervention_id TEXT,
            command TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'unknown'
                CHECK(platform IN ('powershell','cmd','bash','linux','proxmox','cisco','firewall','unknown')),
            risk_level TEXT NOT NULL DEFAULT 'safe'
                CHECK(risk_level IN ('safe','medium','high','critical','blocked')),
            risk_explanation TEXT DEFAULT '',
            safer_alternative TEXT DEFAULT '',
            requires_approval INTEGER NOT NULL DEFAULT 0,
            matched_rule TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS command_risk_rules (
            id TEXT PRIMARY KEY,
            pattern TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'unknown',
            risk_level TEXT NOT NULL DEFAULT 'medium',
            explanation TEXT DEFAULT '',
            safer_alternative TEXT DEFAULT '',
            is_builtin INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS approval_requests (
            id TEXT PRIMARY KEY,
            command_review_id TEXT,
            command TEXT NOT NULL,
            requested_by TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected')),
            approver TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            decided_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd_reviews_interv ON command_reviews(intervention_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd_reviews_risk ON command_reviews(risk_level)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status)")

    count = conn.execute("SELECT COUNT(*) FROM command_risk_rules").fetchone()[0]
    if count == 0:
        _seed_command_rules(conn)


def _seed_command_rules(conn):
    """Règles de risque par défaut (destructives = blocked/critical)."""
    import uuid as _u
    # (pattern_regex, platform, risk_level, explanation, safer_alternative)
    rules = [
        # ── BLOCKED (destructif irréversible) ──
        (r"rm\s+-rf\s+/\s*$|rm\s+-rf\s+/\s", "linux", "blocked",
         "Suppression récursive de la racine du système — destruction totale irréversible.",
         "Ciblez un sous-dossier précis : rm -rf /chemin/precis/. Vérifiez toujours le chemin avant."),
        (r"remove-item\s+.*-recurse\s+.*-force\s+.*c:\\?\s*$|remove-item\s+-recurse\s+-force\s+c:\\", "powershell", "blocked",
         "Suppression récursive forcée de C:\\ — destruction du système Windows.",
         "Ciblez un sous-dossier précis et retirez -Force tant que vous n'avez pas vérifié."),
        (r"diskpart.*\bclean\b", "cmd", "blocked",
         "diskpart clean efface la table de partition d'un disque — perte totale des données.",
         "Vérifiez le numéro de disque (list disk) et sauvegardez avant toute opération diskpart."),
        (r"^\s*format\b", "cmd", "blocked",
         "Formatage de volume — efface toutes les données du volume ciblé.",
         "Confirmez la lettre de lecteur et faites une sauvegarde complète au préalable."),
        (r"del\s+/s\s+/q\s+c:\\?|del\s+/s\s+/q\s+c:", "cmd", "blocked",
         "Suppression silencieuse récursive de C:\\ — destruction massive de fichiers système.",
         "Ciblez un dossier précis et retirez /q pour confirmer chaque suppression."),
        (r"pveceph\s+purge", "proxmox", "blocked",
         "pveceph purge détruit toute la configuration Ceph du cluster Proxmox.",
         "Sauvegardez la config et vérifiez l'impact sur le stockage avant. Opération de dernier recours."),
        (r"\bqm\s+destroy\b", "proxmox", "critical",
         "qm destroy supprime définitivement une VM et ses disques.",
         "Faites un snapshot/backup (vzdump) de la VM avant. Vérifiez le VMID."),
        (r"iptables\s+-F", "linux", "critical",
         "iptables -F vide toutes les règles de pare-feu — expose le système.",
         "Sauvegardez d'abord : iptables-save > rules.bak. Travaillez chaîne par chaîne."),
        (r"netsh\s+advfirewall\s+set\s+allprofiles\s+state\s+off", "powershell", "critical",
         "Désactive complètement le pare-feu Windows sur tous les profils — risque sécurité majeur.",
         "Ajoutez une règle ciblée plutôt que de désactiver le pare-feu entier."),

        # ── CRITICAL (destructif ciblé) ──
        (r"\bdd\s+if=.*of=/dev/", "linux", "critical",
         "dd vers un périphérique bloc peut écraser un disque entier.",
         "Vérifiez of= (lsblk) et ajoutez status=progress. Double-vérifiez la cible."),
        (r"mkfs\.\w+\s+/dev/", "linux", "critical",
         "mkfs formate une partition — perte des données existantes.",
         "Vérifiez la partition cible avec lsblk et sauvegardez avant."),
        (r"drop\s+(database|table)\b", "linux", "critical",
         "DROP DATABASE/TABLE supprime définitivement des données.",
         "Faites un dump SQL avant : mysqldump/pg_dump. Utilisez une transaction si possible."),
        (r"shutdown\s+(-h|/s|now)|halt\b|poweroff\b", "linux", "high",
         "Arrêt du système — coupe les services en production.",
         "Prévenez les utilisateurs et planifiez une fenêtre de maintenance."),
        (r"reboot\b|shutdown\s+/r|restart-computer", "powershell", "high",
         "Redémarrage du système — interruption de service.",
         "Vérifiez qu'aucune tâche critique ne tourne et prévenez les utilisateurs."),
        (r"copy-item\s+.*c:\\windows|move-item\s+.*c:\\windows", "powershell", "high",
         "Modification de fichiers système Windows.",
         "Sauvegardez le fichier original et testez en environnement de test."),
        (r"reg\s+delete|remove-itemproperty.*hklm", "powershell", "high",
         "Suppression de clés de registre — peut casser des fonctionnalités Windows.",
         "Exportez la clé avant : reg export. Créez un point de restauration."),
        (r"set-executionpolicy\s+unrestricted|set-executionpolicy\s+bypass", "powershell", "high",
         "Désactive la protection d'exécution de scripts PowerShell.",
         "Préférez -Scope Process et RemoteSigned plutôt que Unrestricted global."),
        (r"chmod\s+777", "linux", "high",
         "chmod 777 donne tous les droits à tout le monde — faille de sécurité.",
         "Utilisez des permissions minimales : 644 (fichiers) / 755 (dossiers)."),
        (r"\bkill\s+-9\b|stop-process\s+.*-force", "linux", "medium",
         "Arrêt forcé d'un processus — risque de corruption de données non sauvegardées.",
         "Essayez d'abord un arrêt propre (kill -15 / Stop-Process sans -Force)."),
        (r"net\s+user\s+\w+\s+/delete|remove-localuser", "powershell", "high",
         "Suppression d'un compte utilisateur.",
         "Désactivez le compte plutôt que de le supprimer : net user X /active:no."),

        # ── CISCO / FIREWALL ──
        (r"\bno\s+shutdown\b|\bshutdown\b", "cisco", "medium",
         "Active/désactive une interface réseau Cisco — impact connectivité.",
         "Vérifiez l'interface (show ip int brief) et planifiez le changement."),
        (r"erase\s+startup-config|write\s+erase", "cisco", "critical",
         "Efface la configuration de démarrage de l'équipement Cisco.",
         "Sauvegardez : copy running-config tftp. Confirmez avant."),
        (r"clear\s+configure\s+all", "firewall", "critical",
         "Efface toute la configuration du firewall.",
         "Exportez la config et planifiez une fenêtre de maintenance."),

        # ── MEDIUM (à surveiller) ──
        (r"\bgpupdate\s+/force", "powershell", "medium",
         "Force la mise à jour des stratégies de groupe — peut appliquer des changements immédiats.",
         "Vérifiez les GPO modifiées avant d'appliquer en masse."),
        (r"restart-service|stop-service", "powershell", "medium",
         "Arrêt/redémarrage d'un service — interruption temporaire.",
         "Vérifiez les dépendances du service et l'impact métier."),
    ]
    for pat, plat, risk, expl, alt in rules:
        conn.execute("""
            INSERT INTO command_risk_rules (id, pattern, platform, risk_level, explanation, safer_alternative, is_builtin)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (str(_u.uuid4()), pat, plat, risk, expl, alt))


def cmd_rules_list(active_only: bool = True) -> list[dict]:
    with db() as conn:
        _ensure_cmd_safety_tables(conn)
        if active_only:
            rows = conn.execute("SELECT * FROM command_risk_rules WHERE active = 1").fetchall()
        else:
            rows = conn.execute("SELECT * FROM command_risk_rules").fetchall()
    return [row_to_dict(r) for r in rows]


def cmd_review_create(data: dict) -> dict:
    import uuid as _u
    rid = str(_u.uuid4())
    with db() as conn:
        _ensure_cmd_safety_tables(conn)
        conn.execute("""
            INSERT INTO command_reviews
            (id, intervention_id, command, platform, risk_level, risk_explanation,
             safer_alternative, requires_approval, matched_rule)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (rid, data.get("intervention_id"), data.get("command", ""),
              data.get("platform", "unknown"), data.get("risk_level", "safe"),
              data.get("risk_explanation", ""), data.get("safer_alternative", ""),
              1 if data.get("requires_approval") else 0, data.get("matched_rule", "")))
        row = conn.execute("SELECT * FROM command_reviews WHERE id = ?", (rid,)).fetchone()
    return row_to_dict(row)


def cmd_review_list(intervention_id: str | None = None, risk_level: str | None = None,
                     limit: int = 100) -> list[dict]:
    with db() as conn:
        _ensure_cmd_safety_tables(conn)
        sql = "SELECT * FROM command_reviews WHERE 1=1"
        params = []
        if intervention_id:
            sql += " AND intervention_id = ?"; params.append(intervention_id)
        if risk_level:
            sql += " AND risk_level = ?"; params.append(risk_level)
        sql += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(r) for r in rows]


def approval_create(data: dict) -> dict:
    import uuid as _u
    aid = str(_u.uuid4())
    with db() as conn:
        _ensure_cmd_safety_tables(conn)
        conn.execute("""
            INSERT INTO approval_requests (id, command_review_id, command, requested_by, status, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (aid, data.get("command_review_id"), data.get("command", ""),
              data.get("requested_by", ""), data.get("status", "pending"),
              data.get("reason", "")))
        row = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (aid,)).fetchone()
    return row_to_dict(row)


def approval_list(status: str | None = None) -> list[dict]:
    with db() as conn:
        _ensure_cmd_safety_tables(conn)
        if status:
            rows = conn.execute(
                "SELECT * FROM approval_requests WHERE status = ? ORDER BY created_at DESC",
                (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM approval_requests ORDER BY created_at DESC").fetchall()
    return [row_to_dict(r) for r in rows]


def approval_decide(aid: str, status: str, approver: str = "", reason: str = "") -> dict | None:
    with db() as conn:
        _ensure_cmd_safety_tables(conn)
        conn.execute("""
            UPDATE approval_requests SET status = ?, approver = ?, reason = ?, decided_at = datetime('now')
            WHERE id = ?
        """, (status, approver, reason, aid))
        row = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (aid,)).fetchone()
    return row_to_dict(row) if row else None


# ══════════════════════════════════════════════════════════════════════════════
# v2.30.0 — Operations Safety : Module 3 — Client Health Score
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_health_tables(conn):
    """Tables pour le score de santé opérationnelle client."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS client_health_scores (
            id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            backup_score REAL NOT NULL DEFAULT 0,
            security_score REAL NOT NULL DEFAULT 0,
            documentation_score REAL NOT NULL DEFAULT 0,
            infrastructure_score REAL NOT NULL DEFAULT 0,
            incident_score REAL NOT NULL DEFAULT 0,
            global_score REAL NOT NULL DEFAULT 0,
            risk_level TEXT NOT NULL DEFAULT 'medium'
                CHECK(risk_level IN ('low','medium','high','critical')),
            computed_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS client_health_items (
            id TEXT PRIMARY KEY,
            score_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            category TEXT NOT NULL,
            label TEXT NOT NULL,
            points REAL NOT NULL DEFAULT 0,
            max_points REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ok',
            detail TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS client_recommendations (
            id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            score_id TEXT,
            priority TEXT NOT NULL DEFAULT 'medium'
                CHECK(priority IN ('low','medium','high','critical')),
            category TEXT DEFAULT 'general',
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open','done','dismissed')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_health_client ON client_health_scores(client_id, computed_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_health_items_score ON client_health_items(score_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reco_client ON client_recommendations(client_id, status)")


def health_score_create(data: dict, items: list = None, recommendations: list = None) -> dict:
    import uuid as _u
    sid = str(_u.uuid4())
    with db() as conn:
        _ensure_health_tables(conn)
        conn.execute("""
            INSERT INTO client_health_scores
            (id, client_id, backup_score, security_score, documentation_score,
             infrastructure_score, incident_score, global_score, risk_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (sid, data["client_id"], data.get("backup_score", 0), data.get("security_score", 0),
              data.get("documentation_score", 0), data.get("infrastructure_score", 0),
              data.get("incident_score", 0), data.get("global_score", 0),
              data.get("risk_level", "medium")))
        for it in (items or []):
            conn.execute("""
                INSERT INTO client_health_items (id, score_id, client_id, category, label, points, max_points, status, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (str(_u.uuid4()), sid, data["client_id"], it.get("category", "general"),
                  it.get("label", ""), it.get("points", 0), it.get("max_points", 0),
                  it.get("status", "ok"), it.get("detail", "")))
        for rec in (recommendations or []):
            conn.execute("""
                INSERT INTO client_recommendations (id, client_id, score_id, priority, category, title, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(_u.uuid4()), data["client_id"], sid, rec.get("priority", "medium"),
                  rec.get("category", "general"), rec.get("title", ""), rec.get("description", "")))
    return health_score_get(sid)


def health_score_get(sid: str) -> dict | None:
    with db() as conn:
        _ensure_health_tables(conn)
        row = conn.execute("SELECT * FROM client_health_scores WHERE id = ?", (sid,)).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        items = conn.execute("SELECT * FROM client_health_items WHERE score_id = ?", (sid,)).fetchall()
        recos = conn.execute("SELECT * FROM client_recommendations WHERE score_id = ?", (sid,)).fetchall()
    d["items"] = [row_to_dict(r) for r in items]
    d["recommendations"] = [row_to_dict(r) for r in recos]
    return d


def health_score_latest(client_id: str) -> dict | None:
    with db() as conn:
        _ensure_health_tables(conn)
        row = conn.execute(
            "SELECT id FROM client_health_scores WHERE client_id = ? ORDER BY computed_at DESC LIMIT 1",
            (client_id,)).fetchone()
    return health_score_get(row["id"]) if row else None


def health_score_history(client_id: str, limit: int = 12) -> list[dict]:
    with db() as conn:
        _ensure_health_tables(conn)
        rows = conn.execute(
            "SELECT * FROM client_health_scores WHERE client_id = ? ORDER BY computed_at DESC LIMIT ?",
            (client_id, limit)).fetchall()
    return [row_to_dict(r) for r in rows]


def health_recommendations_list(client_id: str, status: str | None = None) -> list[dict]:
    with db() as conn:
        _ensure_health_tables(conn)
        sql = "SELECT * FROM client_recommendations WHERE client_id = ?"
        params = [client_id]
        if status:
            sql += " AND status = ?"; params.append(status)
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# Base de connaissances IT consultable par Marvin (outils/logiciels/produits)
# Permet des recommandations instantanées sans recherche web → plus rapide & smart.
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_it_kb_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS it_knowledge (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            vendor TEXT DEFAULT '',
            description TEXT DEFAULT '',
            use_cases TEXT DEFAULT '',
            pros TEXT DEFAULT '',
            cons TEXT DEFAULT '',
            pricing_model TEXT DEFAULT 'paid'
                CHECK(pricing_model IN ('opensource','free','freemium','paid','saas','unknown')),
            typical_price TEXT DEFAULT '',
            platforms TEXT DEFAULT '',
            alternatives TEXT DEFAULT '',
            official_url TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            rating REAL DEFAULT 0,
            best_for TEXT DEFAULT '',
            source TEXT DEFAULT 'curated',
            times_used INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_itkb_cat ON it_knowledge(category, name)")
    if conn.execute("SELECT COUNT(*) FROM it_knowledge").fetchone()[0] == 0:
        _seed_it_kb(conn)


def _seed_it_kb(conn):
    import uuid as _u
    # (name, category, vendor, description, use_cases, pricing_model, typical_price, platforms, best_for, tags)
    items = [
        # Sauvegarde
        ("Veeam Backup & Replication", "Sauvegarde", "Veeam", "Sauvegarde et réplication VM/physique, référence du marché.", "Sauvegarde serveurs, VM, restauration granulaire, PRA", "paid", "~ selon sockets/instances", "Windows,Linux", "Sauvegarde infra virtualisée (VMware/Hyper-V)", "backup,vm,pra,réplication"),
        ("Acronis Cyber Protect", "Sauvegarde", "Acronis", "Sauvegarde + cybersécurité intégrée (anti-ransomware).", "Image disque, cloud backup, EDR léger", "saas", "~6-12€/poste/mois", "Windows,macOS,Linux,Mobile", "TPE/PME tout-en-un sauvegarde+sécurité", "backup,image,ransomware,cloud"),
        ("Nakivo Backup & Replication", "Sauvegarde", "Nakivo", "Sauvegarde VM abordable, bon rapport qualité/prix.", "Sauvegarde VMware/Hyper-V/NAS", "paid", "abordable", "Linux,NAS", "PME budget serré, sauvegarde VM", "backup,vm,nas"),
        ("Duplicati", "Sauvegarde", "Open source", "Sauvegarde chiffrée vers cloud, gratuit.", "Sauvegarde fichiers vers S3/Backblaze/Drive", "opensource", "gratuit", "Windows,macOS,Linux", "Sauvegarde fichiers chiffrée petit budget", "backup,gratuit,cloud,chiffré"),
        # Antivirus / EDR
        ("Bitdefender GravityZone", "Cybersécurité", "Bitdefender", "EDR/antivirus pro, excellent taux de détection.", "Protection postes/serveurs, EDR, console centrale", "saas", "~4-8€/poste/mois", "Windows,macOS,Linux", "Protection PME/collectivité, console centralisée", "edr,antivirus,endpoint"),
        ("ESET PROTECT", "Cybersécurité", "ESET", "Antivirus léger et fiable, console cloud.", "Protection endpoints, faible impact perf", "saas", "~3-6€/poste/mois", "Windows,macOS,Linux,Android", "Parc avec machines anciennes (léger)", "antivirus,endpoint,léger"),
        ("Microsoft Defender for Business", "Cybersécurité", "Microsoft", "EDR intégré à Microsoft 365 Business Premium.", "Protection endpoints intégrée M365", "saas", "inclus M365 BP", "Windows,macOS", "Clients déjà sur Microsoft 365", "edr,microsoft,m365"),
        ("Malwarebytes", "Cybersécurité", "Malwarebytes", "Désinfection et anti-malware complémentaire.", "Nettoyage d'infection, second avis", "freemium", "gratuit/~3€", "Windows,macOS", "Désinfection ponctuelle d'un poste", "antimalware,nettoyage"),
        # Accès distant
        ("AnyDesk", "Accès distant", "AnyDesk", "Prise en main à distance rapide et fluide.", "Support à distance, télétravail", "freemium", "~15-30€/mois", "Windows,macOS,Linux,Mobile", "Support à distance pro abordable", "remote,support,télétravail"),
        ("TeamViewer", "Accès distant", "TeamViewer", "Référence de la prise en main à distance.", "Support, réunion, accès non surveillé", "freemium", "~25-50€/mois", "Tous", "Support multi-plateforme établi", "remote,support"),
        ("RustDesk", "Accès distant", "Open source", "Alternative open source auto-hébergeable à TeamViewer.", "Support à distance auto-hébergé, RGPD-friendly", "opensource", "gratuit", "Windows,macOS,Linux,Mobile", "Accès distant souverain/auto-hébergé", "remote,gratuit,souverain,rgpd"),
        # Supervision / RMM
        ("NinjaOne", "Supervision", "NinjaOne", "RMM moderne : supervision + gestion de parc + patch.", "MSP, supervision, déploiement patchs", "saas", "~2-3€/endpoint/mois", "Cloud", "MSP/infogérance moderne", "rmm,supervision,msp,patch"),
        ("Atera", "Supervision", "Atera", "RMM+PSA tout-en-un, tarif par technicien.", "Supervision, ticketing, facturation MSP", "saas", "~99€/technicien/mois", "Cloud", "Petit MSP (tarif par tech illimité endpoints)", "rmm,psa,msp"),
        ("Zabbix", "Supervision", "Open source", "Supervision réseau/serveurs open source puissante.", "Monitoring infra, alertes, graphes", "opensource", "gratuit", "Linux", "Supervision auto-hébergée sans licence", "monitoring,gratuit,réseau"),
        ("PRTG Network Monitor", "Supervision", "Paessler", "Supervision réseau par capteurs, simple.", "Monitoring réseau, bande passante, SNMP", "freemium", "gratuit <100 capteurs", "Windows", "Supervision réseau PME clé en main", "monitoring,réseau,snmp"),
        # Virtualisation
        ("Proxmox VE", "Virtualisation", "Proxmox", "Hyperviseur open source (KVM+LXC) avec cluster/HA.", "Virtualisation serveurs, conteneurs, HA", "opensource", "gratuit (support payant)", "Linux", "Virtualisation sans coût de licence", "virtualisation,kvm,gratuit,ha"),
        ("VMware vSphere/ESXi", "Virtualisation", "Broadcom", "Hyperviseur entreprise de référence.", "Virtualisation critique, vMotion, HA", "paid", "licence élevée", "Bare-metal", "Infra critique avec besoin support éditeur", "virtualisation,vmware,entreprise"),
        ("Hyper-V", "Virtualisation", "Microsoft", "Hyperviseur intégré à Windows Server.", "Virtualisation en environnement Windows", "free", "inclus Windows Server", "Windows", "Parc 100% Microsoft", "virtualisation,microsoft,windows"),
        # Pare-feu / réseau
        ("pfSense", "Réseau & Sécurité", "Netgate", "Pare-feu/routeur open source complet.", "Pare-feu, VPN, filtrage, routeur", "opensource", "gratuit", "x86/Appliance", "Pare-feu robuste petit budget", "firewall,vpn,routeur,gratuit"),
        ("OPNsense", "Réseau & Sécurité", "Open source", "Fork de pfSense, interface moderne.", "Pare-feu, IDS/IPS, VPN", "opensource", "gratuit", "x86/Appliance", "Pare-feu open source moderne", "firewall,ids,vpn,gratuit"),
        ("Stormshield", "Réseau & Sécurité", "Stormshield", "UTM/pare-feu français certifié ANSSI.", "Sécurité périmétrique, conformité FR", "paid", "selon modèle", "Appliance", "Collectivité/secteur sensible (souveraineté)", "firewall,utm,anssi,souverain"),
        ("Fortinet FortiGate", "Réseau & Sécurité", "Fortinet", "NGFW performant, large écosystème.", "Pare-feu nouvelle génération, SD-WAN", "paid", "selon modèle", "Appliance", "PME/ETI besoin NGFW + SD-WAN", "firewall,ngfw,sdwan"),
        # Diagnostic / utilitaires
        ("Wireshark", "Diagnostic", "Open source", "Analyseur de paquets réseau de référence.", "Diagnostic réseau, capture trames", "opensource", "gratuit", "Windows,macOS,Linux", "Diagnostic réseau approfondi", "réseau,capture,diagnostic,gratuit"),
        ("Advanced IP Scanner", "Diagnostic", "Famatech", "Scan réseau local rapide et gratuit.", "Inventaire réseau, découverte d'hôtes", "free", "gratuit", "Windows", "Cartographie rapide d'un LAN", "réseau,scan,inventaire,gratuit"),
        ("CrystalDiskInfo", "Diagnostic", "Crystal Dew World", "Santé des disques (SMART).", "Diagnostic disque, prévention de panne", "opensource", "gratuit", "Windows", "Vérifier l'état d'un disque avant panne", "disque,smart,diagnostic,gratuit"),
        ("HWiNFO", "Diagnostic", "HWiNFO", "Infos matériel et capteurs détaillés.", "Diagnostic matériel, monitoring températures", "freemium", "gratuit", "Windows", "Diagnostic matériel complet", "matériel,capteurs,diagnostic"),
        ("MemTest86", "Diagnostic", "PassMark", "Test de mémoire RAM bootable.", "Détection de RAM défectueuse", "freemium", "gratuit", "Bootable", "Tester une RAM suspecte", "ram,mémoire,test,gratuit"),
        # Imagerie / déploiement
        ("Clonezilla", "Déploiement", "Open source", "Clonage/imagerie disque gratuit.", "Image système, déploiement de masse", "opensource", "gratuit", "Bootable", "Cloner/déployer des postes sans coût", "image,clonage,déploiement,gratuit"),
        ("Macrium Reflect", "Déploiement", "Macrium", "Imagerie disque fiable Windows.", "Image système, restauration, migration SSD", "freemium", "~70€", "Windows", "Migration SSD / image de référence", "image,backup,ssd,windows"),
        # Mots de passe / identité
        ("Bitwarden", "Gestion identité", "Bitwarden", "Gestionnaire de mots de passe open source.", "Coffre-fort partagé équipe, auto-hébergeable", "freemium", "gratuit/~3€/mois", "Tous", "Mots de passe d'équipe sécurisés", "motdepasse,coffre,gratuit,rgpd"),
        ("KeePass", "Gestion identité", "Open source", "Coffre-fort de mots de passe local.", "Stockage local chiffré des secrets", "opensource", "gratuit", "Windows,Mobile", "Secrets en local sans cloud", "motdepasse,local,gratuit"),
        # Productivité / cloud
        ("Microsoft 365", "Cloud & Productivité", "Microsoft", "Suite bureautique + mail + Teams + OneDrive.", "Messagerie pro, collaboration, fichiers cloud", "saas", "~6-22€/user/mois", "Cloud", "Bureautique/collaboration standard du marché", "m365,mail,cloud,collaboration"),
        ("Google Workspace", "Cloud & Productivité", "Google", "Suite collaborative cloud (Gmail, Drive, Meet).", "Mail pro, collaboration temps réel", "saas", "~6-18€/user/mois", "Cloud", "Structures cloud-first / collaboration", "google,mail,cloud"),
        # Réseau scan
        ("Nmap", "Diagnostic", "Open source", "Scanner de ports et d'audit réseau.", "Audit réseau, découverte services/ports", "opensource", "gratuit", "Windows,Linux,macOS", "Audit de sécurité réseau", "réseau,ports,audit,gratuit"),
    ]
    for it in items:
        name, cat, vendor, desc, uc, pm, price, plat, best, tags = it
        conn.execute("""
            INSERT INTO it_knowledge
            (id, name, category, vendor, description, use_cases, pricing_model,
             typical_price, platforms, best_for, tags, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?, 'curated')
        """, (str(_u.uuid4()), name, cat, vendor, desc, uc, pm, price, plat, best, tags))


def it_kb_list(category: str | None = None, limit: int = 200) -> list[dict]:
    with db() as conn:
        _ensure_it_kb_tables(conn)
        if category:
            rows = conn.execute("SELECT * FROM it_knowledge WHERE category = ? ORDER BY name LIMIT ?",
                                (category, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM it_knowledge ORDER BY category, name LIMIT ?", (limit,)).fetchall()
    return [row_to_dict(r) for r in rows]


def it_kb_categories() -> list[str]:
    with db() as conn:
        _ensure_it_kb_tables(conn)
        rows = conn.execute("SELECT DISTINCT category FROM it_knowledge ORDER BY category").fetchall()
    return [r[0] for r in rows]


def it_kb_search(query: str, limit: int = 12) -> list[dict]:
    """Recherche plein-texte simple sur nom/catégorie/usage/tags/best_for."""
    q = f"%{(query or '').strip().lower()}%"
    with db() as conn:
        _ensure_it_kb_tables(conn)
        rows = conn.execute("""
            SELECT * FROM it_knowledge
            WHERE lower(name) LIKE ? OR lower(category) LIKE ? OR lower(use_cases) LIKE ?
               OR lower(tags) LIKE ? OR lower(best_for) LIKE ? OR lower(description) LIKE ?
               OR lower(vendor) LIKE ?
            ORDER BY times_used DESC, name LIMIT ?
        """, (q, q, q, q, q, q, q, limit)).fetchall()
    return [row_to_dict(r) for r in rows]


def it_kb_get(name_or_id: str) -> dict | None:
    with db() as conn:
        _ensure_it_kb_tables(conn)
        row = conn.execute("SELECT * FROM it_knowledge WHERE id = ? OR lower(name) = ?",
                           (name_or_id, (name_or_id or "").strip().lower())).fetchone()
    return row_to_dict(row) if row else None


def it_kb_upsert(data: dict) -> dict:
    import uuid as _u
    name = data["name"].strip()
    with db() as conn:
        _ensure_it_kb_tables(conn)
        existing = conn.execute("SELECT id FROM it_knowledge WHERE lower(name) = ?",
                                (name.lower(),)).fetchone()
        fields = ("category", "vendor", "description", "use_cases", "pros", "cons",
                  "pricing_model", "typical_price", "platforms", "alternatives",
                  "official_url", "tags", "rating", "best_for", "source")
        if existing:
            eid = existing[0]
            cols, vals = [], []
            for f in fields:
                if f in data and data[f] not in (None, ""):
                    cols.append(f"{f} = ?"); vals.append(data[f])
            if cols:
                vals.append(eid)
                conn.execute(f"UPDATE it_knowledge SET {', '.join(cols)}, updated_at = datetime('now') WHERE id = ?", vals)
            kid = eid
        else:
            kid = str(_u.uuid4())
            conn.execute("""
                INSERT INTO it_knowledge (id, name, category, vendor, description, use_cases,
                    pros, cons, pricing_model, typical_price, platforms, alternatives,
                    official_url, tags, rating, best_for, source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (kid, name, data.get("category", "Autre"), data.get("vendor", ""),
                  data.get("description", ""), data.get("use_cases", ""), data.get("pros", ""),
                  data.get("cons", ""), data.get("pricing_model", "unknown"),
                  data.get("typical_price", ""), data.get("platforms", ""),
                  data.get("alternatives", ""), data.get("official_url", ""),
                  data.get("tags", ""), float(data.get("rating", 0) or 0),
                  data.get("best_for", ""), data.get("source", "learned")))
    return it_kb_get(kid)


def it_kb_increment_usage(name_or_id: str):
    with db() as conn:
        _ensure_it_kb_tables(conn)
        conn.execute("UPDATE it_knowledge SET times_used = times_used + 1 WHERE id = ? OR lower(name) = ?",
                     (name_or_id, (name_or_id or "").strip().lower()))


def _init_tables():
    with db() as conn:
        execution_repository.ensure_schema(conn)
        system_snapshot_repository.ensure_schema(conn)
        tool_template_repository.ensure_schema(conn)
        cron_job_repository.ensure_schema(conn)
        network_inventory_repository.ensure_schema(conn)
        billing_repository.ensure_schema(conn)
        _ensure_doc_tables(conn)
        operations_repository.ensure_schema(conn)
        _ensure_cmd_safety_tables(conn)
        _ensure_health_tables(conn)
        _ensure_it_kb_tables(conn)
        event_repository.ensure_schema(conn)
        # La baseline est enregistree seulement apres la reussite de tous les
        # initialiseurs historiques. Les prochains changements de schema seront
        # portes par db_migrations.py sans retirer les garde-fous existants.
        apply_migrations(conn)

_init_tables()


# ── Inventaire réseau persistant (v2.139 — mini-CMDB) ──────────────────────────
# Chaque scan (`net_inventory_scan`) était jusqu'ici un instantané jetable — aucune mémoire
# des appareils déjà vus. Cette table transforme un scan ponctuel en inventaire consultable
# (nom personnalisé, notes, première/dernière apparition) — pattern des outils pro (Atera...).

# ── Snapshots système (v2.138 — suivi de tendance, pas juste l'instantané) ────────

# ── Templates d'outils ────────────────────────────────────────────────────────

# ── Jobs cron ─────────────────────────────────────────────────────────────────

# ── Fiches de révision / quiz (v2.155) ──────────────────────────────────────────
# Répétition espacée minimale (façon Leitner à 2 leviers) : bonne réponse → l'intervalle
# double (plafonné), mauvaise réponse → repasse le lendemain. Pas un moteur SM-2 complet
# (courbes d'oubli, facteur de facilité par carte) — volontairement simple, cohérent avec
# le reste de Marvin (pas de sur-ingénierie pour un besoin d'étude personnelle).

def _ensure_flashcards_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flashcards (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            choices TEXT DEFAULT '[]',
            interval_days INTEGER NOT NULL DEFAULT 1,
            due_at TEXT NOT NULL DEFAULT (datetime('now')),
            correct_count INTEGER NOT NULL DEFAULT 0,
            wrong_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_due ON flashcards(due_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_topic ON flashcards(topic)")


def _parse_flashcard(row: dict | None) -> dict | None:
    if row is None:
        return None
    if row.get("choices") and isinstance(row["choices"], str):
        try:
            row["choices"] = json.loads(row["choices"])
        except Exception:
            row["choices"] = []
    return row


def create_flashcard(topic: str, question: str, answer: str, choices: list | None = None) -> dict:
    fid = str(uuid.uuid4())
    with db() as conn:
        _ensure_flashcards_table(conn)
        conn.execute(
            "INSERT INTO flashcards (id, topic, question, answer, choices) VALUES (?,?,?,?,?)",
            (fid, topic, question, answer, json.dumps(choices or []))
        )
        row = conn.execute("SELECT * FROM flashcards WHERE id=?", (fid,)).fetchone()
    return _parse_flashcard(row_to_dict(row))


def get_next_flashcard(topic: str | None = None) -> dict | None:
    """Carte due en priorité (due_at <= maintenant, la plus ancienne d'abord) ; à défaut,
    une carte au hasard du topic pour continuer à s'entraîner même sans rien "en retard"."""
    with db() as conn:
        _ensure_flashcards_table(conn)
        params: list = []
        where = "WHERE due_at <= datetime('now')"
        if topic:
            where += " AND topic = ?"
            params.append(topic)
        row = conn.execute(
            f"SELECT * FROM flashcards {where} ORDER BY due_at ASC LIMIT 1", params
        ).fetchone()
        if not row:
            where2 = "WHERE topic = ?" if topic else ""
            params2 = [topic] if topic else []
            row = conn.execute(
                f"SELECT * FROM flashcards {where2} ORDER BY RANDOM() LIMIT 1", params2
            ).fetchone()
    return _parse_flashcard(row_to_dict(row))


def answer_flashcard(fid: str, correct: bool) -> dict | None:
    with db() as conn:
        _ensure_flashcards_table(conn)
        row = conn.execute("SELECT * FROM flashcards WHERE id=?", (fid,)).fetchone()
        if not row:
            return None
        card = row_to_dict(row)
        if correct:
            interval = min(card["interval_days"] * 2, 60)
            conn.execute(
                "UPDATE flashcards SET interval_days=?, due_at=datetime('now', ?), correct_count=correct_count+1 WHERE id=?",
                (interval, f"+{interval} days", fid)
            )
        else:
            conn.execute(
                "UPDATE flashcards SET interval_days=1, due_at=datetime('now', '+1 days'), wrong_count=wrong_count+1 WHERE id=?",
                (fid,)
            )
        updated = conn.execute("SELECT * FROM flashcards WHERE id=?", (fid,)).fetchone()
    return _parse_flashcard(row_to_dict(updated))


def flashcard_stats() -> list[dict]:
    with db() as conn:
        _ensure_flashcards_table(conn)
        rows = conn.execute("""
            SELECT topic, COUNT(*) as total,
                   SUM(CASE WHEN due_at <= datetime('now') THEN 1 ELSE 0 END) as due_now,
                   SUM(correct_count) as correct_total, SUM(wrong_count) as wrong_total
            FROM flashcards GROUP BY topic ORDER BY topic
        """).fetchall()
    return [row_to_dict(r) for r in rows]


def delete_flashcards_by_topic(topic: str) -> int:
    with db() as conn:
        _ensure_flashcards_table(conn)
        cur = conn.execute("DELETE FROM flashcards WHERE topic=?", (topic,))
    return cur.rowcount
