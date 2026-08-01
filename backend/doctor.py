"""
🩺 Marvin Doctor — auto-diagnostic DÉTERMINISTE (zéro IA, zéro token), inspiré de la
« drift detection » de MEX. Valide toute l'installation et renvoie un SCORE /100 + un
rapport + des correctifs applicables. Idéal pour un déploiement sur PLUSIEURS machines :
chaque install se vérifie elle-même en une seconde.

Barème (comme MEX) : départ 100 ; −10 par erreur, −3 par avertissement, −1 par info.
"""
import os

import database as db
from config import MODEL_PROFILES, DANGEROUS_TOOLS, OLLAMA_URL, DATA_DIR


async def _ollama_installed() -> tuple[bool, set]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            names = set()
            for m in r.json().get("models", []):
                n = m.get("name", "")
                names.add(n)
                if n.endswith(":latest"):
                    names.add(n[:-len(":latest")])
            return True, names
    except Exception:
        return False, set()


async def run_diagnostics() -> dict:
    import tools as _t
    checks = []

    def add(cid, label, level, message, fix=None):
        c = {"id": cid, "label": label, "level": level, "message": message}
        if fix:
            c["fix"] = fix
        checks.append(c)

    toolnames = set(_t.TOOLS_REGISTRY)

    # ── 1. Cohérence des outils (registry == spec) ─────────────────────────────
    try:
        spec = {t["function"]["name"] for t in _t.TOOLS_SPEC}
        if toolnames == spec:
            add("tools_sync", "Outils", "ok", f"{len(toolnames)} outils, registre et specs cohérents.")
        else:
            diff = (toolnames ^ spec)
            add("tools_sync", "Outils", "error", f"Registre ≠ specs ({len(diff)} écart(s)) : {', '.join(list(diff)[:5])}")
    except Exception as e:
        add("tools_sync", "Outils", "error", f"Vérification impossible : {str(e)[:80]}")

    # ── 2. Ollama joignable + modèles installés ────────────────────────────────
    ok, installed = await _ollama_installed()
    if not ok:
        add("ollama", "Ollama", "error", f"Ollama injoignable sur {OLLAMA_URL} — Marvin ne peut pas répondre.")
    else:
        add("ollama", "Ollama", "ok", f"Ollama OK — {len(installed)} modèle(s) installé(s).")
        for prof in ("chat", "agent", "analysis", "vision"):
            mdl = MODEL_PROFILES.get(prof, {}).get("model")
            if mdl and mdl not in installed and (mdl + ":latest") not in installed:
                add(f"model_{prof}", f"Modèle {prof}", "error",
                    f"« {mdl} » (profil {prof}) n'est pas installé.", fix=f"pull:{mdl}")
        if "nomic-embed-text" not in installed:
            add("model_embed", "Embeddings", "warning",
                "« nomic-embed-text » manquant → mémoire/skills/recherche dégradés.", fix="pull:nomic-embed-text")

    # ── 3. Compétences → outils cohérents ──────────────────────────────────────
    if ok:
        try:
            import auto_config
            import local_model_policy
            import local_model_portfolio

            detailed_models = await auto_config._installed_models()
            recommendation = local_model_policy.recommend(
                auto_config.detect_hardware(), detailed_models,
            )
            portfolio = local_model_portfolio.evaluate(recommendation)
            missing_roles = portfolio.get("missing_roles") or []
            if missing_roles:
                add(
                    "local_portfolio", "Portefeuille local", "warning",
                    "Rôle(s) sans modèle local compatible : " + ", ".join(missing_roles),
                )
            else:
                selected = [
                    item.get("selected")
                    for item in recommendation.get("portfolio", {}).values()
                    if item and item.get("selected")
                ]
                add(
                    "local_portfolio", "Portefeuille local", "ok",
                    f"{len(selected)} rôle(s) couverts par des modèles installés et compatibles.",
                )
        except Exception as exc:
            add(
                "local_portfolio", "Portefeuille local", "warning",
                f"Couverture des rôles non vérifiable : {type(exc).__name__}.",
            )

    try:
        import skills
        # v2.517 — seules les compétences ACTIVES peuvent être sélectionnées par le
        # matcher : une compétence désactivée ne peut plus induire le modèle en erreur.
        # Les compter comme des anomalies noyait le diagnostic sous du bruit inerte.
        bad = []
        disabled_bad = 0
        for s in skills.list_skills():
            miss = [t for t in (s.get("tools") or []) if t not in toolnames]
            if not miss:
                continue
            if s.get("enabled"):
                bad.append(f"{s['name']} ({', '.join(miss)})")
            else:
                disabled_bad += 1
        if bad:
            add("skills_tools", "Compétences", "warning",
                f"{len(bad)} compétence(s) active(s) citent un outil inexistant : {'; '.join(bad[:3])}")
        elif disabled_bad:
            add("skills_tools", "Compétences", "ok",
                f"Aucune compétence active fautive ({disabled_bad} désactivée(s) à nettoyer).")
        else:
            add("skills_tools", "Compétences", "ok",
                f"{len(skills.list_skills())} compétence(s), outils tous valides.")
    except Exception as e:
        add("skills_tools", "Compétences", "info", f"Non vérifié : {str(e)[:80]}")

    # ── 3bis. Veille du catalogue de modèles Cloud (v2.524) ─────────────────────
    # Lecture seule : ne déclenche JAMAIS de vérification réseau ici, le Doctor
    # doit rester instantané et déterministe. `model_catalog_watch.status()` lit
    # uniquement le dernier état déjà persisté par le worker de fond.
    try:
        import model_catalog_watch
        watch = model_catalog_watch.status()
        new_models = watch.get("new_models") or []
        if not watch.get("checked"):
            add("model_catalog_watch", "Veille modèles Cloud", "info",
                "Aucune veille effectuée pour le moment (worker pas encore passé).")
        elif new_models:
            names = ", ".join(m["name"] for m in new_models[:5])
            add("model_catalog_watch", "Veille modèles Cloud", "info",
                f"{len(new_models)} modèle(s) Cloud non répertorié(s) détecté(s) : {names}")
        else:
            add("model_catalog_watch", "Veille modèles Cloud", "ok",
                "Catalogue à jour, aucune nouveauté non répertoriée.")
    except Exception as e:
        add("model_catalog_watch", "Veille modèles Cloud", "info", f"Non vérifié : {str(e)[:80]}")

    # ── 4. Documents indexés présents sur le disque ────────────────────────────
    try:
        docs = _t._indexed_docs()
        missing = [d for d in docs if not os.path.exists(d.get("path", ""))]
        if missing:
            add("indexed_docs", "Documents indexés", "warning",
                f"{len(missing)}/{len(docs)} document(s) indexé(s) introuvable(s) sur le disque.", fix="prune_docs")
        elif docs:
            add("indexed_docs", "Documents indexés", "ok", f"{len(docs)} document(s) indexé(s), tous présents.")
    except Exception as e:
        add("indexed_docs", "Documents indexés", "info", f"Non vérifié : {str(e)[:80]}")

    # ── 5. Agendas connectés (abonnements en erreur) ───────────────────────────
    try:
        subs = db.get_setting("calendar_subscriptions") or []
        err = [s for s in subs if s.get("last_error")]
        if err:
            add("cal_subs", "Agendas connectés", "warning",
                f"{len(err)} agenda(s) en erreur : {', '.join(s.get('name', '?') for s in err[:3])}", fix="disable_broken_subs")
        elif subs:
            add("cal_subs", "Agendas connectés", "ok", f"{len(subs)} agenda(s) connecté(s), OK.")
    except Exception:
        pass

    # ── 6. Google Agenda : cohérence de configuration ──────────────────────────
    try:
        sa = os.path.exists(_t._GOOGLE_SA_PATH)
        cal_id = db.get_setting("google_calendar_id")
        if sa and not cal_id:
            add("google", "Google Agenda", "warning",
                "Clé de compte de service présente mais agenda cible (ton email) non défini.")
        elif sa and cal_id:
            add("google", "Google Agenda", "ok", f"Compte de service configuré (agenda : {cal_id}).")
    except Exception:
        pass

    # ── 7. Telegram : cohérence ────────────────────────────────────────────────
    try:
        tg = db.get_setting("telegram_config") or {}
        if tg.get("enabled") and not tg.get("bot_token"):
            add("telegram", "Telegram", "warning", "Telegram activé mais aucun jeton de bot configuré.")
    except Exception:
        pass

    # ── 8. Logo d'en-tête présent ──────────────────────────────────────────────
    try:
        lh = db.get_setting("doc_letterhead") or {}
        if lh.get("logo") and not os.path.exists(lh["logo"]):
            add("letterhead_logo", "En-tête documents", "warning",
                "Le logo d'en-tête est introuvable sur le disque.", fix="clear_logo")
    except Exception:
        pass

    # ── 9. Dossiers de données accessibles en écriture ─────────────────────────
    for sub, lbl in (("", "data"), ("documents_generes", "documents générés"), ("skills", "compétences")):
        p = os.path.join(str(DATA_DIR), sub)
        try:
            os.makedirs(p, exist_ok=True)
            if not os.access(p, os.W_OK):
                add(f"dir_{sub or 'data'}", "Dossiers", "error", f"Dossier « {lbl} » non accessible en écriture.")
        except Exception:
            add(f"dir_{sub or 'data'}", "Dossiers", "error", f"Dossier « {lbl} » inaccessible.")

    # ── 10. Cohérence des outils dangereux (config) ────────────────────────────
    try:
        miss = [t for t in DANGEROUS_TOOLS if t not in toolnames]
        if miss:
            add("dangerous", "Sécurité", "warning",
                f"DANGEROUS_TOOLS cite {len(miss)} outil(s) inexistant(s) : {', '.join(miss[:5])}")
    except Exception:
        pass

    # ── 11. Serveur MCP (v2.103) ────────────────────────────────────────────────
    try:
        import importlib.util as _ilu
        mcp_pkg_ok = _ilu.find_spec("mcp") is not None
        mcp_server_path = os.path.join(os.path.dirname(__file__), "mcp_server.py")
        server_ok = os.path.exists(mcp_server_path)
        if server_ok:
            with open(mcp_server_path, encoding="utf-8") as f:
                compile(f.read(), mcp_server_path, "exec")
        if not mcp_pkg_ok:
            add("mcp", "Serveur MCP", "warning",
                "Le paquet « mcp » n'est pas installé — la page /mcp ne fonctionnera pas. "
                "Corrige avec : .venv\\Scripts\\python -m pip install mcp")
        elif not server_ok:
            add("mcp", "Serveur MCP", "error", "backend/mcp_server.py introuvable.")
        else:
            add("mcp", "Serveur MCP", "ok", "Paquet « mcp » installé, mcp_server.py valide.")
    except SyntaxError as e:
        add("mcp", "Serveur MCP", "error", f"mcp_server.py a une erreur de syntaxe : {str(e)[:100]}")
    except Exception as e:
        add("mcp", "Serveur MCP", "info", f"Non vérifié : {str(e)[:80]}")

    # ── Score ──────────────────────────────────────────────────────────────────
    score = 100
    for c in checks:
        score -= {"error": 10, "warning": 3, "info": 1}.get(c["level"], 0)
    score = max(0, score)
    errors = sum(1 for c in checks if c["level"] == "error")
    warnings = sum(1 for c in checks if c["level"] == "warning")
    fixable = [c for c in checks if c.get("fix") and not c["fix"].startswith("pull:")]
    suggestions = [c["fix"][5:] for c in checks if c.get("fix", "").startswith("pull:")]
    verdict = ("✅ Tout est sain" if score >= 95 else
               "🟡 Quelques points à corriger" if score >= 70 else
               "🔴 Des problèmes à régler")
    return {"score": score, "verdict": verdict, "errors": errors, "warnings": warnings,
            "checks": checks, "fixable": [c["fix"] for c in fixable],
            "pull_suggestions": suggestions}


async def apply_fix(fix_id: str) -> dict:
    """Applique un correctif sûr (jamais destructif sur des données externes sans raison)."""
    import tools as _t
    if fix_id == "prune_docs":
        try:
            import vector_store as vs
        except Exception:
            vs = None
        docs = _t._indexed_docs()
        keep, removed = [], 0
        for d in docs:
            if os.path.exists(d.get("path", "")):
                keep.append(d)
            else:
                removed += 1
                if vs:
                    try:
                        vs.delete_doc_chunks(d.get("id"))
                    except Exception:
                        pass
        _t._save_indexed_docs(keep)
        return {"success": True, "message": f"{removed} document(s) fantôme(s) retiré(s) de l'index."}

    if fix_id == "disable_broken_subs":
        subs = db.get_setting("calendar_subscriptions") or []
        n = 0
        for s in subs:
            if s.get("last_error"):
                s["enabled"] = False
                n += 1
        db.set_setting("calendar_subscriptions", subs)
        return {"success": True, "message": f"{n} agenda(s) en erreur désactivé(s)."}

    if fix_id == "clear_logo":
        lh = db.get_setting("doc_letterhead") or {}
        lh.pop("logo", None)
        db.set_setting("doc_letterhead", lh)
        return {"success": True, "message": "Logo d'en-tête introuvable retiré de la configuration."}

    return {"success": False, "error": "Correctif inconnu ou manuel (ex : installer un modèle)."}
