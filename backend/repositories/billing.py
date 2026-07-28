"""Persistance injectable de l'agrégat de facturation Marvin."""

from __future__ import annotations

import json
import math
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any, Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
Clock = Callable[[], datetime]

_CLIENT_COLUMNS = (
    "name",
    "client_type",
    "contact_name",
    "contact_email",
    "contact_phone",
    "address",
    "siret",
    "notes",
    "previous_provider",
    "previous_amount",
)
_QUOTE_COLUMNS = (
    "title",
    "tier",
    "status",
    "need_analysis",
    "notes",
    "valid_until",
    "sent_email",
    "number",
    "client_id",
)
_INVOICE_COLUMNS = {
    "status",
    "amount_paid",
    "payment_method",
    "paid_date",
    "notes",
    "due_date",
    "title",
}


def _finite(value: Any, field: str) -> float:
    number = float(value or 0)
    if not math.isfinite(number):
        raise ValueError(f"{field} doit être un nombre fini.")
    return number


def _non_negative(value: Any, field: str) -> float:
    number = _finite(value, field)
    if number < 0:
        raise ValueError(f"{field} ne peut pas être négatif.")
    return number


def _decode_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def _project_quote(row: dict | None) -> dict | None:
    if row is None:
        return None
    projected = dict(row)
    projected["items"] = _decode_list(projected.get("items_json"))
    return projected


def _project_invoice(row: dict | None) -> dict | None:
    if row is None:
        return None
    projected = dict(row)
    projected["items"] = _decode_list(projected.get("items_json"))
    return projected


def _quote_totals(items: list, tva_rate: Any) -> dict[str, float]:
    rate = _finite(tva_rate, "tva_rate")
    total_ht = 0.0
    cost = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        total_ht += _finite(item.get("total", 0), "items.total")
        cost += _finite(item.get("cost", 0), "items.cost") * _finite(
            item.get("qty", 1),
            "items.qty",
        )
    total_ttc = round(total_ht * (1 + rate / 100), 2)
    margin = round(total_ht - cost, 2)
    margin_pct = round((margin / total_ht * 100) if total_ht > 0 else 0, 1)
    return {
        "total_ht": total_ht,
        "tva_rate": rate,
        "total_ttc": total_ttc,
        "cost": cost,
        "margin": margin,
        "margin_pct": margin_pct,
    }


class BillingRepository:
    def __init__(
        self,
        connection_scope: ConnectionScope = db,
        clock: Clock = datetime.now,
    ) -> None:
        self._connection_scope = connection_scope
        self._clock = clock

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS billing_clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                client_type TEXT NOT NULL DEFAULT 'pme'
                    CHECK(client_type IN (
                        'mairie', 'pme', 'asso', 'particulier', 'autre'
                    )),
                contact_name TEXT DEFAULT '',
                contact_email TEXT DEFAULT '',
                contact_phone TEXT DEFAULT '',
                address TEXT DEFAULT '',
                siret TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                previous_provider TEXT DEFAULT '',
                previous_amount REAL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS billing_quotes (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                number TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'Devis',
                tier TEXT NOT NULL DEFAULT 'standard'
                    CHECK(tier IN ('basic', 'standard', 'premium', 'custom')),
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN (
                        'draft', 'sent', 'accepted', 'refused', 'expired'
                    )),
                total_ht REAL NOT NULL DEFAULT 0,
                tva_rate REAL NOT NULL DEFAULT 20.0,
                total_ttc REAL NOT NULL DEFAULT 0,
                cost REAL NOT NULL DEFAULT 0,
                margin REAL NOT NULL DEFAULT 0,
                margin_pct REAL NOT NULL DEFAULT 0,
                items_json TEXT DEFAULT '[]',
                need_analysis TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                valid_until TEXT,
                sent_email TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (client_id)
                    REFERENCES billing_clients(id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS billing_service_catalog (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                unit TEXT NOT NULL DEFAULT 'forfait'
                    CHECK(unit IN (
                        'heure', 'jour', 'forfait', 'mois',
                        'année', 'unité', 'licence'
                    )),
                price_basic REAL NOT NULL DEFAULT 0,
                price_standard REAL NOT NULL DEFAULT 0,
                price_premium REAL NOT NULL DEFAULT 0,
                cost REAL NOT NULL DEFAULT 0,
                time_hours REAL NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS billing_invoices (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                quote_id TEXT,
                number TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'Facture',
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN (
                        'draft', 'sent', 'paid', 'partial',
                        'overdue', 'cancelled'
                    )),
                total_ht REAL NOT NULL DEFAULT 0,
                tva_rate REAL NOT NULL DEFAULT 20.0,
                total_ttc REAL NOT NULL DEFAULT 0,
                amount_paid REAL NOT NULL DEFAULT 0,
                items_json TEXT DEFAULT '[]',
                payment_terms TEXT DEFAULT '30',
                payment_method TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                issue_date TEXT NOT NULL DEFAULT (date('now')),
                due_date TEXT,
                paid_date TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (client_id)
                    REFERENCES billing_clients(id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS billing_contracts (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                name TEXT NOT NULL,
                amount_ht REAL NOT NULL DEFAULT 0,
                period TEXT NOT NULL DEFAULT 'mois'
                    CHECK(period IN ('mois', 'trimestre', 'année')),
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active', 'paused', 'ended')),
                sla TEXT DEFAULT '',
                start_date TEXT NOT NULL DEFAULT (date('now')),
                end_date TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (client_id)
                    REFERENCES billing_clients(id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS billing_sequences (
                kind TEXT NOT NULL,
                year INTEGER NOT NULL,
                value INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, year)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_quotes_client "
            "ON billing_quotes(client_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_quotes_status "
            "ON billing_quotes(status, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_catalog_category "
            "ON billing_service_catalog(category, name)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_invoices_client "
            "ON billing_invoices(client_id, status)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_contracts_client "
            "ON billing_contracts(client_id, status)"
        )
        count = connection.execute(
            "SELECT COUNT(*) FROM billing_service_catalog"
        ).fetchone()[0]
        if count == 0:
            BillingRepository._seed_default_catalog(connection)

    @staticmethod
    def _seed_default_catalog(connection) -> None:
        defaults = [
            ("Support", "Support IT à distance (forfait mensuel)", "Hotline + intervention à distance illimitée, heures ouvrées", "mois", 80, 150, 280, 30, 8),
            ("Support", "Support sur site (heure)", "Déplacement et intervention sur site, facturé à l'heure", "heure", 60, 80, 110, 25, 1),
            ("Support", "Maintenance préventive (visite trimestrielle)", "Audit poste, mises à jour, vérification sauvegardes, rapport", "forfait", 150, 250, 400, 80, 3),
            ("Infrastructure", "Installation poste de travail", "Configuration Windows + Office + accès réseau + transferts données", "unité", 80, 120, 180, 40, 2),
            ("Infrastructure", "Mise en place serveur Windows", "Installation Windows Server + AD + GPO + sauvegardes", "forfait", 1200, 2000, 3500, 500, 16),
            ("Infrastructure", "Audit infrastructure réseau", "Cartographie réseau, audit sécurité, rapport et recommandations", "forfait", 500, 800, 1500, 200, 8),
            ("Sécurité", "Sauvegarde cloud (par poste, par mois)", "Sauvegarde quotidienne chiffrée, rétention 30 jours", "mois", 8, 12, 20, 4, 0),
            ("Sécurité", "Audit sécurité informatique", "Test d'intrusion léger, analyse vulnérabilités, plan de remédiation", "forfait", 600, 1200, 2500, 300, 12),
            ("Sécurité", "Antivirus pro (licence annuelle par poste)", "Solution antivirus professionnelle, mises à jour, console centrale", "année", 35, 55, 90, 20, 0),
            ("Sécurité", "Firewall configuration", "Installation, configuration et règles de filtrage", "forfait", 300, 600, 1200, 120, 6),
            ("Logiciel", "Microsoft 365 (par utilisateur/mois)", "Licence M365 Business Standard, configuration et formation", "mois", 12, 18, 28, 8, 0),
            ("Logiciel", "Migration vers cloud (forfait)", "Migration emails + fichiers vers Office 365 ou Google Workspace", "forfait", 800, 1500, 3000, 400, 16),
            ("Formation", "Formation utilisateur (demi-journée)", "Formation sur outils bureautiques ou logiciel métier", "forfait", 250, 400, 600, 100, 4),
            ("Formation", "Formation administrateur (journée)", "Formation technique pour responsable IT", "jour", 600, 900, 1400, 250, 8),
            ("Web", "Création site vitrine", "Site WordPress responsive, 5 pages, formulaire, RGPD", "forfait", 800, 1500, 3500, 400, 20),
            ("Web", "Hébergement web (annuel)", "Hébergement + nom de domaine + certificat SSL + sauvegardes", "année", 120, 200, 400, 50, 0),
            ("Téléphonie", "Standard téléphonique cloud (par ligne/mois)", "Standard IP cloud, appels illimités vers fixes/mobiles France", "mois", 18, 28, 45, 12, 0),
            ("Réseau", "Câblage réseau (par prise)", "Pose, raccordement et test d'une prise réseau Cat6", "unité", 80, 120, 180, 40, 1),
            ("Réseau", "Installation Wi-Fi pro", "Bornes Wi-Fi Pro avec VLAN guest, configuration", "forfait", 600, 1200, 2500, 350, 6),
        ]
        for category, name, description, unit, basic, standard, premium, cost, hours in defaults:
            connection.execute(
                """INSERT INTO billing_service_catalog (
                       id, category, name, description, unit,
                       price_basic, price_standard, price_premium,
                       cost, time_hours
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    category,
                    name,
                    description,
                    unit,
                    basic,
                    standard,
                    premium,
                    cost,
                    hours,
                ),
            )

    def _next_number(self, connection, kind: str, prefix: str) -> str:
        year = self._clock().year
        pattern = f"{prefix}-{year}-%"
        start = len(f"{prefix}-{year}-") + 1
        highest = connection.execute(
            """SELECT COALESCE(MAX(CAST(substr(number, ?) AS INTEGER)), 0)
               FROM billing_quotes
               WHERE ? = 'quote' AND number LIKE ?
               UNION ALL
               SELECT COALESCE(MAX(CAST(substr(number, ?) AS INTEGER)), 0)
               FROM billing_invoices
               WHERE ? = 'invoice' AND number LIKE ?
               ORDER BY 1 DESC
               LIMIT 1""",
            (start, kind, pattern, start, kind, pattern),
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO billing_sequences(kind, year, value)
               VALUES (?, ?, ?)
               ON CONFLICT(kind, year) DO UPDATE SET value =
                   CASE
                     WHEN billing_sequences.value < excluded.value
                     THEN excluded.value
                     ELSE billing_sequences.value
                   END""",
            (kind, year, int(highest or 0)),
        )
        sequence = connection.execute(
            """UPDATE billing_sequences
               SET value = value + 1
               WHERE kind = ? AND year = ?
               RETURNING value""",
            (kind, year),
        ).fetchone()[0]
        return f"{prefix}-{year}-{int(sequence):04d}"

    def client_create(self, data: dict) -> dict:
        client_id = str(uuid.uuid4())
        previous_amount = _finite(
            data.get("previous_amount", 0),
            "previous_amount",
        )
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO billing_clients (
                       id, name, client_type, contact_name, contact_email,
                       contact_phone, address, siret, notes,
                       previous_provider, previous_amount
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    client_id,
                    data.get("name", "Client sans nom"),
                    data.get("client_type", "pme"),
                    data.get("contact_name", ""),
                    data.get("contact_email", ""),
                    data.get("contact_phone", ""),
                    data.get("address", ""),
                    data.get("siret", ""),
                    data.get("notes", ""),
                    data.get("previous_provider", ""),
                    previous_amount,
                ),
            )
            row = connection.execute(
                "SELECT * FROM billing_clients WHERE id = ?",
                (client_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("Le client créé est introuvable avant commit.")
        return result

    def client_get(self, client_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM billing_clients WHERE id = ?",
                (client_id,),
            ).fetchone()
        return row_to_dict(row)

    def client_list(self, client_type: str | None = None) -> list[dict]:
        sql = "SELECT * FROM billing_clients"
        params: tuple[Any, ...] = ()
        if client_type:
            sql += " WHERE client_type = ?"
            params = (client_type,)
        sql += " ORDER BY name ASC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]

    def client_update(self, client_id: str, data: dict) -> dict | None:
        columns: list[str] = []
        values: list[Any] = []
        for key in _CLIENT_COLUMNS:
            if key in data:
                columns.append(f"{key} = ?")
                value = data[key]
                if key == "previous_amount":
                    value = _finite(value, key)
                values.append(value)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if columns:
                columns.append("updated_at = datetime('now')")
                connection.execute(
                    f"UPDATE billing_clients SET {', '.join(columns)} "
                    "WHERE id = ?",
                    (*values, client_id),
                )
            row = connection.execute(
                "SELECT * FROM billing_clients WHERE id = ?",
                (client_id,),
            ).fetchone()
        return row_to_dict(row)

    def client_delete(self, client_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM billing_clients WHERE id = ?",
                (client_id,),
            )

    def quote_create(self, data: dict) -> dict:
        quote_id = str(uuid.uuid4())
        items = data.get("items", [])
        if not isinstance(items, list):
            items = []
        totals = _quote_totals(items, data.get("tva_rate", 20.0))
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            number = data.get("number") or self._next_number(
                connection,
                "quote",
                "DEV",
            )
            connection.execute(
                """INSERT INTO billing_quotes (
                       id, client_id, number, title, tier, status,
                       total_ht, tva_rate, total_ttc, cost, margin,
                       margin_pct, items_json, need_analysis, notes,
                       valid_until, sent_email
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    quote_id,
                    data["client_id"],
                    number,
                    data.get("title", "Devis"),
                    data.get("tier", "standard"),
                    data.get("status", "draft"),
                    totals["total_ht"],
                    totals["tva_rate"],
                    totals["total_ttc"],
                    totals["cost"],
                    totals["margin"],
                    totals["margin_pct"],
                    json.dumps(items, ensure_ascii=False),
                    data.get("need_analysis", ""),
                    data.get("notes", ""),
                    data.get("valid_until"),
                    data.get("sent_email", ""),
                ),
            )
            row = connection.execute(
                "SELECT * FROM billing_quotes WHERE id = ?",
                (quote_id,),
            ).fetchone()
        result = _project_quote(row_to_dict(row))
        if result is None:
            raise RuntimeError("Le devis créé est introuvable avant commit.")
        return result

    def quote_get(self, quote_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM billing_quotes WHERE id = ?",
                (quote_id,),
            ).fetchone()
        return _project_quote(row_to_dict(row))

    def quote_list(
        self,
        client_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        sql = (
            "SELECT q.*, c.name AS client_name, c.client_type "
            "FROM billing_quotes q "
            "LEFT JOIN billing_clients c ON c.id = q.client_id "
            "WHERE 1=1"
        )
        params: list[Any] = []
        if client_id:
            sql += " AND q.client_id = ?"
            params.append(client_id)
        if status:
            sql += " AND q.status = ?"
            params.append(status)
        sql += " ORDER BY q.created_at DESC, q.id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [
            projected
            for row in rows
            if (projected := _project_quote(row_to_dict(row))) is not None
        ]

    def quote_update(self, quote_id: str, data: dict) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            current_row = connection.execute(
                "SELECT * FROM billing_quotes WHERE id = ?",
                (quote_id,),
            ).fetchone()
            current = _project_quote(row_to_dict(current_row))
            if current is None:
                return None
            columns: list[str] = []
            values: list[Any] = []
            if "items" in data or "tva_rate" in data:
                items = data.get("items", current["items"])
                if not isinstance(items, list):
                    raise TypeError("Les lignes du devis doivent être une liste.")
                totals = _quote_totals(
                    items,
                    data.get("tva_rate", current["tva_rate"]),
                )
                columns.extend(
                    [
                        "items_json = ?",
                        "total_ht = ?",
                        "tva_rate = ?",
                        "total_ttc = ?",
                        "cost = ?",
                        "margin = ?",
                        "margin_pct = ?",
                    ]
                )
                values.extend(
                    [
                        json.dumps(items, ensure_ascii=False),
                        totals["total_ht"],
                        totals["tva_rate"],
                        totals["total_ttc"],
                        totals["cost"],
                        totals["margin"],
                        totals["margin_pct"],
                    ]
                )
            for key in _QUOTE_COLUMNS:
                if key in data:
                    columns.append(f"{key} = ?")
                    values.append(data[key])
            if columns:
                columns.append("updated_at = datetime('now')")
                connection.execute(
                    f"UPDATE billing_quotes SET {', '.join(columns)} "
                    "WHERE id = ?",
                    (*values, quote_id),
                )
            row = connection.execute(
                "SELECT * FROM billing_quotes WHERE id = ?",
                (quote_id,),
            ).fetchone()
        return _project_quote(row_to_dict(row))

    def quote_delete(self, quote_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM billing_quotes WHERE id = ?",
                (quote_id,),
            )

    def catalog_list(self, category: str | None = None) -> list[dict]:
        sql = "SELECT * FROM billing_service_catalog WHERE active = 1"
        params: tuple[Any, ...] = ()
        if category:
            sql += " AND category = ?"
            params = (category,)
        sql += " ORDER BY category ASC, name ASC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]

    def catalog_create(self, data: dict) -> dict:
        service_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO billing_service_catalog (
                       id, category, name, description, unit,
                       price_basic, price_standard, price_premium,
                       cost, time_hours
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    service_id,
                    data.get("category", "Autre"),
                    data["name"],
                    data.get("description", ""),
                    data.get("unit", "forfait"),
                    _non_negative(data.get("price_basic", 0), "price_basic"),
                    _non_negative(
                        data.get("price_standard", 0),
                        "price_standard",
                    ),
                    _non_negative(
                        data.get("price_premium", 0),
                        "price_premium",
                    ),
                    _non_negative(data.get("cost", 0), "cost"),
                    _non_negative(data.get("time_hours", 0), "time_hours"),
                ),
            )
            row = connection.execute(
                "SELECT * FROM billing_service_catalog WHERE id = ?",
                (service_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("Le service créé est introuvable avant commit.")
        return result

    def catalog_delete(self, service_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM billing_service_catalog WHERE id = ?",
                (service_id,),
            )

    def invoice_create(self, data: dict) -> dict:
        invoice_id = str(uuid.uuid4())
        now = self._clock()
        total_ht = _non_negative(data.get("total_ht", 0), "total_ht")
        tva_rate = _finite(data.get("tva_rate", 20.0), "tva_rate")
        supplied_total = data.get("total_ttc")
        total_ttc = (
            _non_negative(supplied_total, "total_ttc")
            if supplied_total is not None
            else round(total_ht * (1 + tva_rate / 100), 2)
        )
        terms = str(data.get("payment_terms", "30"))
        issue = data.get("issue_date") or now.strftime("%Y-%m-%d")
        due = data.get("due_date")
        if not due:
            try:
                due = (
                    datetime.strptime(issue, "%Y-%m-%d")
                    + timedelta(days=int(terms or 30))
                ).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                due = ""
        items = data.get("items", [])
        if not isinstance(items, list):
            raise TypeError("Les lignes de facture doivent être une liste.")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            number = self._next_number(connection, "invoice", "FAC")
            connection.execute(
                """INSERT INTO billing_invoices (
                       id, client_id, quote_id, number, title, status,
                       total_ht, tva_rate, total_ttc, items_json,
                       payment_terms, notes, issue_date, due_date
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    invoice_id,
                    data["client_id"],
                    data.get("quote_id"),
                    number,
                    data.get("title", "Facture"),
                    data.get("status", "draft"),
                    total_ht,
                    tva_rate,
                    total_ttc,
                    json.dumps(items, ensure_ascii=False),
                    terms,
                    data.get("notes", ""),
                    issue,
                    due,
                ),
            )
            row = connection.execute(
                "SELECT * FROM billing_invoices WHERE id = ?",
                (invoice_id,),
            ).fetchone()
        result = _project_invoice(row_to_dict(row))
        if result is None:
            raise RuntimeError("La facture créée est introuvable avant commit.")
        return result

    def invoice_list(
        self,
        client_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        sql = (
            "SELECT i.*, c.name AS client_name, c.client_type "
            "FROM billing_invoices i "
            "LEFT JOIN billing_clients c ON c.id = i.client_id "
            "WHERE 1=1"
        )
        params: list[Any] = []
        if client_id:
            sql += " AND i.client_id = ?"
            params.append(client_id)
        if status:
            sql += " AND i.status = ?"
            params.append(status)
        sql += " ORDER BY i.created_at DESC, i.id ASC"
        today = self._clock().strftime("%Y-%m-%d")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        result: list[dict] = []
        for row in rows:
            invoice = _project_invoice(row_to_dict(row))
            if invoice is None:
                continue
            if (
                invoice.get("status") in ("sent", "partial")
                and invoice.get("due_date")
                and invoice["due_date"] < today
            ):
                invoice["is_overdue"] = True
            result.append(invoice)
        return result

    def invoice_get(self, invoice_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM billing_invoices WHERE id = ?",
                (invoice_id,),
            ).fetchone()
        return _project_invoice(row_to_dict(row))

    def invoice_update(self, invoice_id: str, data: dict) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            current = connection.execute(
                "SELECT * FROM billing_invoices WHERE id = ?",
                (invoice_id,),
            ).fetchone()
            if current is None:
                return None
            columns: list[str] = []
            values: list[Any] = []
            for key, value in data.items():
                if key not in _INVOICE_COLUMNS:
                    continue
                if key == "amount_paid":
                    value = _non_negative(value, key)
                    if value > float(current["total_ttc"]):
                        raise ValueError(
                            "amount_paid ne peut pas dépasser total_ttc."
                        )
                columns.append(f"{key} = ?")
                values.append(value)
            if columns:
                columns.append("updated_at = datetime('now')")
                connection.execute(
                    f"UPDATE billing_invoices SET {', '.join(columns)} "
                    "WHERE id = ?",
                    (*values, invoice_id),
                )
            row = connection.execute(
                "SELECT * FROM billing_invoices WHERE id = ?",
                (invoice_id,),
            ).fetchone()
        return _project_invoice(row_to_dict(row))

    def invoice_delete(self, invoice_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM billing_invoices WHERE id = ?",
                (invoice_id,),
            )

    def contract_create(self, data: dict) -> dict:
        contract_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO billing_contracts (
                       id, client_id, name, amount_ht, period,
                       status, sla, start_date, end_date
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    contract_id,
                    data["client_id"],
                    data.get("name", "Contrat"),
                    _non_negative(data.get("amount_ht", 0), "amount_ht"),
                    data.get("period", "mois"),
                    data.get("status", "active"),
                    data.get("sla", ""),
                    data.get("start_date") or self._clock().strftime("%Y-%m-%d"),
                    data.get("end_date"),
                ),
            )
            row = connection.execute(
                "SELECT * FROM billing_contracts WHERE id = ?",
                (contract_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("Le contrat créé est introuvable avant commit.")
        return result

    def contract_list(self, client_id: str | None = None) -> list[dict]:
        if client_id:
            sql = (
                "SELECT * FROM billing_contracts "
                "WHERE client_id = ? ORDER BY created_at DESC, id ASC"
            )
            params: tuple[Any, ...] = (client_id,)
        else:
            sql = (
                "SELECT c.*, cl.name AS client_name "
                "FROM billing_contracts c "
                "LEFT JOIN billing_clients cl ON cl.id = c.client_id "
                "ORDER BY c.created_at DESC, c.id ASC"
            )
            params = ()
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]


repository = BillingRepository()
billing_client_create = repository.client_create
billing_client_get = repository.client_get
billing_client_list = repository.client_list
billing_client_update = repository.client_update
billing_client_delete = repository.client_delete
billing_quote_create = repository.quote_create
billing_quote_get = repository.quote_get
billing_quote_list = repository.quote_list
billing_quote_update = repository.quote_update
billing_quote_delete = repository.quote_delete
billing_catalog_list = repository.catalog_list
billing_catalog_create = repository.catalog_create
billing_catalog_delete = repository.catalog_delete
billing_invoice_create = repository.invoice_create
billing_invoice_list = repository.invoice_list
billing_invoice_get = repository.invoice_get
billing_invoice_update = repository.invoice_update
billing_invoice_delete = repository.invoice_delete
billing_contract_create = repository.contract_create
billing_contract_list = repository.contract_list
