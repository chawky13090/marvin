"""
Système de SKILLS (compétences) — inspiré de Claude Code & OpenClaw, mais SÛR par conception.

Une skill = un fichier Markdown (frontmatter YAML + instructions en langage naturel). Ce n'est
PAS du code exécutable : elle ne fait qu'AJOUTER une méthode / un playbook au contexte de Marvin,
qu'il applique avec ses OUTILS DÉJÀ VÉRIFIÉS (et leurs confirmations). Donc, contrairement à
OpenClaw (faille RCE CVE-2026-25253, 26 % de skills communautaires vulnérables), une skill ici
ne peut PAS exécuter de code arbitraire → aucune surface d'attaque de ce type.

Stockage : data/skills/*.md (local, inspectable, versionnable avec git).
Sélection : sémantique (embeddings nomic) → la bonne skill se déclenche selon la demande.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import time
import unicodedata

from structured_logging import StructuredJsonlStore, sanitize

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "skills")
_VERSIONS_DIR = os.path.join(_SKILLS_DIR, "_versions")
_STATS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "skills_stats.json")
_emb_cache: dict = {}   # name -> (hash_description, vecteur)


def _dir() -> str:
    os.makedirs(_SKILLS_DIR, exist_ok=True)
    return _SKILLS_DIR


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", (name or "").lower().replace(" ", "-"))[:60] or "skill"


def _parse(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    meta, body = {}, raw
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
    if m:
        fm, body = m.group(1), m.group(2)
        for line in fm.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k in ("tools", "triggers", "related"):
                v = [t.strip() for t in v.strip("[] ").split(",") if t.strip()]
            elif v.lower() in ("true", "false"):
                v = (v.lower() == "true")
            meta[k] = v
    name = meta.get("name") or os.path.splitext(os.path.basename(path))[0]
    # Ressources embarquées (progressive disclosure) : sidecar dossier <fichier>.resources/
    base = os.path.splitext(os.path.basename(path))[0]
    rdir = os.path.join(os.path.dirname(path), base + ".resources")
    resources = []
    if os.path.isdir(rdir):
        try:
            resources = sorted(f for f in os.listdir(rdir) if os.path.isfile(os.path.join(rdir, f)))
        except Exception:
            resources = []
    return {"name": name, "description": meta.get("description", ""),
            "tools": meta.get("tools") if isinstance(meta.get("tools"), list) else [],
            "triggers": meta.get("triggers") if isinstance(meta.get("triggers"), list) else [],
            "related": meta.get("related") if isinstance(meta.get("related"), list) else [],
            "enabled": meta.get("enabled", True) if isinstance(meta.get("enabled", True), bool) else True,
            "body": body.strip(), "file": os.path.basename(path), "resources": resources}


def list_skills() -> list:
    out = []
    try:
        for fn in os.listdir(_dir()):
            if fn.endswith(".md"):
                try:
                    out.append(_parse(os.path.join(_dir(), fn)))
                except Exception:
                    pass
    except Exception:
        pass
    return sorted(out, key=lambda s: s["name"].lower())


def get_skill(name: str) -> dict | None:
    for s in list_skills():
        if s["name"] == name or s["file"] == _safe_name(name) + ".md":
            return s
    return None


def save_skill(name: str, description: str, body: str, tools=None, enabled: bool = True,
               triggers=None, related=None) -> str:
    fn = _safe_name(name)
    path = os.path.join(_dir(), fn + ".md")
    # Versioning : avant d'écraser une compétence existante, on sauvegarde l'ancienne
    # version dans data/skills/_versions/ → permet l'auto-upgrade SANS perte (rollback).
    if os.path.exists(path):
        try:
            os.makedirs(_VERSIONS_DIR, exist_ok=True)
            shutil.copy2(path, os.path.join(_VERSIONS_DIR, f"{fn}.{time.strftime('%Y%m%d-%H%M%S')}.md"))
        except Exception:
            pass
    fm = ["---", f"name: {name}", f"description: {description}",
          f"tools: [{', '.join(tools or [])}]",
          f"triggers: [{', '.join(triggers or [])}]",
          f"related: [{', '.join(related or [])}]",
          f"enabled: {'true' if enabled else 'false'}", "---", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(fm) + (body or "").strip() + "\n")
    _emb_cache.pop(name, None)
    return fn


def delete_skill(name: str) -> bool:
    def _drop_resources():
        try:
            shutil.rmtree(_resources_dir(name), ignore_errors=True)
        except Exception:
            pass
    p = os.path.join(_dir(), _safe_name(name) + ".md")
    if os.path.exists(p):
        os.remove(p)
        _drop_resources()
        return True
    for s in list_skills():
        if s["name"] == name:
            os.remove(os.path.join(_dir(), s["file"]))
            _drop_resources()
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  Parsing robuste du JSON produit par le LLM (compétences)
# ══════════════════════════════════════════════════════════════════════════════

def parse_skill_json(raw: str) -> dict:
    """
    Parse robustement le JSON d'une compétence produite par un LLM local. Les petits
    modèles (qwen2.5) produisent souvent du JSON LÉGÈREMENT invalide : guillemets ou
    sauts de ligne non échappés dans 'body' (Markdown multi-ligne) → json.loads échoue.
    Stratégie : strict d'abord (raw_decode), puis repli TOLÉRANT champ par champ.
    """
    if not raw:
        return {}
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    start = cleaned.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(cleaned, start)
            if isinstance(obj, dict) and obj.get("name"):
                return obj
        except Exception:
            pass

    def _unescape(s: str) -> str:
        return (s or "").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\").strip()

    def _field(key: str):
        m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned, re.DOTALL)
        return m.group(1) if m else None

    def _list(key: str):
        m = re.search(rf'"{key}"\s*:\s*\[(.*?)\]', cleaned, re.DOTALL)
        if not m:
            return []
        return [x.strip().strip('"').strip() for x in m.group(1).split(",") if x.strip().strip('"').strip()]

    name = _field("name")
    if not name:
        return {}
    bm = re.search(r'"body"\s*:\s*"(.*)"\s*[}\],\s]*$', cleaned, re.DOTALL)
    body = bm.group(1) if bm else (_field("body") or "")
    return {
        "name": name.strip(),
        "description": _unescape(_field("description") or ""),
        "triggers": _list("triggers"),
        "tools": _list("tools"),
        "body": _unescape(body),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Statistiques de performance + auto-réparation / auto-upgrade des compétences
# ══════════════════════════════════════════════════════════════════════════════

def _load_stats() -> dict:
    try:
        with open(_STATS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_stats(stats: dict):
    try:
        os.makedirs(os.path.dirname(_STATS_FILE), exist_ok=True)
        with open(_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def record_outcome(name: str, ok: bool, detail: str = "", transcript: str = "") -> dict:
    """Enregistre le résultat d'une exécution de compétence (pour piloter l'auto-upgrade)."""
    if not name:
        return {}
    stats = _load_stats()
    s = stats.get(name) or {"uses": 0, "ok": 0, "fail": 0, "consecutive_fail": 0, "version": 1}
    s["uses"] = s.get("uses", 0) + 1
    if ok:
        s["ok"] = s.get("ok", 0) + 1
        s["consecutive_fail"] = 0
        s["last_outcome"] = "ok"
    else:
        s["fail"] = s.get("fail", 0) + 1
        s["consecutive_fail"] = s.get("consecutive_fail", 0) + 1
        s["last_outcome"] = "fail"
        s["last_error"] = (detail or "")[:600]
        if transcript:
            s["last_transcript"] = transcript[:4000]
    s["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S")
    stats[name] = s
    _save_stats(stats)
    return s


def get_stats(name: str = None):
    stats = _load_stats()
    return stats.get(name, {}) if name else stats


def record_success_trace(name: str, calls: list, query: str = "", max_calls: int = 8):
    """🥇 GOLDEN PATH : mémorise la séquence d'outils d'un run RÉUSSI. On conserve le
    déroulé le plus COURT parmi les succès (moins d'étapes = plus efficace) → réinjecté
    comme exemple few-shot au prochain déclenchement de la compétence."""
    if not name or not calls:
        return
    raw = [{"tool": c.get("tool"), "args": (c.get("args") or "")[:90]}
           for c in calls if c.get("tool")]
    if not raw:
        return
    # v2.123 — un run qui a RÉUSSI malgré une boucle (même outil+args répété plusieurs fois
    # de suite) n'est PAS un déroulé efficace à imiter tel quel — bug réel trouvé sur
    # "migration-poste" (8 appels identiques à win_system_report mémorisés comme "le plus
    # court" faute de ce garde-fou, activement réinjecté comme exemple few-shot pour
    # boucler à nouveau). Dédoublonne les appels consécutifs identiques AVANT de comparer
    # les longueurs — le déroulé dédupliqué (ex. 8 appels → 1) EST le vrai golden path,
    # pas une raison de le rejeter.
    calls = []
    for c in raw:
        if calls and calls[-1] == c:
            continue
        calls.append(c)
    calls = calls[:max_calls]
    if not calls:
        return
    stats = _load_stats()
    s = stats.get(name) or {"uses": 0, "ok": 0, "fail": 0, "consecutive_fail": 0, "version": 1}
    prev = s.get("golden")
    # Garder le plus court (à égalité, le plus récent l'emporte → reste à jour).
    if not prev or len(calls) <= len(prev.get("calls", [])):
        s["golden"] = {"calls": calls, "query": (query or "")[:120],
                       "steps": len(calls), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        stats[name] = s
        _save_stats(stats)


def get_golden_trace(name: str):
    return (_load_stats().get(name) or {}).get("golden")


# ══════════════════════════════════════════════════════════════════════════════
#  Mining proactif — propose de NOUVELLES compétences depuis les tâches récurrentes
# ══════════════════════════════════════════════════════════════════════════════

_SUGGEST_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "skills_suggestions.json")


def _load_suggest_state() -> dict:
    try:
        with open(_SUGGEST_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"dismissed": []}


def _save_suggest_state(state: dict):
    try:
        os.makedirs(os.path.dirname(_SUGGEST_FILE), exist_ok=True)
        with open(_SUGGEST_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def dismiss_suggestion(name: str):
    """Mémorise qu'une suggestion a été refusée → ne plus la reproposer."""
    st = _load_suggest_state()
    d = set(st.get("dismissed", []))
    d.add(_safe_name(name))
    st["dismissed"] = sorted(d)
    _save_suggest_state(st)


async def suggest_skills(generate_fn, messages: list, tool_names=None, max_suggestions: int = 4) -> list:
    """Analyse les demandes récurrentes et propose des compétences NON encore couvertes.
    `generate_fn` : async (str)->str. `messages` : demandes utilisateur récentes."""
    msgs = [m for m in (messages or []) if isinstance(m, str) and m.strip()]
    if len(msgs) < 4:
        return []
    existing = list_skills()
    existing_lines = "\n".join(f"- {s['name']} : {s.get('description','')}" for s in existing)
    dismissed = set(_load_suggest_state().get("dismissed", []))
    tools_hint = ", ".join((tool_names or [])[:120])
    sample = "\n".join(f"- {m}" for m in msgs[:80])
    prompt = (
        "Tu analyses l'historique des demandes faites à l'assistant Marvin pour repérer des "
        "TÂCHES RÉCURRENTES qui gagneraient à devenir des COMPÉTENCES réutilisables. RÉDIGE EN FRANÇAIS.\n\n"
        f"### Demandes récentes de l'utilisateur\n{sample}\n\n"
        f"### Compétences DÉJÀ existantes (NE PAS les redoubler)\n{existing_lines or '(aucune)'}\n\n"
        f"### Outils disponibles\n{tools_hint}\n\n"
        "Propose 2 à 4 NOUVELLES compétences MAX, UNIQUEMENT pour des tâches qui :\n"
        "1) reviennent plusieurs fois OU sont clairement répétables, ET\n"
        "2) ne sont PAS déjà couvertes par une compétence existante.\n"
        "Si rien de pertinent, renvoie une liste vide. Ne force pas.\n"
        "Réponds UNIQUEMENT en JSON, sans texte autour :\n"
        '{"suggestions": [{"name": "nom-court-kebab", "description": "quand l\'utiliser (1 phrase)", '
        '"triggers": ["3-5 expressions déclencheuses"], "tools": ["outil1","outil2"], '
        '"why": "pourquoi c\'est récurrent (1 phrase)", "examples": ["demande réelle 1","demande réelle 2"]}]}'
    )
    try:
        raw = await generate_fn(prompt)
    except Exception:
        return []
    # Parsing BULLETPROOF : les petits modèles renvoient des formes variables
    # ([...], {"suggestions":[...]}, objet seul, plusieurs objets, JSON tronqué…).
    # On parse chaque valeur JSON et on COLLECTE RÉCURSIVEMENT les objets ressemblant
    # à une suggestion (name+description) — où qu'ils soient imbriqués.
    cleaned = re.sub(r"```(?:json)?", "", raw or "").strip()
    cands = []

    def _collect(node):
        if isinstance(node, dict):
            if node.get("name") and node.get("description"):
                cands.append(node)
            else:
                for v in node.values():
                    _collect(v)
        elif isinstance(node, list):
            for v in node:
                _collect(v)

    _dec = json.JSONDecoder()
    _i, _n = 0, len(cleaned)
    while _i < _n:
        if cleaned[_i] not in "{[":
            _i += 1
            continue
        try:
            _obj, _end = _dec.raw_decode(cleaned, _i)
        except Exception:
            _i += 1
            continue
        _i = _end
        _collect(_obj)
    existing_names = {s["name"] for s in existing}
    valid_tools = set(tool_names or [])
    out = []
    for c in (cands or []):
        if not isinstance(c, dict) or not c.get("name"):
            continue
        nm = _safe_name(c.get("name"))
        if nm in dismissed or c["name"] in existing_names or nm in {_safe_name(n) for n in existing_names}:
            continue
        # Déjà couvert par une compétence existante ? On n'écarte que sur une
        # correspondance FORTE (seuil strict 0.80) — sinon un vague air de famille
        # (« devis » ↔ « rapport ») tuerait des suggestions pourtant légitimes.
        probe = (c.get("description", "") + " " + " ".join(c.get("triggers") or []))
        try:
            if await match(probe, threshold=0.80):
                continue
        except Exception:
            pass
        out.append({
            "name": c["name"],
            "description": c.get("description", ""),
            "triggers": [str(t)[:40] for t in (c.get("triggers") or [])][:6],
            "tools": [t for t in (c.get("tools") or []) if (not valid_tools or t in valid_tools)][:8],
            "why": c.get("why", ""),
            "examples": [str(e)[:120] for e in (c.get("examples") or [])][:3],
        })
        if len(out) >= max_suggestions:
            break
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  Ressources de compétence (progressive disclosure) — fichiers de référence
#  embarqués (modèles, tables de prix, check-lists…), chargés à la demande.
#  Sidecar : data/skills/<safe-name>.resources/  (ignoré par le scan *.md).
# ══════════════════════════════════════════════════════════════════════════════

def _resources_dir(name: str, create: bool = False) -> str:
    d = os.path.join(_dir(), _safe_name(name) + ".resources")
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _safe_resource_name(filename: str) -> str:
    """Empêche toute traversée de chemin ; garde un nom de fichier simple."""
    fn = os.path.basename((filename or "").strip().replace("\\", "/"))
    fn = re.sub(r"[^A-Za-z0-9._\- ]", "", fn).strip()
    return fn[:80]


def list_resources(name: str) -> list:
    d = _resources_dir(name)
    out = []
    try:
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                out.append({"name": f, "size": os.path.getsize(p), "path": os.path.abspath(p)})
    except Exception:
        pass
    return out


def resource_path(name: str, filename: str) -> str | None:
    fn = _safe_resource_name(filename)
    if not fn:
        return None
    p = os.path.join(_resources_dir(name), fn)
    return os.path.abspath(p) if os.path.exists(p) else None


def read_resource(name: str, filename: str, max_chars: int = 4000) -> str | None:
    """Lit une ressource TEXTE (renvoie None si binaire/illisible)."""
    p = resource_path(name, filename)
    if not p:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read(max_chars)
    except Exception:
        return None


def save_resource(name: str, filename: str, content) -> dict:
    """Crée/écrase une ressource. `content` = str (texte) ou bytes (binaire)."""
    fn = _safe_resource_name(filename)
    if not fn:
        return {"success": False, "error": "Nom de fichier invalide."}
    d = _resources_dir(name, create=True)
    p = os.path.join(d, fn)
    try:
        if isinstance(content, bytes):
            with open(p, "wb") as f:
                f.write(content)
        else:
            with open(p, "w", encoding="utf-8") as f:
                f.write(content or "")
        return {"success": True, "name": fn, "size": os.path.getsize(p)}
    except Exception as e:
        return {"success": False, "error": str(e)[:160]}


def delete_resource(name: str, filename: str) -> bool:
    p = resource_path(name, filename)
    if not p:
        return False
    try:
        os.remove(p)
        # nettoyer le dossier s'il est vide
        try:
            os.rmdir(_resources_dir(name))
        except OSError:
            pass
        return True
    except Exception:
        return False


def resources_prompt_block(name: str, inline_each: int = 1200, inline_total: int = 3000) -> str:
    """Construit le bloc à injecter dans le prompt quand une compétence a des ressources :
    contenu INLINE des petites ressources texte (fiable pour petit modèle) + liste des
    chemins pour lecture à la demande via `file_read` (gros fichiers / binaires)."""
    res = list_resources(name)
    if not res:
        return ""
    inline_parts, listed, used = [], [], 0
    for r in res:
        txt = read_resource(name, r["name"], max_chars=inline_each + 1) if r["size"] <= 20000 else None
        if txt is not None and used < inline_total:
            chunk = txt[:inline_each]
            if len(txt) > inline_each:
                chunk += "…(tronqué, lire le fichier en entier avec file_read)"
            inline_parts.append(f"— {r['name']} —\n{chunk}")
            used += len(chunk)
        else:
            listed.append(r)
    block = "\n\n### 📦 Ressources de cette compétence\n"
    if inline_parts:
        block += "Contenu de référence (utilise-le directement) :\n" + "\n".join(inline_parts) + "\n"
    if listed:
        block += ("Fichiers volumineux/binaires à lire à la demande avec `file_read(path=...)` si besoin :\n"
                  + "\n".join(f"- {r['name']} → {r['path']}" for r in listed) + "\n")
    return block


def list_versions(name: str) -> list:
    """Versions archivées d'une compétence (du plus récent au plus ancien)."""
    fn = _safe_name(name)
    try:
        files = [f for f in os.listdir(_VERSIONS_DIR) if f.startswith(fn + ".") and f.endswith(".md")]
    except Exception:
        return []
    return sorted(files, reverse=True)


def rollback_skill(name: str, version_file: str) -> bool:
    """Restaure une version archivée d'une compétence."""
    fn = _safe_name(name)
    src = os.path.join(_VERSIONS_DIR, version_file)
    if not os.path.exists(src) or not version_file.startswith(fn + "."):
        return False
    parsed = _parse(src)
    save_skill(parsed["name"], parsed["description"], parsed["body"], parsed["tools"],
               parsed.get("enabled", True), triggers=parsed.get("triggers"), related=parsed.get("related"))
    return True


async def upgrade_skill(name: str, generate_fn, reason: str = "", transcript: str = "",
                        tool_names=None) -> dict:
    """
    AUTO-UPGRADE : ré-écrit une compétence pour la rendre PLUS FORTE après un échec.
    Le LLM reçoit la compétence actuelle + le contexte de l'échec (outils en erreur,
    trace) et produit une version corrigée/optimisée. L'ancienne version est archivée
    automatiquement (save_skill) → rollback possible. `generate_fn` : async (str)->str.
    """
    sk = get_skill(name)
    if not sk:
        return {"success": False, "error": "Compétence introuvable."}
    tools_hint = ", ".join((tool_names or [])[:120])
    prompt = (
        "Tu es l'auto-réparateur de compétences de l'assistant Marvin. Une compétence = "
        "une MÉTHODE en langage naturel que Marvin exécute avec SES OUTILS (pas de code).\n"
        "La compétence ci-dessous a ÉCHOUÉ. Produis une VERSION AMÉLIORÉE, PLUS ROBUSTE et "
        "PLUS EFFICACE, qui corrige la cause de l'échec. RÉDIGE EN FRANÇAIS (noms d'outils en anglais).\n\n"
        f"### Compétence actuelle (nom: {sk['name']})\n"
        f"Description: {sk.get('description','')}\n"
        f"Outils: {', '.join(sk.get('tools') or [])}\n"
        f"Corps:\n{sk.get('body','')}\n\n"
        f"### Contexte de l'échec\n{reason}\n{transcript[:2500]}\n\n"
        f"### Outils réellement disponibles (choisis les BONS)\n{tools_hint}\n\n"
        "RÈGLES D'AMÉLIORATION :\n"
        "- Identifie POURQUOI ça a échoué et corrige-le concrètement (mauvais outil, mauvais "
        "paramètre, étape manquante, ordre…). Ex : une cmdlet PowerShell (Get-…) doit passer par "
        "`pc_run_powershell`, pas `pc_run_command`.\n"
        "- Chaque étape indique l'OUTIL EXACT (entre backticks) et des paramètres concrets. "
        "Marvin AGIT lui-même (jamais « ouvrez tel panneau »).\n"
        "- Ajoute une étape de VÉRIFICATION et des replis si une étape échoue. Garde le même 'name'.\n"
        "- Sois plus complet que la version précédente, sans devenir bavard.\n\n"
        "Réponds UNIQUEMENT par un JSON valide, sans texte ni balises de code :\n"
        '{"name": "' + sk['name'] + '", "description": "quand l\'utiliser (1 phrase)", '
        '"triggers": ["3 à 6 déclencheurs"], "tools": ["outil1","outil2"], '
        '"body": "## Objectif\\n...\\n## Étapes\\n1. ...\\n## Vérification\\n...\\n## Pièges à éviter\\n- ..."}'
    )
    try:
        raw = await generate_fn(prompt)
    except Exception as e:
        return {"success": False, "error": f"Upgrade impossible (LLM) : {str(e)[:160]}"}
    data = parse_skill_json(raw)
    if not data.get("name") or not (data.get("body") or "").strip():
        return {"success": False, "error": "Upgrade : JSON illisible.", "raw": (raw or "")[:300]}

    # Ne garder que des outils réellement existants ; conserver ceux d'avant en repli.
    valid = set(tool_names or [])
    new_tools = [t for t in (data.get("tools") or []) if (not valid or t in valid)] or sk.get("tools") or []

    # Le déclenchement (triggers + description) sert au MATCHING et a été choisi
    # délibérément → on le PRÉSERVE. Un upgrade corrige la MÉTHODE (body + tools),
    # pas la façon dont la compétence se déclenche (sinon on dégrade la détection).
    # On ne récupère de nouveaux triggers QUE si l'originale n'en avait aucun.
    _bad = ("déclencheur", "trigger", "expression", "kebab", "...", "à 6", "exemple",
            "quand l'utiliser", "quand l utiliser")
    new_trigs = sk.get("triggers") or [
        t for t in (data.get("triggers") or [])
        if t and len(t) > 2 and not any(b in t.lower() for b in _bad)]
    new_desc = sk.get("description") or data.get("description") or ""

    stats = _load_stats()
    s = stats.get(name) or {}
    new_ver = int(s.get("version", 1)) + 1
    # save_skill archive automatiquement l'ancienne version (rollback possible)
    save_skill(data["name"], new_desc, data.get("body"), new_tools, True,
               triggers=new_trigs, related=sk.get("related"))
    s["version"] = new_ver
    s["consecutive_fail"] = 0
    s["last_outcome"] = "upgraded"
    s["last_upgrade"] = time.strftime("%Y-%m-%d %H:%M:%S")
    stats[name] = s
    _save_stats(stats)
    log_learning_event("upgrade", name, reason or "Échec d'outil détecté",
                        before=sk.get("body"), after=data.get("body"),
                        metadata={"version": new_ver})
    return {"success": True, "version": new_ver, "skill": get_skill(data["name"])}


def _cos(a, b) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


_STOP = {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "aux", "ce", "cet", "cette",
         "mon", "ma", "mes", "est", "sont", "plus", "pas", "sur", "dans", "pour", "avec", "que", "qui",
         "son", "sa", "ses", "the", "via", "par", "aide", "moi", "mon", "fait", "faire", "veux", "dois",
         # v2.190 — les mots interrogatifs ne constituent jamais un ancrage métier. « quelles »
         # était commun à « quelles conditions de certification PASSI » et au trigger
         # « quelles machines sont actives », ce qui lançait à tort un audit réseau.
         "quel", "quels", "quelle", "quelles", "quoi", "comment", "pourquoi", "quand", "combien"}


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _keywords(text: str) -> set:
    import re as _re
    return {w for w in _re.findall(r"[a-z0-9]+", _norm(text)) if len(w) > 3 and w not in _STOP}


async def match(query: str, threshold: float = 0.72) -> dict | None:
    """Meilleure skill ACTIVÉE correspondant à la demande. Matcher HYBRIDE : score sémantique
    (embeddings) + bonus lexical (mots-clés communs nom/description ↔ demande) → discrimine
    bien mieux entre compétences IT proches (ex : « écran bleu » vs « pc lent »)."""
    skills = [s for s in list_skills() if s.get("enabled")]
    if not skills or not (query or "").strip():
        return None
    qkw = _keywords(query)
    try:
        import vector_store as vs
        qv = await vs.embed(query)
    except Exception:
        qv = None
    best, best_score = None, 0.0
    runner_up, runner_up_score = None, 0.0
    for s in skills:
        skw = _keywords(s["name"].replace("-", " ") + " " + (s["description"] or "")) | _keywords(" ".join(s.get("triggers") or []))
        overlap = len(qkw & skw)
        # v2.190 — l'embedding classe des compétences déjà plausibles, il ne donne plus
        # à lui seul l'autorisation d'activer une procédure outillée. C'est ce qui avait
        # associé « conditions de certification » à diagnostic-vpn sans aucun mot commun.
        nq = _norm(query)
        trig = 0.25 if any(_norm(t) and _norm(t) in nq for t in (s.get("triggers") or [])) else 0.0
        if overlap == 0 and trig == 0.0:
            continue
        sv = None
        if qv:
            h = hashlib.md5((s["description"] or s["name"]).encode("utf-8")).hexdigest()
            cached = _emb_cache.get(s["name"])
            if cached and cached[0] == h:
                sv = cached[1]
            else:
                try:
                    sv = await vs.embed(s["description"] or s["name"])
                except Exception:
                    sv = None
                if sv:
                    _emb_cache[s["name"]] = (h, sv)
        sem = _cos(qv, sv) if (qv and sv) else 0.0
        lex = min(0.35, overlap * 0.10)          # bonus lexical plafonné
        # Déclencheurs explicites : si une expression 'trigger' est présente telle quelle → bonus fort
        if sem:
            score = sem + lex + trig
        else:
            # v2.123 — repli si l'embedding est indisponible (Ollama hors-ligne, modèle
            # d'embedding non installé, timeout...) : l'ancien calcul imposait un mur dur
            # (overlap>=2 OU trigger EXACT, sinon plafonné à `lex` seul = 0.30 max — toujours
            # sous le seuil) qui désactivait SILENCIEUSEMENT tout matching pour une requête
            # n'ayant qu'UN mot-clé fort en commun (ex: "imprimante" seul, très spécifique
            # puisque _keywords filtre déjà les mots courts/vides). Un recouvrement lexical
            # même partiel doit compter, en dégradé mais jamais nul.
            base = 0.40 if overlap >= 2 else (0.22 if overlap == 1 else 0.0)
            score = base + lex + trig
        if score > best_score:
            # L'ancien 1er devient le dauphin (seulement s'il ne s'agit pas de la 1ère
            # itération où best est encore None).
            if best is not None:
                runner_up, runner_up_score = best, best_score
            best, best_score = s, score
        elif score > runner_up_score:
            runner_up, runner_up_score = s, score
    accepted = best if (best is not None and best_score >= threshold) else None
    # v2.125 — anti-bruit : trouvé en conditions réelles grâce au journal du dauphin
    # (v2.124) juste construit — deux questions anodines ("combien font 47*53", "quelle
    # est la capitale de la France") déclenchaient des compétences totalement hors sujet
    # (dépannage imprimante, pas-internet) à des scores 0.6-0.7 à peine au-dessus du seuil,
    # quasi à égalité avec le dauphin (écart de 0.004 à 0.013 seulement) — signe de bruit de
    # mesure, pas d'une vraie correspondance. Les VRAIS matches observés en réel se situent
    # tous >0.95 avec un écart net sur le dauphin. Seuil relevé (0.60→0.72) + exige un écart
    # minimum avec le 2ᵉ candidat, sinon on préfère ne PAS matcher plutôt que d'injecter une
    # méthode hors-sujet dans le prompt (qui peut faire dériver le modèle sur une question
    # simple — probable contributeur au ressenti "Marvin tourne en rond sans rien faire").
    # 0.05 choisi pour rejeter les 2 cas de bruit observés (écarts 0.004 et 0.013) tout en
    # laissant passer une vraie ambiguïté entre 2 compétences voisines mais légitimes
    # (ex. "veille-recherche-informatique" vs "veille-vulnerabilites-logiciels", écart 0.073
    # observé en réel — score du gagnant déjà élevé à 0.989, pas du bruit).
    MIN_GAP = 0.05
    if accepted is not None and runner_up is not None and (best_score - runner_up_score) < MIN_GAP:
        accepted = None
    _log_match_attempt(query, accepted, best, best_score, runner_up, runner_up_score)
    return accepted


# v2.124 — journal des tentatives de matching (gagnant + dauphin + scores), pour avoir de
# VRAIES données avant de décider si un retrieval multi-compétences (façon Voyager, qui
# récupère le top-5 plutôt qu'un seul gagnant) apporterait quelque chose ici. Fichier
# append-only borné (garde les 500 dernières entrées) — coût quasi nul, aucune action
# automatique déclenchée par ce journal, purement diagnostique pour l'instant.
_MATCH_LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "skills_match_log.jsonl")
_MATCH_LOG_STORE = None
_MATCH_LOG_STORE_PATH = None
_MATCH_LOG_INIT_LOCK = threading.RLock()


def _match_log_store() -> StructuredJsonlStore:
    global _MATCH_LOG_STORE, _MATCH_LOG_STORE_PATH
    resolved = os.path.abspath(_MATCH_LOG_FILE)
    if _MATCH_LOG_STORE is None or _MATCH_LOG_STORE_PATH != resolved:
        with _MATCH_LOG_INIT_LOCK:
            if _MATCH_LOG_STORE is None or _MATCH_LOG_STORE_PATH != resolved:
                _migrate_match_log(resolved)
                _MATCH_LOG_STORE = StructuredJsonlStore.from_environment(
                    resolved,
                    component="skills.matcher",
                    prefix="SKILL_MATCH_LOG",
                    default_retention_days=30,
                )
                _MATCH_LOG_STORE_PATH = resolved
    return _MATCH_LOG_STORE


def _migrate_match_log(path: str) -> None:
    """Expurge en place les requêtes historiques sans conserver de copie sensible."""
    target = os.path.abspath(path)
    if not os.path.isfile(target):
        return
    try:
        rows = []
        changed = False
        with open(target, encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if not isinstance(row, dict):
                    continue
                if isinstance(row.get("query"), str):
                    row["query"] = sanitize({"query": row["query"]})["query"]
                    changed = True
                rows.append(row)
        if not changed:
            return
        temporary = target + ".tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows[-500:]:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(temporary, target)
    except Exception:
        try:
            if os.path.exists(target + ".tmp"):
                os.remove(target + ".tmp")
        except OSError:
            pass


def _log_match_attempt(query: str, accepted, best, best_score: float, runner_up, runner_up_score: float):
    try:
        compatibility = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "query": (query or "")[:160],
            "winner": accepted["name"] if accepted else None,
            "winner_score": round(best_score, 3) if best else 0.0,
            "runner_up": runner_up["name"] if runner_up else None,
            "runner_up_score": round(runner_up_score, 3) if runner_up else 0.0,
            "gap": round(best_score - runner_up_score, 3) if (best and runner_up) else None,
        }
        _match_log_store().write(
            "skill.match",
            severity="INFO",
            outcome="matched" if accepted else "not_matched",
            compatibility=compatibility,
        )
    except Exception:
        pass  # best-effort, ne doit jamais casser le matching lui-même


def get_match_log(limit: int = 50) -> list:
    """Lit le journal de matching (le plus récent en premier) — diagnostic pour ajuster le
    seuil/la formule, ou juger si un retrieval multi-compétences serait utile (cas où
    winner_score et runner_up_score sont proches = ambiguïté réelle entre 2 compétences)."""
    try:
        bounded_limit = min(max(int(limit), 0), 500)
        return _match_log_store().recent(limit=bounded_limit) if bounded_limit else []
    except Exception:
        return []


def seed_examples():
    """Crée quelques skills d'exemple si le dossier est vide (montre le format)."""
    if list_skills():
        return
    save_skill(
        "depannage-imprimante",
        "Diagnostiquer et réparer une imprimante (réseau ou USB) qui n'imprime pas ou ne répond plus",
        "Méthode de dépannage (suis les étapes, utilise les outils, explique chaque résultat) :\n"
        "1. Demande/identifie l'imprimante concernée et son IP si réseau.\n"
        "2. Connectivité : `net_ping` vers l'IP de l'imprimante.\n"
        "3. Spouleur Windows : `pc_run_command` → `Get-Service Spooler` ; si arrêté, propose de le redémarrer.\n"
        "4. File d'attente bloquée : propose de purger les travaux en attente.\n"
        "5. Pilote : vérifie via `win_system_report` / suggère réinstallation si besoin.\n"
        "6. Conclus par un diagnostic clair + action recommandée.",
        tools=["net_ping", "pc_run_command", "win_system_report", "system_search"],
    )
    save_skill(
        "compte-rendu-reunion",
        "Transformer des notes de réunion en compte-rendu professionnel structuré",
        "Quand l'utilisateur fournit des notes de réunion :\n"
        "1. Structure : Participants · Ordre du jour · Décisions · Actions (avec responsable + échéance) · Points en suspens.\n"
        "2. Reformule en français clair et professionnel, sans inventer.\n"
        "3. Propose de générer un document Word via `document_generate` (modèle compte_rendu) et de créer les "
        "tâches d'action via `task_create` (avec échéances).",
        tools=["document_generate", "task_create", "event_create"],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  📖 Learning Log — journal persistant, introspectable, revu automatiquement
#  (y compris LA NUIT, plus agressivement) — apprentissage global au-delà d'une
#  seule compétence : créations, upgrades, consolidations, oublis, avec diffs.
# ══════════════════════════════════════════════════════════════════════════════

_LEARNING_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "skills_learning_log.json")


def log_learning_event(event_type: str, skill_name: str, reason: str = "",
                        before: str = None, after: str = None, metadata: dict = None):
    """Journalise un événement d'apprentissage (création/upgrade/consolidation/oubli)
    avec diff avant/après si dispo. Persistant → Marvin peut relire sa propre histoire
    (introspection) et la consolidation nocturne s'appuie dessus."""
    import difflib
    event = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": event_type,
        "skill": skill_name,
        "reason": (reason or "")[:300],
        "metadata": metadata or {},
    }
    if before and after and before.strip() != after.strip():
        diff = "\n".join(difflib.unified_diff(
            before.splitlines(), after.splitlines(), fromfile="avant", tofile="après", lineterm=""))
        event["diff"] = diff[:8000]
    try:
        os.makedirs(os.path.dirname(_LEARNING_LOG_PATH), exist_ok=True)
        logs = []
        if os.path.exists(_LEARNING_LOG_PATH):
            with open(_LEARNING_LOG_PATH, encoding="utf-8") as f:
                logs = json.load(f)
        logs.append(event)
        logs = logs[-200:]   # garde les 200 derniers événements
        with open(_LEARNING_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_learning_log(limit: int = 50, skill_name: str = None) -> list:
    """Récupère le journal (pour l'UI et pour l'introspection LLM)."""
    try:
        if not os.path.exists(_LEARNING_LOG_PATH):
            return []
        with open(_LEARNING_LOG_PATH, encoding="utf-8") as f:
            logs = json.load(f)
        if skill_name:
            logs = [e for e in logs if e.get("skill") == skill_name]
        return logs[-limit:][::-1]   # le plus récent d'abord
    except Exception:
        return []


def get_learning_log_for_llm(skill_name: str = None, limit: int = 10) -> str:
    """Résumé du journal pour un appel-outil : permet à Marvin d'interroger sa propre
    évolution (« qu'as-tu appris récemment ? », « pourquoi as-tu changé telle compétence ? »)."""
    logs = get_learning_log(limit, skill_name)
    if not logs:
        return "Aucun historique d'apprentissage pour le moment."
    lines = []
    for e in logs[:limit]:
        s = f"[{e['ts']}] {e['type']} → {e['skill']}\n  Raison : {e['reason']}"
        if e.get("diff"):
            s += f"\n  Évolution :\n{e['diff'][:450]}"
        lines.append(s)
    return "=== Historique d'apprentissage de Marvin ===\n" + "\n\n".join(lines)


async def find_overlapping_skills(threshold: float = 0.85) -> list[dict]:
    """v2.124 — Scan de similarité CROISÉE entre TOUTES les compétences activées (pas
    seulement au sein d'une même compétence comme `review_and_consolidate_learnings`) :
    repère les paires dont la description se ressemble trop, signe possible de
    chevauchement/confusion pour le matcher — pattern « curation à l'échelle de la
    bibliothèque » (SkillOS/SkillBrew, littérature 2026 sur les agents à compétences).
    Ne modifie rien tout seul : renvoie juste la liste pour revue humaine."""
    import vector_store as vs
    sk = [s for s in list_skills() if s.get("enabled")]
    embeds: dict[str, list] = {}
    for s in sk:
        text = s["description"] or s["name"]
        h = hashlib.md5(text.encode("utf-8")).hexdigest()
        cached = _emb_cache.get(s["name"])
        if cached and cached[0] == h:
            embeds[s["name"]] = cached[1]
            continue
        try:
            v = await vs.embed(text)
        except Exception:
            v = None
        if v:
            _emb_cache[s["name"]] = (h, v)
            embeds[s["name"]] = v
    names = list(embeds.keys())
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            sim = _cos(embeds[names[i]], embeds[names[j]])
            if sim >= threshold:
                pairs.append({"a": names[i], "b": names[j], "similarity": round(sim, 3)})
    pairs.sort(key=lambda p: -p["similarity"])
    return pairs


# v2.517 — Garde-fous de la consolidation automatique.
# Délai minimal entre deux consolidations réussies, toutes compétences confondues.
CONSOLIDATION_COOLDOWN_SECONDS = 6 * 3600
# Sujets que la consolidation ne doit jamais transformer en compétence : ce sont des
# comportements du code (worker de consolidation, journal d'apprentissage). Les laisser
# passer crée une boucle auto-référentielle, constatée en conditions réelles.
_META_SKILL_PATTERNS = (
    "consolidat", "deduplication", "dedup", "dedoublonnage", "learning log",
    "learning-log", "learning_log", "journal d'apprentissage", "journal apprentissage",
    "revue automatique", "revue auto", "reconsolidation", "boucle de revue",
)


def _normalize_for_compare(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _is_meta_skill(name: str, description: str) -> bool:
    """Vrai si la compétence proposée parle de la gestion des compétences elle-même."""
    blob = _normalize_for_compare(f"{name} {description}")
    return any(_normalize_for_compare(p) in blob for p in _META_SKILL_PATTERNS)


def _duplicates_existing_skill(name: str, description: str, existing: list) -> bool:
    """Recoupement lexical déterministe avec une compétence déjà présente.

    Volontairement sans embedding : ce contrôle tourne dans un worker de fond et doit
    rester rapide, hors ligne et reproductible. `find_overlapping_skills` reste
    disponible pour l'analyse sémantique à la demande.
    """
    candidate_name = _normalize_for_compare(name)
    candidate_words = set(_normalize_for_compare(description).split())
    for skill in existing or []:
        if _normalize_for_compare(skill.get("name")) == candidate_name:
            return True
        other = set(_normalize_for_compare(skill.get("description")).split())
        if not candidate_words or not other:
            continue
        overlap = len(candidate_words & other) / len(candidate_words | other)
        if overlap >= 0.6:
            return True
    return False


def _consolidation_on_cooldown(skill_name: str = None) -> bool:
    """Vrai si une consolidation a déjà eu lieu dans la fenêtre de cooldown."""
    try:
        for event in get_learning_log(200):
            if event.get("type") != "consolidate":
                continue
            stamp = time.mktime(time.strptime(event["ts"], "%Y-%m-%d %H:%M:%S"))
            return (time.time() - stamp) < CONSOLIDATION_COOLDOWN_SECONDS
    except Exception:
        return False
    return False


async def review_and_consolidate_learnings(generate_fn, skill_name: str = None,
                                           tool_names: list = None):
    """Le LLM relit son propre Learning Log récent et peut proposer UNE consolidation
    (fusion de compétences proches, sous-compétence dédiée) si un vrai pattern se dégage.
    `generate_fn` : async (str)->str. Conservateur : ne fait rien si le log est trop court
    ou si le LLM ne propose rien de solide.

    v2.517 — trois garde-fous ajoutés après constat en conditions réelles. Cette passe
    écrivait dans le Learning Log qu'elle relit ensuite : sans cooldown ni contrôle
    d'existence, elle a produit 17 compétences quasi identiques en 38 h, toutes sur le
    thème « empêcher les consolidations répétées ». Les outils n'étaient pas validés ici
    alors qu'ils le sont déjà dans les deux autres chemins de création (voir plus haut) :
    18,3 % des références d'outils de la bibliothèque pointaient dans le vide.
    """
    log = get_learning_log(30, skill_name)
    if len(log) < 3:
        return None
    if _consolidation_on_cooldown(skill_name):
        return None
    existing = list_skills()
    existing_lines = "\n".join(
        f"- {s['name']} : {s.get('description', '')}" for s in existing
    )
    tools_hint = ", ".join((tool_names or [])[:120])
    prompt = (
        "Tu es Marvin, en revue de ton propre apprentissage. Voici ton Learning Log récent "
        "(créations/améliorations de compétences, avec diffs et raisons). RÉDIGE EN FRANÇAIS.\n"
        "Cherche UN SEUL pattern clair et utile (ex : deux compétences qui se recoupent et "
        "gagneraient à fusionner, ou une méthode qui revient et mérite une compétence dédiée).\n"
        "⛔ NE PROPOSE RIEN si le pattern porte sur la consolidation, la déduplication, la "
        "revue du Learning Log ou la gestion des compétences elles-mêmes : ces sujets sont "
        "gérés par le code, pas par une compétence. Réponds alors: null\n"
        "⛔ NE PROPOSE RIEN qui recoupe une compétence déjà listée ci-dessous. Réponds: null\n"
        "Si rien de solide ne se dégage, réponds exactement: null\n\n"
        f"### Compétences DÉJÀ existantes (NE PAS les redoubler)\n{existing_lines or '(aucune)'}\n\n"
        + (f"### Outils réellement disponibles (n'en invente AUCUN autre)\n{tools_hint}\n\n"
           if tools_hint else "")
        + f"Journal :\n{str(log)[:4000]}\n\n"
        "Si tu proposes une consolidation, réponds UNIQUEMENT en JSON, sans texte autour :\n"
        '{"name": "nom-court-kebab", "description": "quand l\'utiliser (1 phrase)", '
        '"triggers": ["3 à 6 déclencheurs"], "tools": ["nom exact d\'un outil ci-dessus"], '
        '"body": "## Objectif\\n...\\n## Étapes\\n1. ...\\n## Vérification\\n..."}'
    )
    try:
        raw = await generate_fn(prompt)
    except Exception:
        return None
    if not raw or raw.strip().lower().startswith("null"):
        return None
    data = parse_skill_json(raw)
    if not data.get("name") or not (data.get("body") or "").strip():
        return None
    if _is_meta_skill(data["name"], data.get("description", "")):
        log_learning_event("consolidate_refused", data["name"],
                           "Sujet méta (consolidation/journal) : géré par le code.")
        return None
    if _duplicates_existing_skill(data["name"], data.get("description", ""), existing):
        log_learning_event("consolidate_refused", data["name"],
                           "Recoupe une compétence existante.")
        return None
    # Même filtre que les deux autres chemins de création : un outil inventé est retiré.
    valid = set(tool_names or [])
    kept_tools = [t for t in (data.get("tools") or []) if (not valid or t in valid)][:8]
    save_skill(data["name"], data.get("description", "Consolidation automatique"), data.get("body"),
               kept_tools, True, triggers=[str(t)[:40] for t in (data.get("triggers") or [])][:8])
    log_learning_event("consolidate", data["name"], "Revue automatique du Learning Log")
    return {"consolidated": data["name"]}


def consolidate_obsolete_skills() -> list:
    """« Oublie » (archive + désactive) les compétences ANCIENNES et PEU UTILISÉES :
    > 30 jours sans usage ET moins de 3 usages au total. Conservateur (archive, ne
    supprime jamais) — une compétence jamais déclenchée n'est pas forcément mauvaise,
    seulement inutile pour l'instant ; `rollback_skill` permet de la ranimer."""
    stats = _load_stats()
    now = time.time()
    forgotten = []
    for s in list_skills():
        if not s.get("enabled", True):
            continue
        st = stats.get(s["name"]) or {}
        last = st.get("last_used", "")
        uses = st.get("uses", 0)
        if uses >= 3:
            continue
        try:
            from datetime import datetime
            if last:
                age_days = (now - datetime.strptime(last, "%Y-%m-%d %H:%M:%S").timestamp()) / 86400
            else:
                # v2.123 — une compétence JAMAIS déclenchée n'a pas de last_used : l'ancien
                # code l'ignorait purement et simplement (`if not last: continue`), donc
                # aucune des compétences jamais utilisées n'était jamais révisée/archivée,
                # quel que soit son âge (bug réel : 16/26 compétences dans ce cas, audit
                # réel des stats). Utilise la date de dernière modification du fichier
                # comme référence d'âge à défaut d'un usage — un signal moins précis mais
                # bien meilleur qu'une exemption permanente.
                age_days = (now - os.path.getmtime(os.path.join(_dir(), s["file"]))) / 86400
        except Exception:
            continue
        if age_days > 30:
            save_skill(s["name"], s.get("description", ""), s.get("body", ""), s.get("tools") or [],
                       False, triggers=s.get("triggers"), related=s.get("related"))
            log_learning_event("forget", s["name"],
                                f"Inactive depuis {int(age_days)} j, seulement {uses} usage(s) — désactivée (archivée, pas supprimée)")
            forgotten.append(s["name"])
    return forgotten
