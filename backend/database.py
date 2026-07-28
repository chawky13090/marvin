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
from repositories.client_health import (
    health_recommendations_list,
    health_score_create,
    health_score_get,
    health_score_history,
    health_score_latest,
    repository as client_health_repository,
)
from repositories.command_safety import (
    approval_create,
    approval_decide,
    approval_list,
    cmd_review_create,
    cmd_review_list,
    cmd_rules_list,
    repository as command_safety_repository,
)
from repositories.cron_jobs import (
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    list_cron_jobs,
    repository as cron_job_repository,
    update_cron_job,
)
from repositories.documentation import (
    doc_asset_create,
    doc_asset_delete,
    doc_asset_list,
    doc_document_create,
    doc_document_delete,
    doc_document_list,
    doc_intervention_create,
    doc_intervention_delete,
    doc_intervention_get,
    doc_intervention_list,
    doc_intervention_update,
    doc_template_get,
    doc_template_list,
    doc_template_use,
    repository as documentation_repository,
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

# ── CRUD interventions ──────────────────────────────────────────────────────

# ── CRUD documents générés ──────────────────────────────────────────────────

# ── Templates ───────────────────────────────────────────────────────────────

# ── Assets (CMDB-lite) ──────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# v2.30.0 — Operations Safety : Module 1 — Pre-Check / Post-Check
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# v2.30.0 — Operations Safety : Module 2 — Command Safety / Guardrails
# ══════════════════════════════════════════════════════════════════════════════

















# ══════════════════════════════════════════════════════════════════════════════
# v2.30.0 — Operations Safety : Module 3 — Client Health Score
# ══════════════════════════════════════════════════════════════════════════════













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
        documentation_repository.ensure_schema(conn)
        operations_repository.ensure_schema(conn)
        command_safety_repository.ensure_schema(conn)
        client_health_repository.ensure_schema(conn)
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
