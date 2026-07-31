"""Domaine facturation : clients, catalogue, devis, march?, factures et pilotage."""
from __future__ import annotations
import datetime as _dt
import json as _json
import math
import re as _re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
import database as db
from platform_paths import PATHS as _SYSTEM_PATHS

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
async def _missing_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "D?pendance d'outil non configur?e."}
_web_search: Tool = _missing_tool
_file_create_pdf: Tool = _missing_tool
def configure(*, web_search: Tool, file_create_pdf: Tool) -> None:
    global _web_search, _file_create_pdf
    _web_search = web_search
    _file_create_pdf = file_create_pdf


def _finite_amount(value: Any, *, field: str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} doit être un montant numérique.") from exc
    if not math.isfinite(amount):
        raise ValueError(f"{field} doit être un montant fini.")
    return round(amount, 2)


async def execute_billing_client_create(args: dict) -> dict:
    """Crée un nouveau client dans le module devis/facturation."""
    if not args.get("name"):
        return {"error": "Paramètre 'name' requis."}
    try:
        client = db.billing_client_create(args)
        return {"success": True, "message": f"Client '{client['name']}' créé.", "client": client}
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_client_list(args: dict) -> dict:
    """Liste les clients (filtrable par type : mairie | pme | asso | particulier)."""
    try:
        clients = db.billing_client_list(args.get("client_type"))
        return {"success": True, "count": len(clients), "clients": clients}
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_catalog_list(args: dict) -> dict:
    """Liste le catalogue de prestations IT (par catégorie optionnelle)."""
    try:
        services = db.billing_catalog_list(args.get("category"))
        # Group by category for readability
        by_cat = {}
        for s in services:
            cat = s.get("category", "Autre")
            by_cat.setdefault(cat, []).append(s)
        return {
            "success": True,
            "count": len(services),
            "categories": list(by_cat.keys()),
            "by_category": by_cat,
            "services": services,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_analyze_need(args: dict) -> dict:
    """
    Analyse structurée d'un besoin client pour préparer une proposition commerciale.
    Catégorise les besoins par axe (infrastructure, sécurité, maintenance, etc.)
    et propose les prestations du catalogue qui matchent.
    """
    description = args.get("description", "").strip()
    client_type = args.get("client_type", "pme")
    if not description:
        return {"error": "Paramètre 'description' du besoin requis."}

    try:
        catalog = db.billing_catalog_list()

        # Keyword matching against catalog
        text = description.lower()
        keywords_to_categories = {
            "support": ["support", "hotline", "depannage", "dépannage", "assistance", "aide", "maintenance"],
            "infrastructure": ["serveur", "server", "poste", "ordinateur", "matériel", "materiel",
                                "installation", "nouveau poste", "infra"],
            "sécurité": ["sécurité", "securite", "antivirus", "backup", "sauvegarde", "firewall",
                          "intrusion", "audit", "vpn", "rgpd"],
            "logiciel": ["microsoft 365", "office", "m365", "logiciel", "licence", "cloud",
                          "migration", "google workspace"],
            "formation": ["formation", "former", "apprendre", "tutoriel"],
            "web": ["site web", "site internet", "wordpress", "vitrine", "hébergement"],
            "réseau": ["réseau", "wifi", "câblage", "cablage", "switch", "router"],
            "téléphonie": ["téléphone", "telephone", "voip", "standard", "ligne"],
        }

        matched_categories = set()
        for cat, kws in keywords_to_categories.items():
            if any(k in text for k in kws):
                matched_categories.add(cat)

        # ── Scoring de pertinence générique (multi-métiers) ───────────────────
        # On note chaque prestation du catalogue par recoupement de mots avec le
        # besoin → fonctionne pour TOUT métier, pas seulement l'informatique.
        import re as _r
        stop = {"de", "la", "le", "les", "des", "un", "une", "et", "pour", "avec", "du",
                "en", "à", "au", "aux", "sur", "ou", "nos", "mon", "ma", "mes", "notre",
                "client", "besoin", "nous", "vous", "il", "elle", "je", "tu"}
        need_words = {w for w in _r.findall(r"[a-zàâçéèêëîïôûùüÿñ0-9]{3,}", text) if w not in stop}

        def _score(s):
            blob = f"{s.get('name','')} {s.get('description','')} {s.get('category','')} {s.get('use_cases','')}".lower()
            sw = set(_r.findall(r"[a-zàâçéèêëîïôûùüÿñ0-9]{3,}", blob))
            overlap = len(need_words & sw)
            cat_match = 1 if (s["category"].lower() in matched_categories or
                              any(mc in s["category"].lower() for mc in matched_categories)) else 0
            return overlap * 2 + cat_match * 3

        scored = [(s, _score(s)) for s in catalog]
        scored.sort(key=lambda x: x[1], reverse=True)
        # Si rien ne ressort vraiment, on propose tout le catalogue
        relevant = [s for s, sc in scored if sc > 0]
        chosen = relevant if relevant else [s for s, _ in scored]

        suggested = [{
            "id": s["id"], "category": s["category"], "name": s["name"],
            "description": s["description"], "unit": s["unit"],
            "price_basic": s["price_basic"], "price_standard": s["price_standard"],
            "price_premium": s["price_premium"], "time_hours": s["time_hours"],
        } for s in chosen[:25]]

        # Rough total estimates per tier
        total_basic    = sum(s["price_basic"] for s in suggested)
        total_standard = sum(s["price_standard"] for s in suggested)
        total_premium  = sum(s["price_premium"] for s in suggested)
        total_hours    = sum(s["time_hours"] for s in suggested)

        return {
            "success": True,
            "description": description,
            "client_type": client_type,
            "matched_categories": sorted(matched_categories),
            "suggested_services": suggested,
            "suggested_count": len(suggested),
            "estimated_totals_ht": {
                "basic":    round(total_basic, 2),
                "standard": round(total_standard, 2),
                "premium":  round(total_premium, 2),
            },
            "estimated_time_hours": total_hours,
            "hint": "Utilisez billing_quote_create avec les items choisis pour générer un devis.",
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_quote_create(args: dict) -> dict:
    """Crée un devis avec lignes (items), calcul automatique HT/TTC/marge."""
    if not args.get("client_id"):
        return {"error": "Paramètre 'client_id' requis."}
    if not args.get("items"):
        return {"error": "Paramètre 'items' requis (liste de prestations)."}
    try:
        quote = db.billing_quote_create(args)
        return {
            "success": True,
            "message": f"Devis {quote['number']} créé : {quote['total_ttc']}€ TTC (marge {quote['margin_pct']}%)",
            "quote": quote,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_quote_list(args: dict) -> dict:
    """Liste les devis (filtrable par client_id ou status)."""
    try:
        quotes = db.billing_quote_list(args.get("client_id"), args.get("status"))
        return {"success": True, "count": len(quotes), "quotes": quotes}
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_quote_compare(args: dict) -> dict:
    """
    Compare un devis avec le prestataire précédent.
    Calcule économies, gains, valeur ajoutée.
    """
    quote_id = args.get("quote_id", "").strip()
    if not quote_id:
        return {"error": "Paramètre 'quote_id' requis."}
    try:
        quote = db.billing_quote_get(quote_id)
        if not quote:
            return {"error": "Devis introuvable"}
        client = db.billing_client_get(quote["client_id"])
        if not client:
            return {"error": "Client introuvable"}

        previous_amount = float(client.get("previous_amount") or 0)
        new_amount = float(quote["total_ttc"])
        difference = round(previous_amount - new_amount, 2)
        savings_pct = round((difference / previous_amount * 100) if previous_amount > 0 else 0, 1)

        verdict = (
            f"Économie de {difference:.2f}€ ({savings_pct}%)" if difference > 0
            else f"Augmentation de {-difference:.2f}€ ({-savings_pct}%)" if difference < 0
            else "Tarif équivalent"
        )

        return {
            "success": True,
            "client": client.get("name"),
            "previous_provider": client.get("previous_provider", "Inconnu"),
            "previous_amount": previous_amount,
            "new_amount": new_amount,
            "difference": difference,
            "savings_percent": savings_pct,
            "verdict": verdict,
            "quote_number": quote["number"],
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_quote_pdf(args: dict) -> dict:
    """Génère un PDF professionnel du devis."""
    quote_id = args.get("quote_id", "").strip()
    if not quote_id:
        return {"error": "Paramètre 'quote_id' requis."}
    try:
        quote = db.billing_quote_get(quote_id)
        if not quote:
            return {"error": "Devis introuvable"}
        client = db.billing_client_get(quote["client_id"])
        if not client:
            return {"error": "Client introuvable"}

        # Build markdown content for PDF
        from datetime import datetime as _dt
        date_str = _dt.now().strftime("%d/%m/%Y")
        valid_until = quote.get("valid_until") or "30 jours"

        def _num(v, default=0.0):
            # Les valeurs numériques d'un devis peuvent arriver en string (JSON produit par
            # le LLM, ex. "150.00") — coercion défensive pour éviter "Unknown format code 'f'
            # for object of type 'str'" sur le formatage {:.2f} plus bas.
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        items_md = ""
        for i, it in enumerate(quote.get("items", []), 1):
            label = it.get("label", "Prestation")
            desc  = it.get("description", "")
            qty   = _num(it.get("qty", 1), 1.0)
            unit  = it.get("unit", "")
            up    = _num(it.get("unit_price", it.get("price", 0)))
            total = _num(it.get("total"), up * qty)
            items_md += f"\n| {i} | {label} | {qty:g} {unit} | {up:.2f}€ | {total:.2f}€ |"
            if desc:
                items_md += f"\n|  | _{desc}_ |  |  |  |"

        tier_label = {"basic": "Basic", "standard": "Standard", "premium": "Premium",
                       "custom": "Sur mesure"}.get(quote.get("tier"), quote.get("tier"))

        content = f"""# DEVIS N° {quote['number']}

**Date :** {date_str}    **Validité :** {valid_until}    **Formule :** {tier_label}

---

## Client
**{client['name']}**
{client.get('address', '')}
{('SIRET : ' + client['siret']) if client.get('siret') else ''}
{('Contact : ' + client['contact_name']) if client.get('contact_name') else ''}
{('Email : ' + client['contact_email']) if client.get('contact_email') else ''}
{('Tél : ' + client['contact_phone']) if client.get('contact_phone') else ''}

## Objet
{quote.get('title', 'Prestation informatique')}

{('## Analyse du besoin\\n\\n' + quote['need_analysis']) if quote.get('need_analysis') else ''}

## Détail des prestations

| # | Désignation | Quantité | P.U. HT | Total HT |
|---|-------------|----------|---------|----------|{items_md}

## Récapitulatif

| | |
|---|---|
| **Total HT** | **{_num(quote.get('total_ht')):.2f} €** |
| TVA {_num(quote.get('tva_rate')):.1f}% | {(_num(quote.get('total_ttc')) - _num(quote.get('total_ht'))):.2f} € |
| **Total TTC** | **{_num(quote.get('total_ttc')):.2f} €** |

{('## Notes\\n\\n' + quote['notes']) if quote.get('notes') else ''}

---

*Devis valable {valid_until}. Bon pour accord, à retourner signé.*
"""
        # Use existing file_create_pdf tool
        output_path = args.get("output_path") or str(
            Path(_SYSTEM_PATHS["desktop"]) / f"devis_{quote['number']}.pdf"
        )
        result = await _file_create_pdf({
            "path": output_path,
            "title": f"Devis {quote['number']} - {client['name']}",
            "content": content,
        })
        if result.get("error"):
            return result
        # Mark quote as sent_pdf (optional metadata)
        return {
            "success": True,
            "message": f"Devis PDF généré : {output_path}",
            "path": output_path,
            "quote_number": quote["number"],
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_quote_email(args: dict) -> dict:
    """
    Génère un email d'accompagnement professionnel pour envoyer un devis.
    Le ton est adapté au type de client (mairie = formel, asso = chaleureux, PME = pro).
    """
    quote_id = args.get("quote_id", "").strip()
    if not quote_id:
        return {"error": "Paramètre 'quote_id' requis."}
    try:
        quote = db.billing_quote_get(quote_id)
        if not quote:
            return {"error": "Devis introuvable"}
        client = db.billing_client_get(quote["client_id"])
        if not client:
            return {"error": "Client introuvable"}

        client_type = client.get("client_type", "pme")
        contact_name = client.get("contact_name") or "Madame, Monsieur"

        # Tone adapted per client type
        if client_type == "mairie":
            opening = f"Madame, Monsieur,"
            tone_body = "J'ai l'honneur de vous adresser, ci-joint, notre proposition commerciale relative à"
            closing = "Je me tiens à votre entière disposition pour toute précision complémentaire.\n\nJe vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées."
        elif client_type == "asso":
            opening = f"Bonjour {contact_name},"
            tone_body = "Je vous transmets notre proposition pour"
            closing = "N'hésitez pas à me contacter si vous avez la moindre question, je serai ravi d'y répondre.\n\nBien à vous,"
        else:  # pme / particulier
            opening = f"Bonjour {contact_name},"
            tone_body = "Suite à nos échanges, je vous adresse en pièce jointe notre devis concernant"
            closing = "Je reste à votre disposition pour tout échange complémentaire.\n\nCordialement,"

        # Build the cover email
        items_summary = []
        for it in quote.get("items", [])[:5]:
            items_summary.append(f"• {it.get('label', '?')}")
        items_text = "\n".join(items_summary)
        if len(quote.get("items", [])) > 5:
            items_text += f"\n• … et {len(quote['items']) - 5} autres prestations"

        valid = quote.get("valid_until") or "30 jours"
        tier_label = {"basic":"Basic","standard":"Standard","premium":"Premium","custom":"Sur mesure"}.get(quote.get("tier"), "")

        total_ttc = _finite_amount(quote.get("total_ttc", 0), field="total_ttc")
        total_ht = _finite_amount(quote.get("total_ht", 0), field="total_ht")
        tva_rate = _finite_amount(quote.get("tva_rate", 20), field="tva_rate")
        subject = f"Devis {quote['number']} — {quote.get('title','Prestation IT')}"
        body = f"""{opening}

{tone_body} {quote.get('title', 'votre projet informatique').lower()}.

Vous trouverez en pièce jointe le devis n°{quote['number']} (formule {tier_label}) détaillant l'ensemble des prestations proposées.

**Récapitulatif :**
{items_text}

**Montant total : {total_ttc:.2f} € TTC**
(soit {total_ht:.2f} € HT + {tva_rate:.0f}% de TVA)

Cette proposition est valable {valid} à compter de la date d'envoi.

{closing}
"""
        return {
            "success": True,
            "subject": subject,
            "body": body,
            "to": client.get("contact_email", ""),
            "client_name": client.get("name"),
            "quote_number": quote["number"],
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_tier_breakdown(args: dict) -> dict:
    """
    Génère 3 propositions Basic/Standard/Premium pour un besoin donné.
    Permet au client de choisir le niveau qui lui convient.
    """
    service_ids = args.get("service_ids", [])
    if not service_ids:
        return {"error": "Paramètre 'service_ids' requis (liste d'IDs du catalogue)."}
    try:
        catalog = {s["id"]: s for s in db.billing_catalog_list()}
        chosen = [catalog[sid] for sid in service_ids if sid in catalog]
        if not chosen:
            return {"error": "Aucun service trouvé pour les IDs donnés."}

        breakdown = {}
        for tier in ("basic", "standard", "premium"):
            items = []
            total = 0
            for s in chosen:
                price = s[f"price_{tier}"]
                items.append({
                    "name": s["name"],
                    "category": s["category"],
                    "unit": s["unit"],
                    "price": price,
                    "qty": 1,
                    "total": price,
                })
                total += price
            tva = round(total * 0.20, 2)
            breakdown[tier] = {
                "label":     {"basic": "Basic", "standard": "Standard", "premium": "Premium"}[tier],
                "items":     items,
                "total_ht":  round(total, 2),
                "total_ttc": round(total + tva, 2),
                "description": {
                    "basic":    "Formule essentielle, fonctionnalités de base.",
                    "standard": "Formule équilibrée, recommandée pour la plupart des besoins.",
                    "premium":  "Formule complète avec accompagnement et services additionnels.",
                }[tier],
            }
        return {
            "success": True,
            "service_count": len(chosen),
            "breakdown": breakdown,
        }
    except Exception as e:
        return {"error": str(e)}


def _extract_prices(text: str) -> list[dict]:
    """
    Extrait les prix (€ et $) d'un texte web — version STRICTE et vérifiée.
    Le symbole monétaire doit être collé au nombre (≤1 espace) et le contexte
    est vérifié pour écarter les comptages (« 40 999 résultats »), les specs
    (MHz, Go), les remises (« -10€ »), les frais de port et les prix /mois.
    """
    out = []
    if not text:
        return out
    t = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    num = r'\d{1,3}(?:[ .]\d{3})+(?:,\d{1,2})?|\d{1,6}(?:,\d{1,2})?'
    pat = r'(?:(?P<pre>€|EUR)\s?(?P<a>' + num + r')|(?P<b>' + num + r')\s?(?P<post>€|EUR|euros?))'
    for m in _re.finditer(pat, t, _re.IGNORECASE):
        raw = m.group("a") or m.group("b") or ""
        start, end = m.start(), m.end()
        imm = t[max(0, start - 14):start].lower()          # voisinage très proche
        wide = t[max(0, start - 32):start].lower()          # contexte élargi (livraison)
        after = t[end:end + 7]
        after_l = after.lower()
        # marqueur de note de bas de page (condition, ex '10€*') → pas un prix produit
        if after.startswith("*"):
            continue
        # frais de port / livraison (signal fort même un peu éloigné)
        if "livraison" in wide or "frais de port" in wide or "port offert" in wide or imm.rstrip().endswith("port"):
            continue
        # remise / réduction / signe '-' COLLÉ au chiffre (ex '-10€')
        if (start > 0 and t[start - 1] == "-") or "remise" in imm or "économ" in imm            or "econom" in imm or "éduction" in imm or "eduction" in imm:
            continue
        # prix récurrent /mois /an
        if after_l.lstrip().startswith(("/mois", "/an", "/mo", "/ mois")):
            continue
        # grand entier SANS séparateur collé à € : presque toujours un comptage ou un
        # prix dont la virgule décimale a été perdue (ex '40999€' = '409,99€') → on écarte
        if v_has_no_sep(raw) and (_parse_price_number(raw) or 0) >= 10000:
            continue
        v = _parse_price_number(raw)
        if v and 2 <= v <= 200000:
            out.append({"value": round(v, 2), "currency": "EUR"})
    for m in _re.finditer(r'(?:US)?\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d{1,6}(?:\.\d{2})?)', t):
        v = _parse_price_number(m.group(1))
        if v and 2 <= v <= 200000:
            out.append({"value": round(v, 2), "currency": "USD"})
    return out


def _extract_ratings(text: str) -> dict:
    """Extrait une note (/5) et un nombre d'avis d'un texte web. {} si rien."""
    if not text:
        return {}
    t = text.replace("\xa0", " ")
    rating = None
    count = None
    # "4,5/5" · "4.5 / 5" · "4,5 sur 5" · "4.5 out of 5"
    m = _re.search(r'\b([0-5](?:[.,]\d)?)\s*(?:/|sur|out of)\s*5\b', t, _re.IGNORECASE)
    if m:
        v = float(m.group(1).replace(",", "."))
        if 0 <= v <= 5:
            rating = v
    # note /10 (ex lesnumeriques, 01net) → ramenée sur 5
    if rating is None:
        m = _re.search(r'\b([0-9](?:[.,]\d)?|10)\s*(?:/|sur)\s*10\b', t, _re.IGNORECASE)
        if m:
            v = float(m.group(1).replace(",", ".")) / 2.0
            if 0 <= v <= 5:
                rating = round(v, 1)
    # TrustScore / Trustpilot "TrustScore 4,2"
    if rating is None:
        m = _re.search(r'trustscore\s*:?\s*([0-5](?:[.,]\d)?)', t, _re.IGNORECASE)
        if m:
            v = float(m.group(1).replace(",", "."))
            if 0 <= v <= 5:
                rating = v
    # "Note : 4,5" · "noté 4,5" · "★ 4,5"
    if rating is None:
        m = _re.search(r'(?:note|not[ée]+|rating|★|étoiles?)\s*:?\s*([0-5](?:[.,]\d)?)\b', t, _re.IGNORECASE)
        if m:
            v = float(m.group(1).replace(",", "."))
            if 0 <= v <= 5:
                rating = v
    # "4,4 (62)" = note (nb d'avis) — très fréquent (Amazon, Google)
    if rating is None:
        m = _re.search(r'\b([0-5](?:[.,]\d))\s*\((\d[\d \xa0.]{0,7})\)', t)
        if m:
            v = float(m.group(1).replace(",", "."))
            if 0 <= v <= 5:
                rating = v
                count = _parse_int(m.group(2))
    # nombre d'avis : "(62 avis)" · "1 234 reviews" · "62 évaluations"
    if count is None:
        m = _re.search(r'(\d[\d \xa0.]{0,7})\s*(?:avis|reviews?|évaluations?|commentaires?|ratings?)', t, _re.IGNORECASE)
        if m:
            count = _parse_int(m.group(1))
    out = {}
    if rating is not None:
        out["rating"] = round(rating, 1)
    if count:
        out["reviews"] = count
    return out


async def execute_billing_product_reviews(args: dict) -> dict:
    """
    ⭐ Recherche et agrège les AVIS d'un produit/prestation sur le web : note
    moyenne /5 (pondérée par le nb d'avis), total d'avis, et extraits d'avis.
    """
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "Paramètre 'query' requis."}
    queries = [f"{query} avis note", f"{query} avis clients trustpilot",
               f"{query} review rating capterra g2", f"{query} test note /5"]
    rated, snippets, seen = [], [], set()
    try:
        # Séquentiel : DuckDuckGo bloque les rafales parallèles (anti-bot).
        for q in queries:
            res = await _web_search({"query": q, "max_results": 8})
            if not (isinstance(res, dict) and res.get("success")):
                continue
            for r in res.get("results", []):
                blob = f"{r.get('title','')} {r.get('snippet','')}"
                rt = _extract_ratings(blob)
                url = r.get("url", "")
                if rt.get("rating") is not None and url not in seen:
                    seen.add(url)
                    rated.append({"source": r.get("title", "")[:90], "url": url,
                                  "rating": rt["rating"], "reviews": rt.get("reviews")})
                if r.get("snippet"):
                    snippets.append({"source": r.get("title", "")[:80], "text": r["snippet"][:220], "url": url})
        if not rated:
            return {"success": True, "query": query, "rated_sources": 0,
                    "message": "Aucune note exploitable détectée. Consultez les extraits/sources.",
                    "review_snippets": snippets[:6]}
        tot_w = sum(s.get("reviews") or 1 for s in rated)
        avg = round(sum(s["rating"] * (s.get("reviews") or 1) for s in rated) / tot_w, 2)
        total_reviews = sum(s.get("reviews") or 0 for s in rated)
        best = max(rated, key=lambda s: (s["rating"], s.get("reviews") or 0))
        sentiment = ("excellent" if avg >= 4.5 else "très bon" if avg >= 4.0 else
                     "bon" if avg >= 3.5 else "mitigé" if avg >= 2.5 else "faible")
        return {
            "success": True, "query": query,
            "average_rating": avg, "rating_out_of": 5,
            "total_reviews": total_reviews, "rated_sources": len(rated),
            "sentiment": sentiment,
            "ratings": sorted(rated, key=lambda s: -(s.get("reviews") or 0))[:8],
            "review_snippets": snippets[:6],
            "advice": f"Note moyenne {avg}/5 ({sentiment}) sur {total_reviews or '?'} avis, "
                      f"{len(rated)} source(s). À recouper avec les extraits.",
            "disclaimer": "Notes agrégées automatiquement du web ; vérifiez les sources.",
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_market_research(args: dict) -> dict:
    """
    🔎 Compare les offres du marché sur le web pour un produit/prestation IT.
    Cherche les prix en ligne (multi-requêtes), agrège (min/médiane/max), liste les
    sources, et recommande un prix de revient + un prix de vente selon la marge cible.
    """
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "Paramètre 'query' requis (ex: 'Dell Latitude 5550 i5 16Go 512Go')."}
    target_margin = float(args.get("target_margin_pct", 30))
    usd_to_eur = float(args.get("usd_to_eur", 0.92))

    # Plusieurs angles de recherche pour capter un maximum de prix
    queries = [f"{query} prix", f"{query} acheter prix €", f"{query} price buy"]
    all_prices, sources, seen_urls = [], [], set()
    try:
        # Séquentiel : DuckDuckGo bloque les rafales parallèles (anti-bot). Le cache
        # TTL gère l'efficacité sur les requêtes répétées.
        for q in queries:
            res = await _web_search({"query": q, "max_results": 8})
            if not (isinstance(res, dict) and res.get("success")):
                continue
            for r in res.get("results", []):
                blob = f"{r.get('title','')} {r.get('snippet','')}"
                prices = _extract_prices(blob)
                rt = _extract_ratings(blob)
                if prices:
                    url = r.get("url", "")
                    # normalise USD→EUR
                    norm = []
                    for p in prices:
                        val = p["value"] * usd_to_eur if p["currency"] == "USD" else p["value"]
                        norm.append(round(val, 2))
                    lo = min(norm)
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        src = {
                            "title": r.get("title", "")[:120],
                            "url": url,
                            "prices_eur": sorted(set(norm))[:5],
                            "low_eur": lo,
                        }
                        if rt.get("rating") is not None:
                            src["rating"] = rt["rating"]
                            src["reviews"] = rt.get("reviews")
                        sources.append(src)
                    all_prices.extend(norm)
                elif rt.get("rating") is not None and r.get("url") not in seen_urls:
                    # source sans prix mais avec une note → on la garde pour les avis
                    seen_urls.add(r.get("url"))
                    sources.append({"title": r.get("title", "")[:120], "url": r.get("url", ""),
                                    "prices_eur": [], "rating": rt["rating"], "reviews": rt.get("reviews")})

        if not all_prices:
            return {
                "success": True, "query": query, "found_prices": 0,
                "message": "Aucun prix détecté automatiquement. Affinez la requête (modèle/référence précise) "
                           "ou consultez les sources manuellement.",
                "sources": sources,
            }

        all_prices.sort()
        n0 = len(all_prices)
        # Médiane brute = ancre robuste
        median0 = all_prices[n0 // 2] if n0 % 2 else (all_prices[n0 // 2 - 1] + all_prices[n0 // 2]) / 2
        # Filtrer les valeurs ABERRANTES autour de la médiane (accessoires, prix /mois,
        # lots, abonnements) qui faussent le prix de revient. On garde le cluster réel.
        filtered = [p for p in all_prices if median0 * 0.35 <= p <= median0 * 2.8] or all_prices
        filtered.sort()
        outliers_removed = n0 - len(filtered)
        n = len(filtered)
        median = filtered[n // 2] if n % 2 else round((filtered[n // 2 - 1] + filtered[n // 2]) / 2, 2)
        lo, hi = filtered[0], filtered[-1]
        # Prix de revient conseillé = 1er quartile du cluster réel (bon prix d'achat)
        cost_basis = round(filtered[max(0, n // 4)], 2)
        spread_pct = round((hi - lo) / lo * 100, 1) if lo else 0
        # Prix de vente conseillé selon marge cible (marge sur PV)
        margins = {}
        for mlabel, mpct in [("basic", max(15, target_margin - 10)),
                             ("standard", target_margin),
                             ("premium", target_margin + 12)]:
            sell = round(cost_basis / (1 - mpct / 100), 2)
            margins[mlabel] = {"margin_pct": round(mpct, 1), "sell_price_ht": sell,
                               "profit": round(sell - cost_basis, 2)}

        # Nettoie l'affichage des sources : ne garde que les prix dans la bande
        # crédible (cohérents avec le cluster), pour ne montrer que de l'info vérifiée.
        band_lo, band_hi = median0 * 0.35, median0 * 2.8
        clean_sources = []
        for s in sources:
            kept = [p for p in s.get("prices_eur", []) if band_lo <= p <= band_hi]
            if kept:
                clean_sources.append({**s, "prices_eur": kept, "low_eur": min(kept)})
            elif s.get("rating") is not None:
                clean_sources.append({**s, "prices_eur": []})  # source avis-seule
        sources = clean_sources or sources

        # ── Avis agrégés (note /5 pondérée par le nb d'avis) ──────────────────
        rated = [s for s in sources if s.get("rating") is not None]
        reviews_block = None
        if rated:
            tw = sum(s.get("reviews") or 1 for s in rated)
            avg_rating = round(sum(s["rating"] * (s.get("reviews") or 1) for s in rated) / tw, 2)
            total_reviews = sum(s.get("reviews") or 0 for s in rated)
            reviews_block = {"average_rating": avg_rating, "rating_out_of": 5,
                             "total_reviews": total_reviews, "rated_sources": len(rated)}

        # ── Fiabilité de l'estimation (information toujours vérifiée) ──────────
        if n >= 5 and spread_pct < 180:
            confidence, conf_msg = "élevée", "Estimation fiable (plusieurs prix concordants)."
        elif n >= 3 and spread_pct < 350:
            confidence, conf_msg = "moyenne", "Estimation indicative — recoupez avec 1-2 fournisseurs."
        else:
            confidence, conf_msg = "faible", ("Peu de prix fiables ou trop dispersés — "
                                              "VÉRIFIEZ MANUELLEMENT via les sources avant de chiffrer.")

        return {
            "success": True,
            "query": query,
            "found_prices": n0,
            "prices_analyzed": n,
            "outliers_removed": outliers_removed,
            "confidence": confidence,
            "market": {
                "min_eur": lo, "median_eur": median, "max_eur": hi,
                "spread_pct": spread_pct,
            },
            "recommended_cost_basis_eur": cost_basis,
            "recommended_sell": margins,
            "reviews": reviews_block,
            "sources": sources[:10],
            "advice": (f"Marché {lo:.0f}–{hi:.0f}€ (médiane {median:.0f}€, {n} prix retenus, "
                       f"{outliers_removed} écartés). Achat conseillé ≈ {cost_basis:.0f}€ HT → "
                       f"revente ~{margins['standard']['sell_price_ht']:.0f}€ HT ({target_margin:.0f}% de marge). "
                       f"Fiabilité : {confidence}."
                       + (f" Avis : {reviews_block['average_rating']}/5 ({reviews_block['total_reviews']} avis)." if reviews_block else "")
                       + f" {conf_msg}"),
            "disclaimer": "Prix extraits automatiquement du web et filtrés ; toujours à recouper "
                          "avec les sources et vos fournisseurs avant d'engager un devis.",
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_find_products(args: dict) -> dict:
    """
    🛒 Recherche de matériel/produits selon une CONTRAINTE DE BUDGET.
    Ex: 'PC portable bureautique à moins de 500€'. Cherche sur le web, extrait les
    offres dont le prix tient dans le budget, les trie (moins cher / meilleur rapport
    qualité-prix avec les avis) et renvoie une short-list avec sources.
    """
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "Paramètre 'query' requis (ex: 'PC portable bureautique')."}
    max_b = args.get("max_budget")
    max_b = float(max_b) if max_b not in (None, "", 0, "0") else None
    min_b = float(args.get("min_budget", 0) or 0)
    usd_to_eur = float(args.get("usd_to_eur", 0.92))

    # Requêtes orientées budget (meilleures pratiques de recherche d'achat)
    if max_b:
        queries = [f"{query} moins de {int(max_b)}€", f"meilleur {query} pas cher {int(max_b)} euros",
                   f"{query} comparatif prix"]
    else:
        queries = [f"{query} prix comparatif", f"meilleur {query} pas cher", f"{query} acheter prix"]

    offers, seen, all_in = [], set(), []
    try:
        for q in queries:
            res = await _web_search({"query": q, "max_results": 8})
            if not (isinstance(res, dict) and res.get("success")):
                continue
            for r in res.get("results", []):
                blob = f"{r.get('title','')} {r.get('snippet','')}"
                prices = _extract_prices(blob)
                if not prices:
                    continue
                norm = sorted({round(p["value"] * usd_to_eur, 2) if p["currency"] == "USD" else p["value"]
                               for p in prices})
                in_budget = [p for p in norm if p >= min_b and (max_b is None or p <= max_b)]
                if not in_budget:
                    continue
                url = r.get("url", "")
                if url in seen:
                    continue
                seen.add(url)
                rt = _extract_ratings(blob)
                price = min(in_budget)
                all_in.append(price)
                offers.append({
                    "title": r.get("title", "")[:110],
                    "price_eur": price,
                    "all_prices_in_budget": in_budget[:4],
                    "rating": rt.get("rating"),
                    "reviews": rt.get("reviews"),
                    "url": url,
                    "snippet": (r.get("snippet", "") or "")[:170],
                })

        if not offers:
            return {"success": True, "query": query, "max_budget": max_b, "count": 0,
                    "message": (f"Aucune offre détectée sous {int(max_b)}€." if max_b else "Aucune offre détectée.")
                               + " Élargissez le budget ou précisez le produit.",
                    "offers": []}

        # Tri : prix croissant (le moins cher d'abord). Meilleur rapport qualité/prix
        # = note élevée parmi les moins chers.
        offers.sort(key=lambda o: o["price_eur"])
        rated = [o for o in offers if o.get("rating")]
        best_value = None
        if rated:
            best_value = max(rated, key=lambda o: (o["rating"] or 0) - (o["price_eur"] / (max_b or max(all_in) or 1)))

        all_in.sort()
        return {
            "success": True,
            "query": query,
            "max_budget": max_b,
            "min_budget": min_b,
            "count": len(offers),
            "price_range_in_budget": {"min": all_in[0], "max": all_in[-1]} if all_in else None,
            "cheapest": offers[0],
            "best_value": best_value,
            "offers": offers[:10],
            "advice": (f"{len(offers)} offre(s) trouvée(s)"
                       + (f" sous {int(max_b)}€" if max_b else "")
                       + f" : de {all_in[0]:.0f}€ à {all_in[-1]:.0f}€. "
                       + (f"Le moins cher : {offers[0]['title'][:50]} à {offers[0]['price_eur']:.0f}€. " if offers else "")
                       + (f"Meilleur rapport qualité/prix : {best_value['title'][:45]} "
                          f"({best_value['rating']}/5, {best_value['price_eur']:.0f}€)." if best_value else "")),
            "disclaimer": "Offres extraites du web (prix variables) ; vérifiez sur les sources avant achat.",
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_price_recommendation(args: dict) -> dict:
    """
    💰 Recommande un prix de vente compétitif à partir d'un coût d'achat, selon
    les marges-cibles par segment (meilleures pratiques commerciales IT).
    """
    cost = args.get("cost")
    if cost is None:
        return {"error": "Paramètre 'cost' (coût d'achat HT) requis."}
    cost = float(cost)
    client_type = args.get("client_type", "pme")
    category = (args.get("category") or "").lower()

    # Marges-cibles indicatives (marge sur PV) selon segment & nature
    base = {"mairie": 22, "pme": 30, "asso": 18, "particulier": 35, "autre": 28}.get(client_type, 30)
    # Le matériel se marge moins que le service/conseil
    if any(k in category for k in ("matériel", "materiel", "hardware", "licence", "logiciel")):
        base -= 8
    elif any(k in category for k in ("conseil", "audit", "sécurité", "securite", "formation", "service", "support")):
        base += 8
    base = max(10, min(base, 60))

    tiers = {}
    for label, delta in [("basic", -8), ("standard", 0), ("premium", +12)]:
        m = max(8, base + delta)
        sell = round(cost / (1 - m / 100), 2)
        tiers[label] = {"margin_pct": round(m, 1), "sell_price_ht": sell,
                        "sell_price_ttc": round(sell * 1.2, 2), "profit": round(sell - cost, 2)}
    return {
        "success": True, "cost_ht": cost, "client_type": client_type,
        "category": args.get("category", ""),
        "recommended": tiers,
        "advice": f"Pour un coût de {cost:.0f}€ HT, prix de vente conseillé ~{tiers['standard']['sell_price_ht']:.0f}€ HT "
                  f"(marge {tiers['standard']['margin_pct']:.0f}%). Présentez 3 paliers pour l'effet d'ancrage.",
    }


def _eur(v) -> str:
    try:
        return f"{float(v):,.2f}".replace(",", " ").replace(".", ",") + " €"
    except Exception:
        return f"{v} €"


async def execute_billing_generate_proposal(args: dict) -> dict:
    """
    📑 Génère une PROPOSITION COMMERCIALE structurée et persuasive depuis un devis
    (meilleures pratiques : résumé exécutif, solution, valeur/ROI, TCO, garanties,
    appel à l'action). Sortie Markdown prête à présenter / exporter en PDF.
    """
    quote_id = (args.get("quote_id") or "").strip()
    if not quote_id:
        return {"error": "Paramètre 'quote_id' requis."}
    try:
        quote = db.billing_quote_get(quote_id)
        if not quote:
            return {"error": "Devis introuvable"}
        client = db.billing_client_get(quote["client_id"]) or {}
        import json as _json
        items = quote.get("items_json")
        items = _json.loads(items) if isinstance(items, str) else (items or [])

        ctype = client.get("client_type", "pme")
        formality = {"mairie": "vouvoiement institutionnel", "asso": "chaleureux et engagé",
                     "pme": "professionnel et orienté ROI", "particulier": "simple et rassurant"}.get(ctype, "professionnel")
        cname = client.get("name", "le client")

        # Regrouper par catégorie
        by_cat = {}
        for it in items:
            by_cat.setdefault(it.get("category", "Prestations"), []).append(it)

        total_ht = float(quote.get("total_ht", 0))
        total_ttc = float(quote.get("total_ttc", 0))
        prev = float(client.get("previous_amount") or 0)

        md = []
        md.append(f"# Proposition commerciale — {cname}")
        md.append(f"**Réf. devis :** {quote.get('number','')}  ·  **Date :** {quote.get('created_at','')[:10]}  ·  "
                  f"**Validité :** {quote.get('valid_until') or '30 jours'}\n")

        # 1. Résumé exécutif
        md.append("## 1. Votre contexte et vos enjeux")
        need = quote.get("need_analysis") or "Modernisation et fiabilisation de votre système d'information."
        md.append(f"{need}\n")
        md.append(f"Cette proposition répond à vos besoins avec une approche {formality}, "
                  "centrée sur la disponibilité, la sécurité et la maîtrise des coûts.\n")

        # 2. Solution proposée
        md.append("## 2. Notre solution")
        for cat, its in by_cat.items():
            md.append(f"### {cat}")
            for it in its:
                qty = it.get("qty", 1)
                label = it.get("label") or it.get("name", "Prestation")
                line_total = it.get("total", it.get("unit_price", 0) * qty)
                desc = it.get("description", "")
                md.append(f"- **{label}**{f' ×{qty}' if qty and qty != 1 else ''} — {_eur(line_total)} HT"
                          + (f"  \n  _{desc}_" if desc else ""))
            md.append("")

        # 3. Valeur & bénéfices
        md.append("## 3. Bénéfices pour vous")
        benefits = [
            "🛡️ **Sécurité renforcée** : protection des données, sauvegardes vérifiées, conformité RGPD.",
            "⏱️ **Disponibilité** : interventions rapides, supervision proactive, moins d'interruptions.",
            "💶 **Coûts maîtrisés** : forfaits clairs, pas de mauvaise surprise, budget prévisible.",
            "🤝 **Interlocuteur unique** : un partenaire de confiance, réactif et de proximité.",
        ]
        md.extend(benefits)
        md.append("")

        # 4. Investissement + comparaison
        md.append("## 4. Votre investissement")
        md.append(f"- **Total HT :** {_eur(total_ht)}")
        md.append(f"- **TVA ({quote.get('tva_rate',20)}%) :** {_eur(total_ttc - total_ht)}")
        md.append(f"- **Total TTC :** **{_eur(total_ttc)}**\n")
        if prev > 0:
            diff = prev - total_ttc
            if diff > 0:
                md.append(f"> 💡 **Économie vs votre prestataire actuel ({client.get('previous_provider','')}) : "
                          f"{_eur(diff)}/an** ({diff/prev*100:.0f}%), à service supérieur.\n")
            else:
                md.append(f"> 💎 Pour un investissement comparable, vous gagnez en sécurité, réactivité et conformité.\n")

        # 5. Garanties / engagement
        md.append("## 5. Nos engagements")
        md.append("- ✅ Devis ferme, sans frais cachés.\n- ✅ Intervention par des techniciens certifiés.\n"
                  "- ✅ Garantie de bon fonctionnement et accompagnement au changement.\n"
                  "- ✅ Réversibilité : vos données vous appartiennent.\n")

        # 6. Appel à l'action
        md.append("## 6. Prochaine étape")
        md.append("Pour démarrer, il vous suffit de **valider cette proposition** (retour signé ou accord par email). "
                  "Nous planifions alors un point de lancement sous 5 jours ouvrés.\n")
        contact = client.get("contact_name", "")
        md.append(f"_Nous restons à votre disposition{', ' + contact if contact else ''} pour tout échange._")

        proposal = "\n".join(md)
        return {
            "success": True,
            "quote_number": quote.get("number"),
            "client": cname,
            "proposal_markdown": proposal,
            "word_count": len(proposal.split()),
            "hint": "Utilisez billing_quote_pdf pour un PDF, ou copiez ce Markdown dans un document.",
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_tco_analysis(args: dict) -> dict:
    """
    📊 Analyse du coût total de possession (TCO) sur N années + ROI vs alternative.
    Best practice IT pour justifier un investissement (achat vs location/cloud).
    """
    try:
        years = int(args.get("years", 3))
        upfront = float(args.get("upfront_cost", 0))          # matériel/setup initial
        monthly = float(args.get("monthly_cost", 0))          # support/licences récurrents
        alt_monthly = float(args.get("alternative_monthly", 0))  # solution comparée (ex: cloud)
        alt_upfront = float(args.get("alternative_upfront", 0))
        downtime_hours_year = float(args.get("downtime_hours_year_saved", 0))
        hourly_value = float(args.get("hourly_value", 50))    # coût horaire d'un arrêt

        months = years * 12
        tco = round(upfront + monthly * months, 2)
        alt_tco = round(alt_upfront + alt_monthly * months, 2)
        savings = round(alt_tco - tco, 2) if alt_tco else 0
        # Valeur du temps d'arrêt évité
        productivity_gain = round(downtime_hours_year * hourly_value * years, 2)
        net_benefit = round(savings + productivity_gain, 2)
        roi_pct = round((net_benefit / tco * 100), 1) if tco > 0 else 0

        breakdown = []
        for y in range(1, years + 1):
            breakdown.append({"year": y, "cumulative_tco": round(upfront + monthly * 12 * y, 2)})

        return {
            "success": True,
            "years": years,
            "tco_total": tco,
            "tco_yearly_avg": round(tco / years, 2) if years else tco,
            "breakdown_per_year": breakdown,
            "alternative_tco": alt_tco,
            "savings_vs_alternative": savings,
            "productivity_value": productivity_gain,
            "net_benefit": net_benefit,
            "roi_pct": roi_pct,
            "advice": (f"TCO sur {years} ans : {tco:.0f}€"
                       + (f" vs {alt_tco:.0f}€ pour l'alternative (économie {savings:.0f}€)." if alt_tco else ".")
                       + (f" Bénéfice net estimé {net_benefit:.0f}€ (ROI {roi_pct:.0f}%)." if net_benefit else "")),
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_invoice_create(args: dict) -> dict:
    """🧾 Crée une facture, optionnellement depuis un devis accepté (from_quote_id)."""
    try:
        from_quote = (args.get("from_quote_id") or "").strip()
        data = dict(args)
        if from_quote:
            q = db.billing_quote_get(from_quote)
            if not q:
                return {"error": "Devis source introuvable"}
            import json as _json
            its = q.get("items_json")
            data.update({
                "client_id": q["client_id"], "quote_id": q["id"],
                "title": q.get("title", "Facture"),
                "total_ht": q.get("total_ht", 0), "tva_rate": q.get("tva_rate", 20),
                "total_ttc": q.get("total_ttc", 0),
                "items": _json.loads(its) if isinstance(its, str) else (its or []),
            })
        if not data.get("client_id"):
            return {"error": "client_id requis (ou from_quote_id)."}
        inv = db.billing_invoice_create(data)
        return {"success": True, "message": f"Facture {inv['number']} créée ({_eur(inv['total_ttc'])} TTC).",
                "invoice": inv}
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_invoice_list(args: dict) -> dict:
    """Liste les factures (filtrable par client_id / status). Signale les retards."""
    try:
        invs = db.billing_invoice_list(args.get("client_id"), args.get("status"))
        overdue = [i for i in invs if i.get("is_overdue")]
        unpaid = sum(float(i["total_ttc"]) - float(i.get("amount_paid", 0))
                     for i in invs if i["status"] in ("sent", "partial", "overdue"))
        return {"success": True, "count": len(invs), "invoices": invs,
                "overdue_count": len(overdue), "total_unpaid_ttc": round(unpaid, 2)}
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_invoice_mark_paid(args: dict) -> dict:
    """Marque une facture payée (totalement ou partiellement)."""
    iid = (args.get("invoice_id") or "").strip()
    if not iid:
        return {"error": "Paramètre 'invoice_id' requis."}
    try:
        inv = db.billing_invoice_get(iid)
        if not inv:
            return {"error": "Facture introuvable"}
        amount = args.get("amount")
        total = _finite_amount(inv["total_ttc"], field="total_ttc")
        paid = _finite_amount(amount, field="amount") if amount is not None else total
        if paid <= 0:
            return {"error": "Le montant payé doit être strictement positif."}
        if paid > total:
            return {
                "error": (
                    f"Le montant payé ({_eur(paid)}) dépasse le total de la facture "
                    f"({_eur(total)})."
                )
            }
        status = "paid" if paid >= total - 0.01 else "partial"
        upd = db.billing_invoice_update(iid, {
            "amount_paid": paid, "status": status,
            "payment_method": args.get("payment_method", ""),
            "paid_date": _dt.now().strftime("%Y-%m-%d") if status == "paid" else None,
        })
        return {"success": True, "message": f"Facture {inv['number']} : {status} ({_eur(paid)}).", "invoice": upd}
    except Exception as e:
        return {"error": str(e)}


async def execute_billing_revenue_dashboard(args: dict) -> dict:
    """
    📈 Tableau de bord commercial : CA facturé/encaissé, impayés, MRR/ARR (contrats
    récurrents), taux de conversion des devis, pipeline. Best practice de pilotage.
    """
    try:
        quotes = db.billing_quote_list()
        invoices = db.billing_invoice_list()
        contracts = db.billing_contract_list()

        # Devis : pipeline + taux de conversion
        by_status = {}
        pipeline_value = 0.0
        for q in quotes:
            by_status[q["status"]] = by_status.get(q["status"], 0) + 1
            if q["status"] in ("draft", "sent"):
                pipeline_value += float(q.get("total_ttc", 0))
        decided = by_status.get("accepted", 0) + by_status.get("refused", 0)
        win_rate = round(by_status.get("accepted", 0) / decided * 100, 1) if decided else 0

        # Factures : CA
        invoiced = sum(float(i["total_ttc"]) for i in invoices)
        collected = sum(float(i.get("amount_paid", 0)) for i in invoices)
        unpaid = round(invoiced - collected, 2)
        overdue = round(sum(float(i["total_ttc"]) - float(i.get("amount_paid", 0))
                            for i in invoices if i.get("is_overdue")), 2)

        # Récurrent : MRR / ARR
        mrr = 0.0
        for c in contracts:
            if c.get("status") != "active":
                continue
            amt = float(c.get("amount_ht", 0))
            per = c.get("period", "mois")
            mrr += amt if per == "mois" else (amt / 3 if per == "trimestre" else amt / 12)
        mrr = round(mrr, 2)

        return {
            "success": True,
            "pipeline": {"open_quotes": by_status.get("draft", 0) + by_status.get("sent", 0),
                         "pipeline_value_ttc": round(pipeline_value, 2),
                         "win_rate_pct": win_rate, "quotes_by_status": by_status},
            "revenue": {"invoiced_ttc": round(invoiced, 2), "collected_ttc": round(collected, 2),
                        "unpaid_ttc": unpaid, "overdue_ttc": overdue},
            "recurring": {"mrr_ht": mrr, "arr_ht": round(mrr * 12, 2), "active_contracts":
                          len([c for c in contracts if c.get("status") == "active"])},
            "advice": (f"Taux de conversion {win_rate:.0f}% · Pipeline {pipeline_value:.0f}€ · "
                       f"MRR {mrr:.0f}€ (ARR {mrr*12:.0f}€)"
                       + (f" · ⚠️ {overdue:.0f}€ en retard de paiement." if overdue else ".")),
        }
    except Exception as e:
        return {"error": str(e)}


_ADVANCED_CATALOG = [
    ("Cybersécurité", "EDR / Antivirus managé (par poste/mois)",
     "Protection nouvelle génération supervisée, détection comportementale", "mois", 4, 7, 12, 2, 0.2),
    ("Cybersécurité", "Audit de sécurité & test d'intrusion",
     "Cartographie des risques, scan de vulnérabilités, rapport + plan d'action", "forfait", 900, 1800, 3500, 400, 16),
    ("Cybersécurité", "Pare-feu nouvelle génération (installation + config)",
     "UTM/NGFW, filtrage, VPN, segmentation réseau", "forfait", 600, 1100, 2200, 350, 8),
    ("Cybersécurité", "Sensibilisation phishing (campagne + formation)",
     "Campagnes simulées + formation des utilisateurs, reporting", "forfait", 350, 600, 1200, 120, 6),
    ("Cloud & Sauvegarde", "Sauvegarde externalisée (BaaS, par To/mois)",
     "Sauvegarde chiffrée hors site, tests de restauration, rétention", "mois", 15, 25, 45, 8, 0.5),
    ("Cloud & Sauvegarde", "Migration Microsoft 365 (par utilisateur)",
     "Migration emails/fichiers, configuration, accompagnement", "unité", 25, 45, 80, 12, 0.5),
    ("Cloud & Sauvegarde", "Plan de reprise d'activité (PRA/PCA)",
     "Conception et test d'un plan de continuité, RTO/RPO définis", "forfait", 1200, 2500, 5000, 600, 24),
    ("Conformité", "Mise en conformité RGPD (TPE/PME)",
     "Registre des traitements, politique, mentions, accompagnement DPO", "forfait", 800, 1500, 3000, 350, 14),
    ("Supervision", "Supervision proactive 24/7 (par équipement)",
     "Monitoring, alertes, reporting mensuel, intervention préventive", "mois", 8, 15, 28, 4, 0.3),
    ("Téléphonie", "Téléphonie VoIP (par ligne/mois)",
     "Standard cloud, mobilité, enregistrement, numéros illimités France", "mois", 8, 14, 22, 5, 0.2),
    ("Infrastructure", "Serveur NAS + configuration RAID",
     "Stockage centralisé, partages, sauvegardes, accès distant sécurisé", "forfait", 700, 1300, 2600, 450, 6),
    ("Formation", "Formation cybersécurité utilisateurs (1/2 journée)",
     "Bonnes pratiques, mots de passe, phishing, mobilité", "forfait", 350, 550, 900, 150, 4),
]


async def execute_billing_catalog_enrich(args: dict) -> dict:
    """➕ Ajoute au catalogue les prestations IT modernes (cyber, cloud, RGPD, VoIP…)
    si elles n'y figurent pas déjà (idempotent par nom)."""
    try:
        existing = {s["name"].strip().lower() for s in db.billing_catalog_list()}
        added = []
        for cat, name, desc, unit, pb, ps, pp, cost, hours in _ADVANCED_CATALOG:
            if name.strip().lower() in existing:
                continue
            db.billing_catalog_create({
                "category": cat, "name": name, "description": desc, "unit": unit,
                "price_basic": pb, "price_standard": ps, "price_premium": pp,
                "cost": cost, "time_hours": hours,
            })
            added.append(name)
        return {"success": True, "added_count": len(added), "added": added,
                "message": f"{len(added)} prestation(s) moderne(s) ajoutée(s) au catalogue."
                           if added else "Catalogue déjà à jour."}
    except Exception as e:
        return {"error": str(e)}


_TRADE_CATALOGS = {
    "plomberie": [
        ("Dépannage", "Intervention de dépannage (heure)", "Déplacement + main d'œuvre", "heure", 55, 70, 90, 20, 1),
        ("Installation", "Remplacement de robinetterie", "Fourniture et pose d'un mitigeur", "forfait", 120, 180, 280, 70, 1.5),
        ("Installation", "Installation chauffe-eau", "Pose d'un cumulus + raccordements", "forfait", 350, 550, 800, 250, 4),
        ("Installation", "Remplacement WC", "Dépose ancien + pose neuf", "forfait", 180, 280, 420, 120, 2),
        ("Rénovation", "Réfection salle de bain (forfait)", "Plomberie complète d'une salle de bain", "forfait", 1800, 3200, 5500, 1400, 40),
        ("Urgence", "Recherche et réparation de fuite", "Détection + réparation", "forfait", 150, 250, 400, 60, 2),
        ("Entretien", "Débouchage canalisation", "Furet / haute pression", "forfait", 90, 150, 250, 40, 1.5),
    ],
    "électricité": [
        ("Dépannage", "Intervention électricien (heure)", "Déplacement + main d'œuvre", "heure", 50, 65, 85, 18, 1),
        ("Installation", "Pose de prise / interrupteur", "Fourniture et pose", "unité", 45, 65, 90, 20, 0.5),
        ("Installation", "Tableau électrique neuf", "Remplacement tableau aux normes NF C 15-100", "forfait", 800, 1400, 2200, 600, 10),
        ("Installation", "Pose de luminaire", "Installation et raccordement", "unité", 60, 90, 140, 30, 1),
        ("Mise aux normes", "Diagnostic + mise en sécurité", "Audit installation + corrections", "forfait", 250, 450, 800, 120, 6),
        ("Domotique", "Installation prise connectée / éclairage smart", "Configuration incluse", "forfait", 120, 200, 350, 80, 2),
        ("Borne", "Installation borne de recharge VE", "Pose IRVE + protection", "forfait", 700, 1100, 1800, 500, 6),
    ],
    "peinture": [
        ("Intérieur", "Peinture mur / plafond (m²)", "Préparation + 2 couches", "unité", 18, 28, 40, 8, 0.2),
        ("Intérieur", "Peinture d'une pièce (forfait)", "Murs + plafond, pièce 12 m²", "forfait", 350, 550, 850, 200, 12),
        ("Préparation", "Rebouchage / ponçage / enduit", "Préparation des supports", "heure", 35, 45, 60, 10, 1),
        ("Extérieur", "Ravalement de façade (m²)", "Nettoyage + traitement + peinture", "unité", 35, 55, 85, 20, 0.5),
        ("Décoration", "Pose papier peint / toile (m²)", "Fourniture pose", "unité", 22, 35, 55, 12, 0.3),
        ("Boiserie", "Peinture portes / boiseries", "Laquage", "unité", 60, 95, 150, 30, 1.5),
    ],
    "menuiserie": [
        ("Pose", "Pose de porte intérieure", "Fourniture et pose bloc-porte", "unité", 180, 280, 420, 120, 2),
        ("Pose", "Pose de fenêtre / baie", "Dépose + pose menuiserie", "unité", 350, 550, 900, 250, 4),
        ("Sur mesure", "Meuble sur mesure (devis)", "Conception, fabrication, pose", "forfait", 800, 1600, 3500, 600, 30),
        ("Agencement", "Pose de placard / dressing", "Sur mesure", "forfait", 600, 1100, 2200, 450, 16),
        ("Réparation", "Réparation / ajustement menuiserie", "Main d'œuvre", "heure", 45, 60, 80, 15, 1),
        ("Parquet", "Pose de parquet (m²)", "Pose flottante ou collée", "unité", 25, 40, 65, 14, 0.4),
    ],
    "jardinage": [
        ("Entretien", "Tonte de pelouse (forfait)", "Tonte + ramassage", "forfait", 40, 60, 90, 15, 1.5),
        ("Entretien", "Taille de haie (ml)", "Taille + évacuation", "unité", 8, 14, 22, 4, 0.2),
        ("Création", "Création de massif / plantation", "Conception + plantation", "forfait", 250, 500, 1000, 180, 8),
        ("Élagage", "Élagage / abattage d'arbre", "Selon hauteur, évacuation incluse", "forfait", 150, 350, 800, 100, 4),
        ("Contrat", "Entretien annuel jardin (forfait/mois)", "Passages réguliers", "mois", 80, 140, 250, 50, 3),
        ("Aménagement", "Pose de gazon / terrassement (m²)", "Préparation + pose", "unité", 12, 20, 35, 7, 0.3),
    ],
    "ménage": [
        ("Régulier", "Ménage à domicile (heure)", "Entretien courant", "heure", 22, 28, 38, 12, 1),
        ("Ponctuel", "Grand ménage / remise en état", "Nettoyage approfondi", "forfait", 120, 200, 350, 80, 5),
        ("Fin de chantier", "Nettoyage fin de chantier (m²)", "Après travaux", "unité", 4, 7, 12, 2, 0.1),
        ("Vitres", "Nettoyage de vitres", "Intérieur/extérieur", "heure", 25, 32, 45, 12, 1),
        ("Repassage", "Repassage (heure)", "À domicile", "heure", 20, 26, 34, 10, 1),
        ("Contrat", "Contrat ménage entreprise (forfait/mois)", "Bureaux, locaux", "mois", 300, 600, 1200, 200, 20),
    ],
    "coiffure_esthétique": [
        ("Coiffure", "Coupe femme + brushing", "", "forfait", 30, 45, 70, 8, 1),
        ("Coiffure", "Coupe homme", "", "forfait", 18, 25, 40, 4, 0.5),
        ("Coiffure", "Coloration / mèches", "Produits inclus", "forfait", 45, 70, 120, 20, 1.5),
        ("Esthétique", "Soin du visage", "", "forfait", 40, 60, 95, 15, 1),
        ("Esthétique", "Épilation (forfait)", "", "forfait", 20, 35, 60, 6, 0.5),
        ("Onglerie", "Pose vernis semi-permanent / gel", "", "forfait", 25, 40, 65, 10, 1),
        ("Domicile", "Prestation à domicile (supplément)", "Déplacement", "forfait", 10, 15, 25, 5, 0.3),
    ],
    "photographie": [
        ("Événement", "Reportage mariage (forfait)", "Journée + photos retouchées", "forfait", 900, 1600, 3000, 300, 20),
        ("Studio", "Séance portrait / book", "1h + retouches", "forfait", 120, 220, 400, 40, 3),
        ("Entreprise", "Photos produits (par photo)", "Prise + retouche", "unité", 15, 25, 45, 5, 0.3),
        ("Immobilier", "Reportage immobilier", "Photos HD d'un bien", "forfait", 120, 200, 350, 40, 3),
        ("Vidéo", "Captation vidéo + montage", "Tournage + montage court", "forfait", 400, 800, 1600, 200, 12),
        ("Tirage", "Tirage / album photo", "Impression qualité pro", "unité", 20, 40, 80, 15, 0.5),
    ],
    "web_design": [
        ("Site", "Site vitrine (forfait)", "Design + intégration responsive", "forfait", 800, 1800, 3500, 300, 30),
        ("E-commerce", "Boutique en ligne", "Catalogue + paiement", "forfait", 2000, 4000, 8000, 800, 60),
        ("Identité", "Logo + charte graphique", "Création identité visuelle", "forfait", 350, 800, 1800, 100, 12),
        ("Maintenance", "Maintenance site (forfait/mois)", "MAJ, sauvegardes, sécurité", "mois", 50, 100, 200, 20, 2),
        ("SEO", "Référencement naturel (forfait/mois)", "Optimisation + suivi", "mois", 250, 500, 1000, 100, 8),
        ("Contenu", "Rédaction web (par article)", "SEO-friendly", "unité", 40, 80, 150, 15, 1.5),
        ("Design", "Maquette / UI design (par écran)", "", "unité", 80, 150, 280, 30, 2),
    ],
    "conseil": [
        ("Conseil", "Consultation / audit (jour)", "Analyse + recommandations", "jour", 400, 700, 1200, 100, 7),
        ("Accompagnement", "Accompagnement projet (forfait/mois)", "Suivi récurrent", "mois", 800, 1500, 3000, 200, 15),
        ("Formation", "Formation / atelier (jour)", "Animation, support inclus", "jour", 600, 1000, 1800, 150, 8),
        ("Coaching", "Séance de coaching (heure)", "", "heure", 70, 120, 200, 10, 1),
        ("Étude", "Étude de marché / faisabilité", "Rapport complet", "forfait", 1200, 2500, 5000, 400, 30),
    ],
    "comptabilité": [
        ("Tenue", "Tenue comptable (forfait/mois)", "Saisie, rapprochements", "mois", 90, 180, 350, 40, 4),
        ("Bilan", "Établissement du bilan annuel", "Liasse fiscale", "forfait", 600, 1200, 2500, 250, 20),
        ("Paie", "Gestion de la paie (par bulletin)", "", "unité", 15, 25, 40, 8, 0.3),
        ("Conseil", "Conseil fiscal / social (heure)", "", "heure", 80, 120, 180, 20, 1),
        ("Création", "Accompagnement création d'entreprise", "Statuts, formalités", "forfait", 400, 800, 1500, 150, 10),
    ],
}


async def execute_billing_seed_trade(args: dict) -> dict:
    """
    🧰 Charge dans le catalogue les prestations TYPES d'un métier (hors IT) :
    plomberie, électricité, peinture, menuiserie, jardinage, ménage,
    coiffure_esthétique, photographie, web_design, conseil, comptabilité.
    Permet d'utiliser le module devis/facture pour TOUT métier.
    """
    trade = (args.get("trade") or "").strip().lower().replace("é", "é")
    if trade in ("list", "", "?"):
        return {"success": True, "available_trades": sorted(_TRADE_CATALOGS.keys()),
                "hint": "Appelez billing_seed_trade(trade='plomberie') pour charger un métier."}
    # tolérance d'orthographe simple
    key = next((k for k in _TRADE_CATALOGS if k == trade or k.startswith(trade[:5]) or trade in k), None)
    if not key:
        return {"error": f"Métier inconnu : {trade}. Disponibles : {', '.join(sorted(_TRADE_CATALOGS))}"}
    try:
        existing = {s["name"].strip().lower() for s in db.billing_catalog_list()}
        added = []
        for cat, name, desc, unit, pb, ps, pp, cost, hours in _TRADE_CATALOGS[key]:
            if name.strip().lower() in existing:
                continue
            db.billing_catalog_create({
                "category": cat, "name": name, "description": desc, "unit": unit,
                "price_basic": pb, "price_standard": ps, "price_premium": pp,
                "cost": cost, "time_hours": hours,
            })
            added.append(name)
        return {"success": True, "trade": key, "added_count": len(added), "added": added,
                "message": f"{len(added)} prestation(s) « {key} » ajoutée(s) au catalogue."
                           if added else f"Catalogue « {key} » déjà présent."}
    except Exception as e:
        return {"error": str(e)}
