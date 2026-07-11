"""
Marvin Backend — FastAPI application principale.
Lance avec : uvicorn main:app --host 0.0.0.0 --port 8005
(ne pas utiliser --reload : coupe les streams SSE lors des changements de fichiers)
"""
import json
import base64
import re as _re
import asyncio as _asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Body, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, Response
from pydantic import BaseModel, Field
from typing import Any

import database as db
import tools as tool_module
from agent import run_agent, _refresh_model_cache
from config import (
    FRONTEND_URL, BACKEND_PORT, DANGEROUS_TOOLS,
    PERMISSION_SECURE, PERMISSION_STANDARD, PERMISSION_EXPERT, DEFAULT_PERMISSION_LEVEL,
    SECURE_BLOCKED_TOOLS, BACKEND_DIR,
)

# URI de callback OAuth — utilise BACKEND_PORT pour être cohérent avec le serveur réel
_GOOGLE_CALLBACK  = f"http://localhost:{BACKEND_PORT}/api/oauth/google/callback"
_MS_CALLBACK      = f"http://localhost:{BACKEND_PORT}/api/oauth/microsoft/callback"

# Scopes Google complets (Drive + Gmail + Calendar)
_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]

# ══════════════════════════════════════════════════════════════════════════════
# Moteur CRON — exécution planifiée des outils
# ══════════════════════════════════════════════════════════════════════════════

def _parse_schedule_seconds(schedule: str) -> int:
    """
    Convertit une expression de planning en nombre de secondes entre deux exécutions.
    Supporte :
      - "every N seconds/minutes/hours/days"
      - "every minute / every hour / every day"
      - "*/N * * * *"  (cron simplifié — minutes seulement)
      - "daily at HH:MM"
    Retourne 60 par défaut si format inconnu.
    """
    s = schedule.lower().strip()

    # every N unit
    m = _re.match(r'every\s+(\d+)\s+(second|minute|hour|day)s?', s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return n * {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[unit]

    # every minute / every hour / every day
    if s in ("every minute", "chaque minute"):  return 60
    if s in ("every hour", "chaque heure"):     return 3600
    if s in ("every day", "chaque jour"):       return 86400

    # */N * * * *  (N en minutes)
    m = _re.match(r'\*/(\d+)\s+\*', s)
    if m:
        return int(m.group(1)) * 60

    # daily at HH:MM → secondes jusqu'à la prochaine occurrence
    m = _re.match(r'daily at (\d{1,2}):(\d{2})', s)
    if m:
        return 86400  # relance toutes les 24h ; next_run est calculé séparément

    return 60  # défaut : chaque minute


# Convention cron : dimanche=0, lundi=1, … samedi=6
_DOW = {"sunday": 0, "dimanche": 0, "monday": 1, "lundi": 1, "tuesday": 2, "mardi": 2,
        "wednesday": 3, "mercredi": 3, "thursday": 4, "jeudi": 4, "friday": 5, "vendredi": 5,
        "saturday": 6, "samedi": 6}


def _to_cron(s: str):
    """Traduit une expression en clair en cron 5 champs si possible (sinon None).
    Gère : 'daily at HH:MM', 'weekdays/weekends at HH:MM', 'every <jour> at HH:MM',
    'weekly on <jour> at HH:MM', 'monthly on day D at HH:MM', et le cron brut."""
    s = s.lower().strip()
    # Déjà un cron 5 champs ?
    if _re.fullmatch(r'[\d*/,\-]+(\s+[\d*/,\-]+){4}', s):
        return s
    def hm(t):
        return int(t[1]), int(t[0]) if False else (int(t[0]), int(t[1]))
    m = _re.search(r'(?:at|à)\s+(\d{1,2})[:h](\d{2})', s)
    H, M = (int(m.group(1)), int(m.group(2))) if m else (9, 0)
    if "weekday" in s or "semaine" in s or "ouvré" in s:
        return f"{M} {H} * * 1-5"
    if "weekend" in s or "week-end" in s:
        return f"{M} {H} * * 0,6"
    mm = _re.search(r'monthly.*day\s+(\d{1,2})|mensuel.*(\d{1,2})', s)
    if mm:
        d = mm.group(1) or mm.group(2)
        return f"{M} {H} {d} * *"
    for name, dow in _DOW.items():
        if name in s:
            return f"{M} {H} * * {dow}"
    if ("daily" in s or "chaque jour" in s or "tous les jours" in s) and m:
        return f"{M} {H} * * *"
    if m and ("every day" in s or "daily" in s or not any(k in s for k in ("every", "chaque"))):
        return f"{M} {H} * * *"
    return None


def _next_run_dt(schedule: str) -> str:
    """Prochaine exécution en HEURE LOCALE. Supporte cron, jours nommés, intervalles."""
    now = datetime.now()
    cron = _to_cron(schedule)
    if cron:
        try:
            from croniter import croniter
            return croniter(cron, now).get_next(datetime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    secs = _parse_schedule_seconds(schedule)
    return (now + timedelta(seconds=secs)).strftime("%Y-%m-%d %H:%M:%S")


async def _drain_run_agent(message: str, conv_id: str):
    """Consomme un tour `run_agent` complet (les messages/outils sont déjà sauvegardés par
    run_agent lui-même, rien à faire du flux SSE ici) — factorisé pour pouvoir le borner
    avec asyncio.wait_for depuis _long_task_resume_tick."""
    async for _ in run_agent([{"role": "user", "content": message}], conv_id, None):
        pass


async def _long_task_resume_tick(job: dict, now_str: str):
    """v2.145 — reprise d'une tâche longue (`long_task_start`) : contrairement aux jobs cron
    normaux (1 outil, args fixes), celui-ci relance un VRAI tour d'agent complet (`run_agent`,
    outils inclus) sur la conversation d'origine — pas juste un appel d'outil isolé. S'arrête
    tout seul (désactive le job) une fois toutes les étapes de la checklist marquées 'done'."""
    args = job.get("args") or {}
    conv_id = args.get("conversation_id")
    slug = args.get("slug")
    goal = args.get("goal", "")
    if not conv_id or not slug:
        db.update_cron_job(job["id"], {"enabled": False, "last_run": now_str,
                                        "last_result": json.dumps({"error": "job long_task mal formé"})[:500]})
        return

    tag = f"longtask:{slug}"
    pending = [t for t in db.list_tasks(limit=200)
               if t.get("status") != "done" and tag in (t.get("tags") or [])]
    if not pending:
        db.update_cron_job(job["id"], {
            "enabled": False, "last_run": now_str,
            "last_result": json.dumps({"message": f"Tâche longue « {goal[:80]} » terminée."})[:500],
        })
        try:
            notifier = tool_module.TOOLS_REGISTRY.get("pc_notify")
            if notifier:
                await notifier({"title": "Marvin — Tâche longue terminée",
                                 "message": goal[:200] or "Toutes les étapes sont faites."})
        except Exception:
            pass
        return

    # v2.145 — 2 bugs trouvés en testant en réel :
    #   1. Nommer littéralement "long_task_status"/"task_update" dans le nudge déclenchait
    #      la règle d'or #6 (outil explicite cité = SEUL outil autorisé ce tour), bloquant
    #      l'accès aux VRAIS outils nécessaires pour avancer (file_large_finder, etc.) —
    #      corrigé en décrivant l'étape en PROSE, sans jamais nommer un outil précis.
    #   2. Le modèle n'avait aucun moyen fiable de connaître l'ID exact de la tâche à
    #      marquer terminée (inventait le tag ou un numéro de position) — corrigé en
    #      donnant l'ID exact de la PROCHAINE étape directement dans le nudge.
    next_step = pending[0]
    nudge = (
        f"[Reprise automatique de tâche longue « {goal} »] Étape à traiter maintenant : "
        f"« {next_step['title']} » (identifiant de tâche : {next_step['id']}). Avance "
        "dessus avec les outils appropriés à cette étape précise — reste sur une action "
        "CIBLÉE et RAPIDE, évite un scan récursif ou une opération lourde qui prendrait "
        "plusieurs minutes — puis mets à jour le statut de cette tâche à 'done' une fois "
        f"terminée. Il reste {len(pending)} étape(s) au total sur cette tâche longue."
    )
    # v2.145 — 3e bug trouvé en testant en réel : une reprise SANS limite de temps peut
    # enchaîner suffisamment d'appels d'outils/cloud pour prendre plusieurs MINUTES (même
    # symptôme déjà documenté en v2.136 — un tour d'agent normal peut être lent), ce qui
    # retarde TOUS les autres jobs cron suivants (le worker traite les jobs séquentiellement)
    # et peut bloquer la réactivité perçue du backend le temps que ça tourne. Borné à 3 min
    # (buffer confortable avant le prochain cycle à 5 min) — la progression déjà faite dans
    # ce délai reste sauvegardée (run_agent écrit chaque message au fil de l'eau), seule la
    # suite est coupée et reprise au cycle suivant.
    try:
        await _asyncio.wait_for(_drain_run_agent(nudge, conv_id), timeout=180)
        result = {"message": "Reprise exécutée."}
    except _asyncio.TimeoutError:
        result = {"message": "Reprise interrompue après 3 min (progression déjà faite conservée) — continuera au prochain cycle."}
    except Exception as e:
        result = {"error": str(e)[:200]}

    db.update_cron_job(job["id"], {
        "last_run": now_str,
        "next_run": _next_run_dt(job["schedule"]),
        "last_result": json.dumps(result)[:500],
        "run_count": True,
    })


async def _cron_worker():
    """Tâche de fond : vérifie et exécute les jobs cron toutes les 30 secondes."""
    while True:
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")   # heure LOCALE
            jobs = db.list_cron_jobs(enabled_only=True)
            for job in jobs:
                next_run = job.get("next_run")
                if not next_run or next_run <= now_str:
                    # v2.145 — les jobs de reprise de tâche longue relancent un tour d'agent
                    # complet, pas un simple appel d'outil (cf. _long_task_resume_tick).
                    if job["tool_name"] == "_long_task_resume":
                        await _long_task_resume_tick(job, now_str)
                        continue
                    # Exécuter l'outil
                    executor = tool_module.TOOLS_REGISTRY.get(job["tool_name"])
                    result = {"error": f"Outil '{job['tool_name']}' introuvable"}
                    duration_ms = 0
                    if executor:
                        import time as _t
                        t0 = _t.monotonic()
                        try:
                            args = dict(job.get("args") or {})
                            result = await executor(args)
                        except Exception as e:
                            result = {"error": str(e)}
                        duration_ms = int((_t.monotonic() - t0) * 1000)
                        try:
                            db.log_execution(job["tool_name"], job.get("args", {}), result, duration_ms)
                        except Exception:
                            pass

                    # Mettre à jour le job
                    db.update_cron_job(job["id"], {
                        "last_run": now_str,
                        "next_run": _next_run_dt(job["schedule"]),
                        "last_result": json.dumps(result)[:500],
                        "run_count": True,  # incrémente run_count
                    })
        except Exception as e:
            print(f"[CRON] Erreur worker: {e}")

        await _asyncio.sleep(30)


# ── App ───────────────────────────────────────────────────────────────────────
from contextlib import asynccontextmanager

async def _prewarm_default_model():
    """
    Pre-load the default models (agent + chat) into Ollama's RAM at startup.
    Eliminates the 10-30s cold-load delay on user's first message.
    Runs in background — doesn't block startup.
    """
    import httpx as _httpx
    from config import OLLAMA_URL, MODEL_PROFILES
    # Pre-warm agent first (most used), then chat (for short messages)
    models_to_warm = [
        MODEL_PROFILES.get("agent", {}).get("model", "qwen2.5:7b"),
        MODEL_PROFILES.get("chat", {}).get("model", "qwen2.5:3b"),
    ]
    seen = set()
    async with _httpx.AsyncClient(timeout=120.0) as client:
        for model in models_to_warm:
            if model in seen:
                continue
            seen.add(model)
            try:
                await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "."}],
                        "stream": False,
                        "keep_alive": "30m",   # 30 min keepalive — survives most idle periods
                        "options": {"num_predict": 1},
                    },
                )
                print(f"[Marvin] ✅ Modèle '{model}' pré-chargé en mémoire")
            except Exception as e:
                print(f"[Marvin] ⚠️ Pré-chargement '{model}' échoué : {e}")


async def _email_watch_worker():
    """Boucle de fond : surveille périodiquement les mails importants et notifie (si activé)."""
    await _asyncio.sleep(30)  # laisser le démarrage se terminer
    while True:
        interval = 5
        try:
            cfg = db.get_setting("email_watch")
            if isinstance(cfg, str):
                import json as _json
                try: cfg = _json.loads(cfg)
                except Exception: cfg = {}
            cfg = cfg if isinstance(cfg, dict) else {}
            interval = max(2, int(cfg.get("interval_min", 5)))
            if cfg.get("enabled"):
                # 1) classer automatiquement selon les règles, 2) notifier les importants restants
                try:
                    await tool_module.TOOLS_REGISTRY["email_apply_rules"]({})
                except Exception:
                    pass
                await tool_module.TOOLS_REGISTRY["email_watch_check"]({})
        except Exception:
            pass
        await _asyncio.sleep(interval * 60)


async def _event_reminder_worker():
    """Boucle de fond : notifie les rappels d'agenda à l'heure dite (toast Windows)."""
    await _asyncio.sleep(20)
    from datetime import datetime as _dt
    while True:
        try:
            now = _dt.now().strftime("%Y-%m-%d %H:%M")
            for ev in db.events_needing_reminder(now):
                try:
                    when = (ev.get("start_at") or "")[11:16] or "aujourd'hui"
                    loc = f" ({ev['location']})" if ev.get("location") else ""
                    await tool_module.TOOLS_REGISTRY["pc_notify"]({
                        "title": f"📅 Rappel : {ev.get('title', 'Rendez-vous')}",
                        "message": f"À {when}{loc}",
                    })
                    db.update_event(ev["id"], {"reminded": True})
                except Exception:
                    pass
        except Exception:
            pass
        await _asyncio.sleep(60)


async def _build_tool_index():
    """Indexe les descriptions d'outils pour le routing sémantique (et préchauffe
    le modèle d'embeddings). Une seule fois ; réindexe si le set d'outils change."""
    await _asyncio.sleep(8)
    try:
        import tool_router
        ok = await tool_router.ensure_tool_index(tool_module.TOOLS_SPEC)
        print(f"[Marvin] {'✅ Index sémantique des outils prêt' if ok else '⚠️ Index outils indisponible (embeddings/Qdrant)'}")
    except Exception as e:
        print(f"[Marvin] ⚠️ Index outils échoué : {e}")


def _bg_scale() -> float:
    """Facteur d'intervalle des tâches de fond, piloté par le mode (2.0 = 2× moins souvent)."""
    try:
        return max(0.25, float(db.get_setting("bg_scale") or 1.0))
    except Exception:
        return 1.0


async def _calendar_sync_worker():
    """Resynchronise périodiquement les agendas connectés (abonnements iCal + Google)."""
    await _asyncio.sleep(15)   # première synchro peu après le démarrage
    while True:
        try:
            subs = db.get_setting("calendar_subscriptions")
            sa = tool_module._google_calendar_ready()
            if subs or sa:   # tourne s'il y a un abonnement iCal OU un Google connecté
                await tool_module.TOOLS_REGISTRY["calendar_sync"]({})
        except Exception:
            pass
        await _asyncio.sleep(int(30 * 60 * _bg_scale()))   # ~30 min × facteur du mode


# ── Marvin proactif : briefing matinal automatique ──────────────────────────────
def _get_proactive_cfg() -> dict:
    cfg = db.get_setting("proactive_config")
    if isinstance(cfg, str):
        import json as _json
        try: cfg = _json.loads(cfg)
        except Exception: cfg = {}
    return cfg if isinstance(cfg, dict) else {}


async def _tts_bytes(text: str, voice: str = "henri") -> bytes:
    """Synthèse vocale → MP3 (edge-tts), pour la lecture côté backend."""
    import edge_tts, re as _re
    vid = DEFAULT_TTS_VOICES.get(voice, {}).get("id", "fr-FR-HenriNeural")
    t = _re.sub(r"[*#`_>]+", "", text or "").strip()
    if not t:
        return b""
    comm = edge_tts.Communicate(t[:1500], vid)
    chunks = []
    async for c in comm.stream():
        if c["type"] == "audio":
            chunks.append(c["data"])
    return b"".join(chunks)


def _play_mp3_bytes_sync(mp3: bytes):
    """Joue un MP3 sur les haut-parleurs du PC (ffmpeg→wav→winsound), sans dépendance externe."""
    import tempfile, os as _os, subprocess
    try:
        import winsound, imageio_ffmpeg
    except Exception:
        return
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    mp3p = tempfile.mktemp(suffix=".mp3"); wavp = tempfile.mktemp(suffix=".wav")
    try:
        with open(mp3p, "wb") as f:
            f.write(mp3)
        subprocess.run([ffmpeg, "-y", "-i", mp3p, "-ar", "22050", "-ac", "1", wavp],
                       capture_output=True, creationflags=0x08000000)  # CREATE_NO_WINDOW
        if _os.path.exists(wavp):
            winsound.PlaySound(wavp, winsound.SND_FILENAME)  # synchrone (on est dans un thread)
    except Exception:
        pass
    finally:
        for p in (mp3p, wavp):
            try: _os.unlink(p)
            except Exception: pass


async def _speak_backend(text: str, voice: str = "henri"):
    try:
        mp3 = await _tts_bytes(text, voice)
        if mp3:
            await _asyncio.get_running_loop().run_in_executor(None, _play_mp3_bytes_sync, mp3)
    except Exception:
        pass


async def run_morning_briefing(mb: dict) -> dict:
    """Génère le briefing, envoie une notification concise, et le lit à voix haute si demandé."""
    res = await tool_module.TOOLS_REGISTRY["daily_briefing"]({})
    if not res.get("success"):
        return {"error": res.get("error", "briefing indisponible")}
    ev = res.get("events_today") or []
    parts = [f"{len(ev)} rendez-vous" if ev else "aucun rendez-vous"]
    if res.get("tasks_urgent"): parts.append(f"{res['tasks_urgent']} tâche(s) urgente(s)")
    elif res.get("tasks_pending"): parts.append(f"{res['tasks_pending']} tâche(s)")
    if res.get("unread"): parts.append(f"{res['unread']} mail(s) non lus")
    summary = "Aujourd'hui : " + ", ".join(parts) + "."
    try:
        await tool_module.TOOLS_REGISTRY["pc_notify"]({"title": "🌅 Votre briefing du jour", "message": summary})
    except Exception:
        pass
    try:
        await tool_module._telegram_notify("🌅 <b>Briefing du jour</b>\n" + summary)
    except Exception:
        pass
    if mb.get("voice"):
        spoken = "Bonjour ! " + (res.get("briefing") or summary)
        await _speak_backend(spoken, mb.get("voice_name", "henri"))
    return {"success": True, "summary": summary}


async def run_evening_recap(er: dict) -> dict:
    """Bilan de fin de journée : tâches en attente, RDV de demain, mails non lus."""
    reg = tool_module.TOOLS_REGISTRY
    res = await reg["daily_briefing"]({})
    try:
        tomo = await reg["event_list"]({"period": "tomorrow"})
        ev_tomo = tomo.get("events") or []
    except Exception:
        ev_tomo = []
    parts = []
    if res.get("tasks_urgent"):
        parts.append(f"{res['tasks_urgent']} tâche(s) urgente(s) en attente")
    elif res.get("tasks_pending"):
        parts.append(f"{res['tasks_pending']} tâche(s) en attente")
    parts.append(f"{len(ev_tomo)} RDV demain" if ev_tomo else "rien de prévu demain")
    if res.get("unread"):
        parts.append(f"{res['unread']} mail(s) non lus")
    summary = "Bilan du soir — " + ", ".join(parts) + "."
    try: await reg["pc_notify"]({"title": "🌙 Bilan du soir", "message": summary})
    except Exception: pass
    try: await tool_module._telegram_notify("🌙 <b>Bilan du soir</b>\n" + summary)
    except Exception: pass
    if er.get("voice"):
        await _speak_backend("Bonsoir ! " + summary, er.get("voice_name", "henri"))
    return {"success": True, "summary": summary}


# Anticipation : alertes proactives (dédupliquées par jour) — signaux LOCAUX, sans coût LLM
_anticip_seen = {"date": None, "ids": set()}

async def run_anticipation(an: dict, *, force: bool = False) -> dict:
    """Repère ce qui va coincer (tâches en retard, RDV imminent) et prévient — une fois par item/jour."""
    from datetime import datetime as _dt
    reg = tool_module.TOOLS_REGISTRY
    now = _dt.now()
    today = now.strftime("%Y-%m-%d")
    if _anticip_seen["date"] != today:
        _anticip_seen["date"] = today
        _anticip_seen["ids"] = set()
    seen = _anticip_seen["ids"]
    alerts = []

    # 1) Tâches en retard (échéance passée, non terminées)
    if an.get("overdue_tasks", True):
        try:
            tl = await reg["task_list"]({})
            for t in (tl.get("tasks") or []):
                due = (t.get("due_date") or "")[:10]
                if due and due < today and (t.get("status") not in ("done", "completed", "cancelled")):
                    key = "ovd_" + str(t.get("id"))
                    if force or key not in seen:
                        seen.add(key)
                        alerts.append({"type": "task_overdue", "key": key,
                                       "text": f"⏰ En retard : « {t.get('title','tâche')} » (échéance {due})"})
        except Exception:
            pass

    # 2) RDV imminent (commence dans <= lead minutes)
    if an.get("upcoming_events", True):
        lead = int(an.get("upcoming_events_min", 30))
        try:
            el = await reg["event_list"]({"period": "today"})
            for e in (el.get("events") or []):
                raw = e.get("start_at") or e.get("start") or ""
                try:
                    from dateutil import parser as _dtp
                    st = _dtp.parse(raw)
                    if st.tzinfo:
                        st = st.replace(tzinfo=None)
                    mins = (st - now).total_seconds() / 60
                except Exception:
                    continue
                if 0 <= mins <= lead:
                    key = "evt_" + str(e.get("id") or raw)
                    if force or key not in seen:
                        seen.add(key)
                        alerts.append({"type": "event_soon", "key": key,
                                       "text": f"📅 Dans {int(mins)} min : {e.get('title') or e.get('summary','RDV')}"})
        except Exception:
            pass

    max_notify = int(an.get("max_notify", 5))
    for a in alerts[:max_notify]:
        try: await reg["pc_notify"]({"title": "🔔 Marvin anticipe", "message": a["text"]})
        except Exception: pass
        try: await tool_module._telegram_notify("🔔 " + a["text"])
        except Exception: pass
    if alerts[:max_notify]:
        try:
            import audit
            audit.log_action("anticipation_notify", {"alertes": len(alerts[:max_notify])},
                             {"message": "; ".join(a["text"] for a in alerts[:max_notify])[:200]}, source="proactif")
        except Exception:
            pass
    return {"success": True, "alerts": alerts, "count": len(alerts)}


_last_briefing_date = {"d": None}
_last_recap_date = {"d": None}

async def _proactive_worker():
    """Briefing matinal, bilan du soir (1×/jour chacun) + anticipation périodique."""
    await _asyncio.sleep(25)
    from datetime import datetime as _dt
    _last_anticip = {"t": 0.0}
    import time as _time
    while True:
        try:
            cfg = _get_proactive_cfg()
            now = _dt.now()
            hm = now.strftime("%H:%M")
            day = now.strftime("%Y-%m-%d")
            quiet = _in_quiet_hours(cfg, hm)  # v2.150 — "heures calmes" : aucune notif proactive
            # Briefing matinal
            mb = cfg.get("morning_briefing", {})
            if mb.get("enabled") and hm == mb.get("time", "08:00") and _last_briefing_date["d"] != day:
                _last_briefing_date["d"] = day
                if not quiet:
                    await run_morning_briefing(mb)
            # Bilan du soir
            er = cfg.get("evening_recap", {})
            if er.get("enabled") and hm == er.get("time", "18:30") and _last_recap_date["d"] != day:
                _last_recap_date["d"] = day
                if not quiet:
                    await run_evening_recap(er)
            # Anticipation (toutes les N minutes)
            an = cfg.get("anticipation", {})
            if an.get("enabled") and not quiet:
                interval = max(5, int(an.get("interval_min", 30))) * 60
                if _time.time() - _last_anticip["t"] >= interval:
                    _last_anticip["t"] = _time.time()
                    await run_anticipation(an)
        except Exception:
            pass
        await _asyncio.sleep(30)


async def _skill_night_learning_worker():
    """📖🌙 Consolidation du Learning Log des compétences — s'exécute en continu, PLUS
    SOUVENT LA NUIT (22h-6h : toutes les 15 min) que le jour (toutes les 25 min). Marvin
    relit son propre historique d'apprentissage par compétence et peut le consolider
    (fusion/sous-compétence dédiée) sans intervention de l'utilisateur, puis archive les
    compétences anciennes et peu utilisées (`consolidate_obsolete_skills`, réversible)."""
    await _asyncio.sleep(45)
    import time as _time
    last_run = 0.0
    while True:
        try:
            now_h = _time.localtime().tm_hour
            interval = 900 if (now_h >= 22 or now_h <= 6) else 1500   # 15 min nuit, 25 min jour
            if _time.time() - last_run >= interval:
                last_run = _time.time()
                import skills

                async def _g(p):
                    # v2.122 — model=None : cloud_routing.resolve_model() décide selon le
                    # réglage Ollama Cloud + la sensibilité du prompt réel, au lieu de
                    # pré-résoudre en local à l'aveugle.
                    return await tool_module._ollama_generate(p, model=None, timeout=180)

                consolidated = 0
                for sk in skills.list_skills():
                    if len(skills.get_learning_log(8, sk["name"])) < 2:
                        continue   # pas assez d'historique réel pour en tirer quelque chose
                    res = await skills.review_and_consolidate_learnings(_g, sk["name"])
                    if res:
                        consolidated += 1
                if consolidated:
                    print(f"[Marvin] 📖 Consolidation nocturne : {consolidated} compétence(s).")
                forgotten = skills.consolidate_obsolete_skills()
                if forgotten:
                    print(f"[Marvin] 🗄️ Compétences archivées (inactives) : {forgotten}")
        except Exception as e:
            print(f"[Marvin] ⚠️ Consolidation nocturne échouée : {e}")
        await _asyncio.sleep(60)


async def _db_backup_worker():
    """💾 Sauvegarde automatique quotidienne de data/secretary.db (v2.111). Une sauvegarde
    immédiate au démarrage garantit qu'une install fraîche ou un redémarrage récent a
    toujours un point de restauration, puis une toutes les 24h. Rotation : 14 dernières
    conservées (backup.py::KEEP_LAST). Best-effort, ne bloque jamais le démarrage."""
    await _asyncio.sleep(20)
    import backup as _backup
    while True:
        try:
            r = _backup.create_backup()
            if r.get("success"):
                print(f"[Marvin] 💾 Sauvegarde DB : {r['path']} ({r['size_kb']} Ko)")
            else:
                print(f"[Marvin] ⚠️ Sauvegarde DB échouée : {r.get('error')}")
        except Exception as e:
            print(f"[Marvin] ⚠️ Sauvegarde DB échouée : {e}")
        await _asyncio.sleep(86400)  # 24h


async def _memory_consolidation_worker():
    """🧠 Consolidation périodique de la mémoire générale (v2.115) — même esprit que le
    Learning Log des compétences, mais déterministe (recouvrement de texte, pas de
    jugement LLM) pour éviter tout risque de fusion erronée. Une fois par jour suffit :
    le volume de nouveaux souvenirs est faible d'une session à l'autre."""
    await _asyncio.sleep(40)
    import memory_consolidation as _memconsol
    while True:
        try:
            r = _memconsol.consolidate_memories()
            if r.get("merged_count"):
                print(f"[Marvin] 🧠 Mémoire consolidée : {r['merged_count']} doublon(s) fusionné(s).")
        except Exception as e:
            print(f"[Marvin] ⚠️ Consolidation mémoire échouée : {e}")
        await _asyncio.sleep(86400)  # 24h


async def _health_trend_worker():
    """📈 Instantané quotidien de santé système (RAM/disque/usure SSD/erreurs récurrentes) —
    v2.138, suite d'une recherche web sur les tendances 2026 du monitoring IT (passage du
    réactif au PRÉDICTIF : détecter une dérive avant qu'elle devienne un problème, pas
    seulement un seuil statique instantané). Un point immédiat au démarrage puis un toutes les
    24h, consommé par l'outil `pc_health_trend`. Best-effort, ne bloque jamais le démarrage."""
    await _asyncio.sleep(60)
    import tools as _tm
    while True:
        try:
            r = await _tm.capture_system_snapshot()
            print(f"[Marvin] 📈 Instantané de santé système enregistré ({r.get('id', '?')[:8]}).")
        except Exception as e:
            print(f"[Marvin] ⚠️ Instantané de santé système échoué : {e}")
        await _asyncio.sleep(86400)  # 24h


@asynccontextmanager
async def lifespan(app_instance):
    """Initialisation au démarrage : cache des modèles + worker cron + surveillance email + pré-chargement."""
    # Auto-configuration : choisit les meilleurs modèles selon le matériel (AVANT le pré-chargement)
    try:
        import auto_config
        ac = await auto_config.apply_auto_config()
        if ac.get("enabled"):
            print(f"[Marvin] 🧩 Auto-config : {ac['hardware']['gpu']} ({ac['hardware']['vram_gb']} Go) → {ac['applied']}")
    except Exception as e:
        print(f"[Marvin] ⚠️ Auto-config échouée : {e}")
    await _refresh_model_cache()
    cron_task = _asyncio.create_task(_cron_worker())
    # Pre-warm the default model in the background (doesn't block startup)
    prewarm_task = _asyncio.create_task(_prewarm_default_model())
    # Pré-charge Whisper (STT) en arrière-plan → 1ère transcription instantanée
    whisper_task = _asyncio.create_task(_prewarm_whisper())
    # Surveillance des mails importants (notifications) — boucle de fond
    watch_task = _asyncio.create_task(_email_watch_worker())
    # Rappels d'agenda (notifications à l'heure dite) — boucle de fond
    reminder_task = _asyncio.create_task(_event_reminder_worker())
    # Synchro des agendas connectés (iCal) — boucle de fond
    calsync_task = _asyncio.create_task(_calendar_sync_worker())
    # Briefing matinal proactif — boucle de fond
    proactive_task = _asyncio.create_task(_proactive_worker())
    # Apprentissage : consolidation du Learning Log des compétences, plus agressive la nuit
    night_learning_task = _asyncio.create_task(_skill_night_learning_worker())
    # Index sémantique des outils (routing intelligent) — tâche unique au démarrage
    toolidx_task = _asyncio.create_task(_build_tool_index())
    # Sauvegarde automatique de data/secretary.db — immédiate puis toutes les 24h
    backup_task = _asyncio.create_task(_db_backup_worker())
    # Consolidation de la mémoire générale (fusion des doublons) — une fois par jour
    memconsol_task = _asyncio.create_task(_memory_consolidation_worker())
    # Instantané quotidien de santé système (RAM/disque/usure/erreurs) — suivi de tendance
    healthtrend_task = _asyncio.create_task(_health_trend_worker())
    # Skills : crée les exemples si le dossier est vide (montre le format)
    try:
        import skills
        skills.seed_examples()
    except Exception:
        pass
    yield
    try:
        import web_browser
        await web_browser.close()
    except Exception:
        pass
    for _t in (cron_task, prewarm_task, whisper_task, watch_task, reminder_task, calsync_task, proactive_task, night_learning_task, toolidx_task, backup_task, memconsol_task):
        _t.cancel()
    for _t in (cron_task, prewarm_task, whisper_task, watch_task, reminder_task, calsync_task, proactive_task, night_learning_task, toolidx_task, backup_task, memconsol_task):
        try:
            await _t
        except _asyncio.CancelledError:
            pass

# v2.79.0 — Compétences fiabilisées : (1) nomic-embed-text requis pour le matching
#   sémantique (sinon dégradé en lexical) ; (2) les compétences EXÉCUTENT vraiment les
#   outils — filet `_salvage_text_tool_calls` (récupère les appels écrits en texte/JSON,
#   résout les noms hallucinés) + re-prompt correctif quand le modèle explique au lieu
#   d'agir + prompt durci (agent.py) ; (3) invention de compétence robuste via parser
#   JSON tolérant `_parse_skill_json` (résiste aux quotes/sauts de ligne dans `body`).
# v2.80.0 — Compétences PLUS FORTES + AUTO-RÉPARANTES : (1) `pc_run_command` auto-route
#   vers PowerShell quand il détecte un cmdlet (fin de l'erreur « Get-… non reconnu » en
#   cmd) ; (2) moteur d'auto-upgrade — stats par compétence (skills_stats.json), versioning
#   automatique (data/skills/_versions/), `skills.upgrade_skill` (le LLM ré-écrit une
#   compétence après un échec d'outil) déclenché en arrière-plan par agent.py, + endpoints
#   stats/upgrade/versions/rollback ; (3) filet `_salvage_text_tool_calls` étendu au motif
#   nom-avant-accolade (profil chat 3b) ; (4) win_event_log : message clair si droits admin requis.
# v2.81.0 — 🥇 GOLDEN PATH (les compétences apprennent du SUCCÈS) : quand une compétence
#   réussit proprement, la SÉQUENCE d'outils gagnante est mémorisée (skills.record_success_trace,
#   garde la plus courte = la + efficace) et RÉINJECTÉE comme exemple few-shot au prochain
#   déclenchement (agent.py) → exécution + fiable sur petit modèle. Affiché dans l'UI Skills
#   (🥇 Déroulé appris). Raffinements : `_is_tooling_failure` ignore les erreurs ENVIRONNEMENTALES
#   (timeout, droits admin) → pas de faux auto-upgrade ; l'upgrade PRÉSERVE triggers+description
#   (le matching reste stable, seule la MÉTHODE est corrigée) ; win_service_action accepte `query`.
# v2.82.0 — 📦 RESSOURCES DE COMPÉTENCE (progressive disclosure) : une compétence peut
#   embarquer des fichiers de référence (modèles, tables de prix, check-lists) dans un sidecar
#   data/skills/<nom>.resources/. À l'activation, `skills.resources_prompt_block` injecte le
#   contenu des petites ressources INLINE et liste les gros fichiers/binaires à lire via
#   `file_read`. Endpoints CRUD /api/skills/{name}/resources (+ /upload binaire) + UI (panneau
#   « 📦 Ressources » dans la page Skills). Les ressources survivent à un rollback (sidecar).
#   `_is_tooling_failure` ignore aussi les « argument manquant » (entrée utilisateur ≠ défaut skill).
# v2.83.0 — 🔎 MINING PROACTIF + override modèle par machine : (1) `skills.suggest_skills`
#   analyse les demandes récurrentes (db.get_recent_user_messages) et propose des compétences
#   NON couvertes (parser bulletproof = collecteur récursif d'objets JSON ; exclusion stricte
#   à 0.80 pour ne pas écarter à tort) ; endpoints /api/skills/suggest(+/dismiss) + section UI
#   « 🔎 Suggestions ». (2) Réglage `model_overrides` (data/, distribuable) épingle un modèle par
#   profil — ici chat+agent+analysis = qwen2.5:14b (RTX 3080) → un seul modèle résident, zéro thrash.
# v2.84.0 — 📦 EMPORIUM (Winget, V3 phase 1) : gestionnaire de paquets universel. 5 outils
#   (winget_search/list_upgrades/install/upgrade/uninstall) + endpoints REST /api/winget/* +
#   onglet « Emporium ». Parser winget ROBUSTE par POSITIONS DE COLONNES (split('\r')[-1] pour
#   retirer le spinner, bornes = débuts de mots de l'en-tête) — fiable même quand un nom long
#   ne laisse qu'1 espace avant l'ID (cas VLC). Install/upgrade/uninstall = silencieux + confirmés.
#   Pilotable depuis le chat ET l'onglet. 261 → 266 outils.
# v2.85.0 — 🏛️ PANTHEON (V3 phase 2) + THÈME VIVANT. Pantheon : 8 outils d'optimisation
#   (system_restore_point, registry_get/backup/set, tweak_telemetry, tweak_debloat_list/remove,
#   tweak_network_harden) — toute écriture fait d'ABORD une sauvegarde (.reg / point de
#   restauration) + confirmation (réversible) ; endpoints /api/pantheon/* + onglet. 266 → 274
#   outils. Thème « Oracle » VIVANT (globals.css) : fond animé (aurore holographique + cœur
#   numérique qui bat), avatar SVG animé (LivingAvatar, s'accélère quand Marvin réfléchit),
#   titres holographiques, cartes vivantes. Re-skin global via variables CSS (--bg-primary translucide).
# v2.86.0 — 🧹 CATHARSIS + 🎛️ CODEX (V3 phases 3 & 4) → VISION V3 COMPLÈTE (4 piliers).
#   Catharsis (2 outils) : catharsis_scan (analyse l'espace récupérable par catégorie, SANS
#   supprimer — fix clé : chemins en DOUBLE quotes PS pour développer $env:TEMP) + catharsis_clean
#   (purge confirmée). Codex (5 outils) : os_power_plan, os_dark_mode, os_firewall,
#   os_network_adapters, os_hibernation (lecture libre, écriture confirmée). Endpoints
#   /api/catharsis/* et /api/codex/* + onglets. 274 → 281 outils. + execute_pc_run_powershell
#   force la sortie console en UTF-8 (fin des accents mojibake dans TOUS les outils PS).
# v2.87.0 — RETRAVAIL ERGONOMIE (retours utilisateur) : (1) onglets renommés en FONCTIONNEL
#   (Logiciels/Optimisation/Nettoyage/Système — plus de noms antiques en façade) ; (2) Logiciels :
#   winget_list_installed (chat-usable) + liste des 259 apps installées avec Désinstaller par ligne ;
#   (3) Nettoyage : refonte en TUILES façon CCleaner (13 catégories groupées Windows/Navigateurs/
#   Système + corbeille) ; (4) AVATAR VIVANT visible : grand Oracle animé (148px) sur l'accueil du
#   chat + header + sidebar (cœur qui bat, s'accélère quand Marvin réfléchit) ; (5) barre de chat
#   restylée (bordure holographique animée, glow or/cyan au focus). 282 outils.
# v2.88.0 — Panneau CONVERSATIONS retravaillé (app/page.js) : recherche/filtre en direct,
#   groupement par DATE (Aujourd'hui / 7 / 30 jours / Plus ancien via updated_at), RENOMMAGE
#   inline (✏️ → PUT /api/conversations/{id} {title}), actions révélées au survol, style vivant.
#   + sidebar groupée en sections (Assistant/PC & Système/Organisation/IA/Automatisation/Réglages).
# v2.89.0 — 🛡️ GARDE DE SÉCURITÉ D'EXÉCUTION (security.py, défense en profondeur). Screen
#   toute commande shell/PowerShell/SSH AVANT exécution ; BLOQUE EN DUR le catastrophique
#   irréversible (format X:, diskpart clean, Remove-Item -Recurse racine/système, rm -rf /,
#   mkfs, dd of=/dev/sd, cipher /w, bcdedit /delete, fork bomb…) — même en Expert / confirmé.
#   Conservateur (zéro faux positif testé : temp cleanup, suppression d'1 fichier, rm ./node_modules
#   passent). Câblé dans pc_run_command / pc_run_powershell / ssh_exec. C'est la brique
#   réutilisable du pattern « allowlist / séparation de privilèges » (cf. proposition sidecar).
# v2.90.0 — 🔐 SIDECAR ÉLEVÉ (séparation de privilèges, pattern proposé par l'utilisateur).
#   Nouveau démon séparé `elevated_daemon.py` : SEUL ce petit process tourne en administrateur
#   (le backend principal peut rester utilisateur normal). Canal IPC local = Named Pipe Windows
#   avec jeton partagé (`elevated_protocol.py` — contourne le piège MIC : un pipe créé par un
#   process élevé refuse par défaut l'écriture depuis un process non élevé ; on force l'étiquette
#   d'intégrité à Medium via SDDL). N'accepte qu'une ALLOWLIST (run_command/run_powershell/ping)
#   et revérifie `security.screen_command()` CÔTÉ ÉLEVÉ AUSSI (défense en profondeur — c'est en
#   admin que ça compte le plus). Nouvel outil `pc_run_elevated` (confirmation obligatoire,
#   bloqué en niveau Sécurisé). `elevated_client.py` = client utilisé par le backend, échoue
#   proprement si le démon n'est pas lancé. Lancement : `launch_elevated_daemon.ps1` (1 invite
#   UAC standard). **Prouvé en ÉLÉVATION RÉELLE** (pas seulement en théorie) : `net session`
#   (Erreur 5 refusé en non-admin) → succès via le canal élevé ; `format C:`/`Remove-Item
#   C:\ -Recurse` → bloqués même via le démon élevé ; jeton invalide → refusé. Journal d'audit
#   (source="elevated") vérifié. Le backend principal continue de tourner tel quel pour l'instant
#   (bascule complète en non-admin = étape suivante, opt-in, à faire avec l'utilisateur).
# v2.91.0 — 🌐 RÉSEAU PRO + 🧾 INVENTAIRE MATÉRIEL, portés d'un fork parallèle du projet
#   (secretary-ai-codex-groky-alpha, audité puis transplanté manuellement — pas de fusion en
#   bloc). 6 outils réseau : net_nmap_scan (nmap.exe si présent, sinon repli TCP asynchrone
#   interne), net_service_detect (bannières TCP), net_http_probe (statut/titre/en-têtes de
#   sécurité), net_tls_check (certificat : émetteur/SAN/expiration), net_subnet_sweep (CIDR
#   borné), net_route_diagnostics (connectivité complète). Scans larges → confirmation
#   obligatoire (_net_targets). + pc_hardware_specs : inventaire matériel (fabricant/modèle/
#   série, CPU, RAM, disques, GPU, cartes réseau) avec liens officiels support/pilotes déduits
#   du fabricant détecté (Dell/HP/Lenovo/ASUS/Acer/Surface/MSI/GIGABYTE/ASRock/Intel/AMD/
#   NVIDIA/Samsung/WD/Seagate/Crucial). Les 7 outils sont TESTÉS EN RÉEL sur cette machine (pas
#   seulement importés) : TLS google.com réel, ports RDP/SMB détectés localement, inventaire
#   matériel exact (ASUS STRIX Z270F, i7-7700K, RTX 2060, 32 Go RAM). 283 → 290 outils.
# v2.92.0 — 🎮 DÉTECTION GPU TEMPS RÉEL + amorce AMD natif. `local_video.get_device_info()`
#   passe d'un cache figé (permanent jusqu'au redémarrage) à un TTL COURT (20s) — corrige le
#   vrai bug trouvé en session (mémoire disait RTX 3080, la machine a une RTX 2060 : le cache
#   ne s'était JAMAIS rafraîchi). Nouvel outil chat `pc_gpu_status` (+ `refresh=true` pour forcer
#   une redétection immédiate juste après un changement de carte — utile pour tester des cartes
#   clients). Amorce DirectML (`_detect_directml_gpu`) : seule voie native pour faire tourner
#   PyTorch sur un GPU AMD sous Windows (ROCm = Linux uniquement) ; se dégrade proprement si le
#   paquet est absent. **Constat honnête** : `torch-directml` n'a AUCUNE version compatible avec
#   Python 3.14 (ce venv) → le calcul AMD natif reste bloqué par l'environnement, pas par le code
#   (options : venv dédié Python 3.10/3.11 pour la vidéo, à discuter, PAS fait silencieusement).
#   290 → 291 outils.
# v2.93.0 — 🪟 CATALOGUE « Windows+ » (win_quick_launch/win_quick_launch_list), 29 raccourcis
#   groupés (God Mode / Paramètres Windows / Panneaux legacy / Outils admin / Performance /
#   Maintenance / Dossiers utiles), porté du fork — CATALOGUE DE NAVIGATION SEULEMENT (leur
#   système de tweaks/registre séparé n'est PAS repris, il chevauche Pantheon existant). Risque
#   quasi nul : `os.startfile` (+ repli `cmd /c start`), n'écrit rien sauf God Mode (dossier vide
#   standard). Testé en réel : ouverture du dossier Temp confirmée. + routage par mots-clés pour
#   les 3 derniers ajouts (pc_gpu_status, win_quick_launch*) — leçon apprise cette session :
#   un outil non découvert par le filtre de mots-clés n'est jamais proposé au LLM. 291 → 293 outils.
# v2.94.0 — 🎙️ VOIX CONSOLIDÉE + choix du micro. Nouveau module partagé
#   `lib/voice/voiceRecorder.js` : ChatInput.jsx et useVoice.js avaient CHACUN leur propre copie
#   de la capture micro (getUserMedia + VAD + MediaRecorder), avec les MÊMES 3 défauts dupliqués
#   deux fois — aucun choix de périphérique (toujours le micro système par défaut, impossible de
#   passer sur un casque Bluetooth), mimeType 'audio/webm' figé sans repli, VAD peu sensible
#   (seuil 0.025/1100ms ratait les phrases courtes). Centralisé en un seul module : repli robuste
#   à 3 niveaux (deviceId exact → ideal → défaut, efface le choix mémorisé s'il est cassé —
#   micro Bluetooth éteint/débranché ne bloque plus rien), détection MIME réelle du navigateur,
#   VAD réglé à 0.006/120ms/900ms. Sélecteur de micro (▾) ajouté dans ChatInput ET dans la page
#   /vocal, backés par `useVoice()` (device list + persistance localStorage, partagés via
#   ChatContext). Erreurs micro/transcription remontées à l'UI (fini l'échec silencieux).
#   TESTÉ EN RÉEL (Playwright, permission micro accordée) : périphériques système réels détectés
#   dont un vrai casque Bluetooth (Bose QC35 II), sélection → persistance localStorage →
#   ré-affichage coché après réouverture du menu, /vocal sans erreur console. 293 outils (inchangé
#   — travail frontend, pas de nouvel outil).
# v2.95.0 — 📖🌙 LEARNING LOG + CONSOLIDATION NOCTURNE, transplanté du fork Codex/Grok. Jusqu'ici
#   Marvin apprenait déjà des échecs/réussites PAR compétence (auto-upgrade sur échec d'outil,
#   golden path sur succès — v2.79-81) mais rien ne consolidait cet apprentissage AU NIVEAU
#   GLOBAL, et rien ne tournait la nuit. Nouveau : `skills.log_learning_event/get_learning_log`
#   — journal persistant (`data/skills_learning_log.json`, 200 derniers événements, avec diffs)
#   de toute création/upgrade/consolidation/oubli de compétence, câblé aux 3 points de création
#   (manuelle, génération ✨, extraction 🧠) + à `upgrade_skill`. `review_and_consolidate_learnings`
#   (le LLM relit son propre log par compétence et peut proposer UNE fusion/consolidation si un
#   vrai pattern se dégage) + `consolidate_obsolete_skills` (archive — jamais supprime — les
#   compétences >30j sans usage et <3 usages au total, rollback possible). Nouveau worker de fond
#   `_skill_night_learning_worker` : cadence 15 min la nuit (22h-6h) vs 25 min le jour — Marvin
#   revoit son apprentissage sans intervention, plus activement la nuit. Endpoints
#   `/api/skills/learning_log` (GET) + `/api/skills/consolidate` (POST, déclenchement manuel) +
#   nouvel outil chat `skill_learning_log` (introspection : « qu'as-tu appris récemment ? »).
#   TESTÉ EN RÉEL : création d'une compétence → événement "create" loggé et relu via l'endpoint
#   et l'outil chat ; consolidation manuelle déclenchée sans erreur (reviewed=null car <3
#   événements, comportement attendu, conservateur) ; worker de fond démarré et tourne sans
#   exception. 293 → 294 outils.
# v2.96.0 — 🩹 CORRECTIF EVENT-LOOP BLOQUANTE + 🎯 OUTIL EXPLICITE RESPECTÉ (audit fork
#   Codex/Grok). Trouvé en auditant `tools.py` : `subprocess.run()` était appelé de façon
#   SYNCHRONE dans des `async def execute_*`, ce qui GÈLE TOUT FastAPI (chat, `/api/health`,
#   tout) pendant la durée de la commande — jusqu'à **30 MINUTES** pour `winget upgrade --all`
#   (timeout=1800s). 12 sites `subprocess.run` directs + 6 appels à `_winget_run` corrigés :
#   tous passent maintenant par `await asyncio.to_thread(...)` (pc_run_command, pc_run_powershell,
#   winget_*, _reg_backup avant chaque tweak Pantheon, clipboard get/set, pc_notify, pc_window_list,
#   net_scan_local, git_info). PREUVE RÉELLE : `ping -n 8` (7,3s) lancé en tâche de fond via
#   `pc_run_command`, `/api/health` interrogé PENDANT l'exécution → répond en 24ms puis 1,6ms
#   (avant ce correctif, `/api/health` aurait attendu les 7,3s). net_ping accepte maintenant
#   `target`/`ip` en alias de `host` (robustesse). + `agent.py` détecte les noms d'outils cités
#   EXPLICITEMENT par l'utilisateur (`_exact_tool_mentions_from_text`) : l'outil nommé est imposé
#   pour le tour (tools_payload restreint) et toute substitution est bloquée à l'exécution
#   (corrige un cas réel du fork : demande `file_find`, le modèle appelait `net_ping`). Testé :
#   détection correcte sur 4 phrases (exact-match + zéro faux positif sur du texte normal).
#   294 outils (inchangé — corrections internes, pas de nouvel outil).
# v2.97.0 — 🎨 REFONTE UI COMPLÈTE — console IA professionnelle. Sur demande explicite de
#   l'utilisateur : « je veux que l'UI ressemble à celle d'une IA pro, repense toute l'UI ».
#   Pivot du thème « Oracle » (or/mystique, aurore animée, cœur qui bat, hexagones antiques —
#   v2.85-2.87) vers une palette graphite neutre + bleu électrique/cyan (`app/globals.css`) :
#   fond fixe opaque (plus d'aurore radiale animée en fond de page), accents #4f8cff/#38bdf8,
#   rayons de bordure resserrés (look outil, pas pilule partout), police mono ajoutée pour les
#   accents techniques. `.holo-text`/`.living-card`/`.breathe`/`.float-y` CONSERVÉES (utilisées
#   dans 7+ fichiers) mais redéfinies en version calme (texte plein, pas de dégradé arc-en-ciel ;
#   survol = relief discret, pas de halo coloré). Migration mécanique de TOUTES les couleurs or
#   codées en dur (#c9a84c/#e8c96d/#e8c96a/#dab95e/#35e0d0 + leurs rgba, 32 fichiers) vers la
#   nouvelle palette — zéro résidu vérifié par grep. `LivingAvatar.jsx` réécrit : l'ancien
#   « Oracle antique » (yeux dorés, hexagone pierre, laurier, circuits gravés) remplacé par un
#   badge de statut géométrique sobre (anneau + cœur qui pulse, un seul accent bleu). Sidebar :
#   suppression de l'icône robot inutilisée (dead code), nettoyage des mentions « Oracle »
#   (tooltip/commentaires). Vérifié en réel (Playwright, 3 pages : accueil chat, Outils,
#   Paramètres) : zéro erreur console, rendu cohérent sur tout l'écran.
# v2.98.0 — 🗂️ REFONTE NAVIGATION — regroupement par sujet + mode vocal fusionné au chat.
#   Sur demande explicite : « travaille la mise en page, regroupe ce qui est du même sujet de
#   façon pro, intuitif ». Constat : ~30 destinations plates dans la sidebar, dont 8 pour "PC &
#   Système" (Outils/Logiciels/Optimisation/Nettoyage/Système/Santé/SSH/Monitoring) et 3 pour
#   les fichiers (Fichiers/Mes documents/Indexation) qui se recoupaient sans que l'utilisateur
#   puisse deviner laquelle contient quoi. **Fusion en 2 hubs à onglets internes** (zéro
#   fonctionnalité perdue) :
#   - `/systeme` (🖥️ PC & Système) : onglets Santé/Logiciels/Optimisation/Nettoyage/Système —
#     regroupe emporium/pantheon/catharsis/codex/sante (SSH et Monitoring restent séparés,
#     sujet différent : machines distantes / supervision continue).
#   - `/fichiers` : onglets Parcourir/Documents/Recherche PC — regroupe files/documents/indexation.
#   Implémentation : chaque ancienne page exporte maintenant sa vue (`XxxView`) réutilisable EN
#   PLUS de son ancien rendu ; l'ancienne route (`/emporium`, `/pantheon`, `/catharsis`, `/codex`,
#   `/sante`, `/files`, `/documents`, `/indexation`) redirige (`router.replace`, useEffect) vers
#   le hub avec le bon onglet préselectionné → tout ancien lien/favori continue de marcher.
#   **Mode vocal fusionné au chat** : `/vocal` avait une UI dédiée (orbe, mode mains libres) qui
#   faisait EXACTEMENT doublon avec le bandeau « Mode vocal actif » déjà présent dans
#   `ChatContainer.jsx` (voix/vitesse/barge-in/toggle, vérifié dans le code avant suppression) —
#   `/vocal` redirige maintenant simplement vers `/`. **Sidebar des conversations repliable**
#   (`app/page.js`) : poignée fine `◀/▶` entre la liste et la zone de chat, état persistant
#   (`localStorage`), CSS désactive la poignée sur mobile (le tiroir mobile existant suffit).
#   Sidebar nav : 30 → ~24 entrées. Vérifié en réel (Playwright) : les 3 anciennes routes
#   redirigent vers les bons onglets, le hub Santé affiche un vrai score 100/100 (294 outils
#   cohérents), le hub Fichiers affiche le vrai contenu du disque, le repli/dépli de la sidebar
#   fonctionne (la zone de chat s'élargit), zéro erreur console sur l'ensemble du parcours.
# v2.99.0 — ⏳ RETOUR VISUEL "MARVIN TRAVAILLE" — sur demande explicite (« je dois savoir que
#   Marvin travaille »). Nouveau `TopLoadingBar` : fine barre de progression animée en haut de
#   l'écran, visible sur N'IMPORTE QUELLE page tant qu'une requête chat est en cours (branchée
#   sur `useChatStatus().isLoading`, donc visible même si l'utilisateur a navigué ailleurs
#   pendant que Marvin répond). Nouveau composant réutilisable `Spinner`/`LoadingRow`
#   (`components/ui/Spinner.jsx`, sablier CSS pur `.spinner-ring`) qui remplace 13 textes
#   "Chargement..." bruts sans aucun signal visuel, répartis sur 12 fichiers (calendar, cron,
#   devis, docs, emails ×2, memoire, monitoring, notes, outils ×2, tasks, video,
#   FileExplorerCard) — désormais tous avec un sablier animé. Le bouton d'envoi du chat
#   (déjà correct) bascule en bouton ⏹ Stop pendant la génération. Aucune fonctionnalité
#   retirée, uniquement des indicateurs de chargement ajoutés/harmonisés. Vérifié en réel
#   (Playwright, 14 pages) : zéro erreur console.
# v2.100.0 — 📊 REFONTE MONITORING (bug de scroll + panneaux fonctionnels). Signalé par
#   l'utilisateur : `/monitoring` n'avait aucun scroll (conteneur racine `minHeight:'100vh'`
#   sans `overflowY`) → les stats/historique en bas de page étaient invisibles. Au-delà du
#   correctif, refonte du concept : la page entière poussait tout à la verticale (une seule
#   longue page à faire défiler). Nouveau pattern **panneaux à défilement indépendant**
#   (`Panel`, maxHeight 560px + overflow interne) : les jauges CPU/RAM/Réseau/Disques restent
#   groupées et visibles sans scroll long, pendant que « Dernières exécutions » et
#   « Statistiques » défilent chacun dans leur propre zone. Historique d'outils enfin
#   exploitable : recherche par nom d'outil + filtre Tout/Succès/Échec (composables), et
#   chaque ligne se déplie au clic pour montrer arguments + résultat/erreur (`PrettyResult`,
#   données déjà en base via `db.list_executions`, jamais affichées avant). Taux d'échec (%)
#   ajouté aux statistiques, coloré selon la sévérité. Vérifié en réel (Playwright) : scroll
#   fonctionne, filtre+recherche combinés isolent correctement (32 échecs `calendar_list`
#   trouvés), dépliage affiche arguments/résultat lisible, zéro erreur console.
# v2.101.0 — 🎯 4 PROPOSITIONS D'ERGONOMIE (validées par l'utilisateur : « je suis ok pour tes
#   4 propositions go »).
#   1) **Toasts unifiés** : `components/ui/Toast.jsx` (ToastProvider/useToast) existait déjà
#      mais n'était monté nulle part — 9 pages (emporium/pantheon/catharsis/codex/sante/skills/
#      documents/indexation) + 3 de plus trouvées en auditant plus large (devis/docs/cron)
#      réinventaient chacune leur propre bandeau `useState`+`setTimeout`. Toutes migrées vers
#      `useToast()` (déstructurer `.toast` — piège découvert et corrigé : le hook renvoie
#      `{addToast, removeToast, toast}`, pas directement les méthodes). Bug annexe corrigé dans
#      `Toast.jsx` : `useAutoClose` utilisait `useState(() => {...})` comme s'il s'agissait de
#      `useEffect` → le timer de fermeture auto n'était jamais nettoyé au démontage (fuite).
#      `ToastProvider` monté une fois dans `layout.js`. `components/chat/FileExplorerCard.jsx`
#      gardé intentionnellement à part (toast positionné à côté du fichier concerné dans l'arbre,
#      pas un bandeau générique — pertinent tel quel).
#   2) **Palette de commandes (Ctrl+K)** : `components/ui/CommandPalette.jsx`, monté globalement,
#      indexe `NAV_SECTIONS` (exporté depuis `Sidebar.jsx`) + une action "Nouvelle conversation".
#      Navigation clavier complète (flèches, Entrée, Échap), ouverture aussi via un bouton dans
#      la sidebar (`window.dispatchEvent(new Event('marvin:open-command-palette'))`).
#   3) **`components/ui/DashboardKit.jsx`** : extraction de `CircleGauge`/`BarRow`/`StatCard`/
#      `Sparkline`/`Panel` (construits pour /monitoring v2.100) en bibliothèque partagée — toute
#      future page-dashboard réutilise au lieu de recopier des styles inline. `/monitoring`
#      migré pour les importer (zéro changement visuel, vérifié).
#   4) **Raccourcis clavier** : Ctrl+N (nouvelle conversation, marche même déjà sur "/" via
#      l'event `marvin:new-conversation" — un simple `router.push('/')` y serait un no-op),
#      Échap ferme le menu de sélection du micro dans `ChatInput.jsx`.
#   Vérifié en réel (Playwright) : toasts empilés avec bonnes couleurs/icônes lors d'une vraie
#   action (scan Catharsis), Ctrl+K ouvre/filtre/navigue, Ctrl+N réinitialise la conversation,
#   zéro erreur console sur 14 pages testées.
# v2.102.0 — 🔧 BOÎTE À OUTILS REGROUPÉE PAR FAMILLES. Signalé par l'utilisateur : 17 catégories
#   d'outils (Infographie/Documents/Fichiers/Web/PC & Système/Calendrier/Cloud/Tâches & Notes/
#   Mémoire & IA/Réseau/OCR & Vision/Email/SSH/Archives/Voix & Audio/Utilitaires/Données & Docs)
#   affichées en UNE rangée d'onglets horizontaux qui débordait déjà l'écran — illisible.
#   Ajout d'un niveau intermédiaire (`GROUPS` dans `app/outils/page.jsx`, même logique que les
#   sections de la sidebar) : 4 familles — 📄 Contenu & Documents, 🖥️ Système & Réseau,
#   🗂️ Organisation, 🌐 Web & Données — puis les catégories du groupe sélectionné en sous-onglets.
#   17 onglets à plat → 4 familles + sous-onglets courts. La recherche globale (déjà correcte,
#   cherchait déjà dans les 141 outils toutes catégories confondues) n'est pas affectée : elle
#   masque les deux rangées d'onglets comme avant. Petite redondance clarifiée : l'outil rapide
#   « Nettoyer le disque » (PC & Système) renvoie maintenant explicitement vers PC & Système →
#   Nettoyage pour la version détaillée par catégorie (ex-Catharsis). 141 outils inchangés
#   (réorganisation d'affichage uniquement, zéro perte). Vérifié en réel (Playwright) : clic sur
#   une famille affiche ses catégories, clic sur une catégorie affiche ses outils, zéro erreur
#   console.
# v2.103.0 — 🔌 MARVIN EN SERVEUR MCP (Model Context Protocol) — recherche web + sécurité
#   d'abord (voir échange utilisateur : demande explicite d'explorer MCP "sans oublier la
#   sécurité"). Constat de la recherche : MCP est devenu LE standard 2026 pour connecter une IA
#   à des outils (Claude/ChatGPT/Gemini/Copilot/Cursor, 10 000+ serveurs) MAIS l'écosystème a une
#   crise de sécurité documentée (faille SDK officielle ~200k instances, 38% des serveurs sans
#   authentification, 30+ CVE injection shell en 2 mois, attaques "rug pull" par mise à jour
#   malveillante). Décision : implémenter UNIQUEMENT le sens serveur (exposer les outils DÉJÀ
#   vérifiés de Marvin) — PAS le sens client (consommer des serveurs MCP tiers non audités),
#   qui reste une décision séparée à prendre au cas par cas.
#   Architecture (`backend/mcp_server.py`, transport stdio, lancé par le client MCP en
#   sous-processus) : PROXY RÉSEAU PUR vers le backend Marvin déjà démarré — n'importe JAMAIS
#   `tools.py`/`database.py` directement (Qdrant est mono-process, un import direct depuis un
#   2ᵉ process risquerait `AlreadyLocked`). Nouveau `GET /api/tools/list` (catalogue des 294
#   outils pour la découverte MCP) + nouveau `POST /api/mcp/execute`, DÉLIBÉRÉMENT séparé de
#   `/api/tools` : ce dernier force `confirmed=true` sur les outils dangereux (conçu pour les
#   boutons de la page Outils, qui ont DÉJÀ demandé confirmation avant l'appel) — le forcer pour
#   un appelant MCP externe permettrait une exécution destructrice sans confirmation. Le nouvel
#   endpoint respecte le niveau de permission ACTUEL de Marvin (Sécurisé/Standard/Expert) : en
#   Expert, confirmation auto (comme le reste de Marvin) ; sinon, `requiresConfirmation` remonte
#   normalement au client MCP, qui doit re-soumettre avec confirmed=true si SON utilisateur
#   approuve. `security.screen_command()` reste actif à l'intérieur de chaque outil (défense en
#   profondeur, inchangé). Audit tracé avec `source="mcp"` (distinct de "chat"/"ui"). Le serveur
#   ne démarre QUE si un client MCP le lance explicitement (config manuelle côté Claude
#   Desktop/Cursor) — aucun port ouvert par défaut, zéro découverte automatique.
# v2.104.0 — 🔌 PAGE /mcp — GUIDE DE CONNEXION MCP. Sur demande explicite (« ajouter un onglet
#   qui explique le MCP et comment s'y connecter », avec l'exigence : « les chemins doivent être
#   dynamiques, si j'installe Marvin sur une autre machine le MCP doit être sur le bon chemin »).
#   Nouveau `GET /api/mcp/config` : renvoie les chemins RÉELS de CETTE installation — jamais codés
#   en dur. `sys.executable` (le python.exe du venv réellement utilisé, où que Marvin soit
#   installé) + `config.BACKEND_DIR / "mcp_server.py"` (déjà dynamique, `Path(__file__).parent`).
#   Testé : sur cette machine, renvoie bien `C:\Users\Chawb\secretary-ai\backend\.venv\...` — sur
#   une autre installation, les chemins suivraient automatiquement sans aucune modification de
#   code. Nouvelle page `/mcp` (sidebar → Réglages, entre Accès mobile et Paramètres, même esprit
#   que la page de connexion mobile existante) : statut backend en direct, niveau de permission
#   actuel avec explication de son impact sur MCP, bloc JSON prêt à copier (bouton avec toast de
#   confirmation), explication courte du choix « serveur uniquement, jamais client ». Piège
#   récurrent re-attrapé : `useToast()` renvoie `{toast}`, pas directement les méthodes — corrigé
#   avant que ça parte en prod (déjà documenté dans CLAUDE.md depuis v2.101, mais reproduit une
#   fois de plus en écrivant ce composant, donc vérifié explicitement cette fois). Vérifié en réel
#   (Playwright) : statut/permission/JSON corrects, clic sur Copier déclenche le toast, zéro
#   erreur console.
# v2.105.0 — 🧹 3 PETITES DETTES REFERMÉES (suite auto-proposée après audit). (1) Marvin Doctor
#   vérifie maintenant le serveur MCP (`doctor.py` check #11) : paquet `mcp` installé + syntaxe
#   de `mcp_server.py` valide (compile() sans exécuter). (2) Palette de commandes (Ctrl+K) : la
#   recherche n'indexait que les pages, pas les 294 outils. Le catalogue d'outils est maintenant
#   chargé à la demande (1ʳᵉ ouverture de la palette seulement, pas au chargement de chaque page)
#   depuis `/api/tools/list`, et un résultat "outil" sélectionné navigue vers
#   `/outils?q=<nom>` — `app/outils/page.jsx` lit ce paramètre `q` au montage pour préremplir sa
#   recherche (a nécessité un `Suspense` autour du composant, requis par `useSearchParams`).
#   (3) `CircleGauge` (`DashboardKit.jsx`) avait un seuil de couleur pensé pour un usage
#   ressource (haut = mauvais, ex. CPU/RAM) — nouvelle option `invert` (haut = bon, ex. score de
#   santé) + `suffix` personnalisable ("/100" au lieu de "%"). La page Santé utilise maintenant
#   ce composant partagé au lieu d'un `conic-gradient` fait main. Vérifié en réel (Playwright) :
#   check Doctor MCP → "ok", Ctrl+K + "csv_analyze" + Entrée → atterrit sur l'outil pré-filtré,
#   gauge Santé toujours vert à 100/100, zéro erreur console.
# v2.106.0 — 🩺 AUDIT COMPLET SUR DEMANDE EXPLICITE (« revois tout les chats, teste/corrige/
#   améliore tous les outils, règle la température Ollama pour éviter les hallucinations »).
#   Audit basé sur `data/secretary.db::tool_executions` (754 exécutions réelles, 141 échecs
#   historiques), triés un par un (déjà corrigé / comportement attendu / vrai bug) plutôt que
#   supposés. 6 vrais bugs d'outils corrigés (tools.py) : (1) `_resolve_path` ne corrigeait
#   l'alias Bureau→Desktop que si le nom d'utilisateur était FAUX dans le chemin — jamais si déjà
#   correct (`pc_open_file` échouait sur "C:\Users\Chawb\Bureau"). (2) `pc_open_file` retombe
#   maintenant sur `pc_app_launch` si le chemin ressemble à un nom d'appli sans extension
#   (corrige "ouvre firefox/teraterm"). (3) `json_tool` accepte `json` en alias de `data`.
#   (4) `ocr_extract` valide le modèle Ollama demandé contre les modèles réellement installés,
#   repli silencieux sur `llava-phi3` si halluciné (ex. "llava:13b" jamais installé → 404 sec).
#   (5) `net_dns_lookup` accepte `domain`/`hostname` en alias de `host`. (6) `translate` accepte
#   `source`/`target` en alias de `source_lang`/`target_lang` (sinon retombait en silence sur
#   auto→en, faux sans erreur visible). (7) `file_convert_docx_to_pdf` : bloquait tout FastAPI
#   pendant la conversion Word (pas de `asyncio.to_thread`) + oubliait `pythoncom.CoInitialize()`
#   sur le thread d'exécution (même piège COM que `system_search`, déjà corrigé là-bas). (8)
#   `billing_quote_pdf` : `Unknown format code 'f' for str` quand un devis JSON produit par le
#   LLM contient des nombres en string — coercion défensive `_num()`.
#   Anti-hallucination Ollama, à la racine (agent.py) : la branche « modèle choisi manuellement »
#   avait la température INVERSÉE par rapport à la doctrine de `config.py::MODEL_PROFILES` —
#   elle montait à 0.6 pour les PETITS modèles (3b/1b), alors que ce sont eux les plus sujets à
#   halluciner un nom d'outil/paramètre plausible mais faux (cause racine du bug ocr_extract
#   ci-dessus). Corrigé : 0.2-0.3 partout, cohérent avec le reste. Ajout de `top_p: 0.9` à toutes
#   les requêtes Ollama (resserre l'échantillonnage). Nouvelle règle d'or #7 dans le prompt
#   système : ne jamais inventer un identifiant technique qui « sonne juste » (modèle IA, version,
#   ID), laisser le paramètre optionnel vide plutôt que deviner.
#   Test réel élargi : `system_self_test` passe de 16-18 à 46 outils couverts (tools.py, tous
#   lecture seule, zéro effet de bord) ; + 24 outils supplémentaires testés manuellement via
#   `/api/mcp/execute` (OS/réseau/texte/documents). 69 outils vérifiés au total sur cette session,
#   0 nouveau bug au-delà des 8 ci-dessus (les échecs restants étaient soit déjà corrigés, soit du
#   bruit de méthodologie de test — ex. conflit de verrou Qdrant en appelant `search_semantic` en
#   script autonome au lieu de passer par le backend déjà lancé, cf. règle connue).
#   Revue des mémoires de sessions passées → 1 vraie dette de sécurité trouvée et corrigée :
#   `audit.py::log_action` ne filtrait les secrets que par égalité stricte de nom de clé
#   ("password"/"token"/"secret") → ratait `owner_password`, `bot_token`, `api_key`,
#   `client_secret`, `private_key` etc., qui finissaient en clair dans le fichier JSONL git-able.
#   Filtre passé en sous-chaîne (insensible à la casse) sur une liste élargie. Les autres pistes
#   des mémoires (COM/asyncio.to_thread, backup registre avant tweak) étaient déjà correctement
#   en place — vérifiées, pas re-corrigées inutilement.
# v2.107.0 — 🧹 JSON hors du chat + 5 axes (suite auto-proposée après l'audit v2.106, sur
#   demande explicite « tout format json doit disparaitre du chat » + « fait tout »).
#   BUG RACINE trouvé et corrigé : `MessageBubble.jsx::renderToolResult` (le composant
#   RÉELLEMENT rendu en live, pas `ToolCallCard.jsx` qui s'est avéré être du code mort jamais
#   importé) retombait sur un `JSON.stringify` brut par défaut pour tout outil sans rendu
#   dédié — soit la grande majorité des 294 (ex. winget_search). Corrigé : le fallback utilise
#   désormais `PrettyResult` (déjà existant mais jamais branché ici) → lisible par défaut,
#   JSON disponible uniquement via son bouton « Voir en JSON ». Vérifié en réel (Playwright)
#   sur une conversation réelle affichant ce bug.
#   5 axes supplémentaires : (1) suppression de `ToolCallCard.jsx`/`.module.css`, code mort
#   (zéro import) qui dupliquait `MessageBubble::ToolCallInline` — source unique désormais.
#   (2) `app/api/conversations/*` transformé en proxy pur vers le backend Python (qui avait
#   déjà une implémentation équivalente plus correcte) au lieu de dupliquer l'accès SQLite
#   direct côté JS (`lib/database/queries.js`, même fichier `data/secretary.db` que Python) —
#   dette dupliquée déjà repérée dans le fork Codex/Grok, confirmée présente ici aussi. Bug
#   trouvé au passage et corrigé côté Python : `update_conversation` ne pouvait jamais
#   désassigner un projet (`body.projectId is not None` ignorait un `null` explicite) —
#   passé en `model_dump(exclude_unset=True)`. Testé en réel (rename/restore, assign,
#   delete sur conversation jetable). (3) `PrettyResult.jsx` enrichi : formatage monétaire
#   (`total_ttc`, `unit_price`…), puces de statut colorées (payée/en retard/running/stopped…),
#   libellés FR pour les familles billing_*/win_*. (4) Le profil `analysis` envoyait les 294
#   outils SANS filtrage (risque de hallucination de nom d'outil sur un si gros catalogue,
#   déjà repéré dans les mémoires) — applique désormais le même filtrage mots-clés+sémantique
#   que chat/agent, avec un plafond plus large (90 vs 28) pour garder la couverture. Vérifié :
#   requête "caractéristiques matérielles" → 29 outils pertinents incluant bien
#   `pc_hardware_specs` (au lieu de 294 bruts). (5) `scripts/smoke_test_chat.py` (nouveau) :
#   recharge des conversations réelles via Playwright et détecte tout dump JSON multi-clés
#   visible par défaut — regex volontairement ciblée sur les dumps multi-paires (le vrai bug)
#   pour ne pas remonter de faux positifs sur un autre problème distinct et déjà atténué
#   (un appel d'outil écrit en texte par le LLM, {"query":"..."} à une seule clé — cf. §5
#   CLAUDE.md, `_salvage_text_tool_calls`). A servi à re-tester tout ce qui précède.
# v2.108.0 — 🧹 Dualité JS/Python éliminée sur notes/tâches/projets/mémoire (suite directe
#   de v2.107, sur demande explicite « continue sur cette voie » puis « fait les 5 »).
#   `app/api/chat/route.js` (255 lignes, moteur de chat JS legacy 100% mort) supprimé sur
#   confirmation explicite après avoir été bloqué une 1ère fois par le classifieur de
#   permissions (action jugée trop destructive pour une inférence autonome — comportement
#   voulu, contourné correctement en redemandant). DÉCOUVERTE EN COURS DE ROUTE, PAS ENCORE
#   TRAITÉE : `app/api/tools/route.js` + `lib/agent/tools.js` (1344 lignes) forment un
#   second moteur d'agent JS complet, également confirmé 100% mort (zéro appelant réel,
#   l'Outils page appelle `${BACKEND_URL}/api/tools` en Python, pas la route relative) —
#   signalé à l'utilisateur, pas supprimé sans confirmation explicite (même prudence que
#   pour app/api/chat).
#   `/api/notes` et `/api/tasks` transformés en proxy pur vers le backend Python (déjà un
#   CRUD complet côté Python) — même pattern que `/api/conversations` en v2.107, interface
#   externe (POST {action,...}) conservée à l'identique pour ne toucher aucune page.
#   `/api/projects` : Python n'avait qu'une lecture (`get_projects`) — ajouté
#   `create_project`/`delete_project` (+ `CREATE TABLE IF NOT EXISTS` défensif, la table
#   n'était créée que côté JS jusqu'ici) et les endpoints POST/DELETE, puis proxyfié.
#   Actions mémoire de `/api/settings` (get/create/delete/clear_memories) proxyfiées vers
#   `/api/memories` (Python) — dupliquaient `memory_save`/`memory_list`/`memory_delete`,
#   déjà des outils de chat. Ajouté côté Python : `POST /api/memories` et
#   `DELETE /api/memories` (clear-all), qui n'existaient pas. La gestion de modèles Ollama
#   (pull/delete/list/set_model) reste en JS — pas de duplication, pas d'équivalent Python.
#   `lib/database/queries.js` élagué de 38 à 2 exports (`getSetting`/`setSetting`, les seuls
#   encore réellement importés) — 36 fonctions mortes retirées (conversations/messages/
#   tasks/notes désormais orphelines par ce ménage même, + OAuth/journal fichiers/templates
#   email jamais appelés, dette préexistante). Chaque proxy testé en réel bout-en-bout
#   (create/update/delete) avant/après bascule, y compris un vrai bug trouvé au passage :
#   `update_conversation` (Python) ne pouvait jamais désassigner un projet — déjà corrigé
#   en v2.107, revérifié ici. `scripts/smoke_test_chat.py` reste vert après chaque étape.
# v2.109.0 — 🕐 Bug de fuseau horaire sur les timestamps (trouvé en continuant l'audit v2.108
#   sur demande explicite « continue le travail »). En testant la création de note via l'UI
#   réelle (pas juste curl), une note tout juste créée affichait « il y a 2h » au lieu
#   d'« à l'instant ». Cause racine : le backend renvoie des timestamps SQLite UTC naïfs
#   ("2026-07-09 08:05:10", sans 'Z'/fuseau) — `new Date(...)` côté navigateur les interprète
#   comme une heure LOCALE en l'absence d'indicateur de fuseau explicite, décalant tout
#   affichage relatif/absolu de l'écart UTC local de l'utilisateur (ex. +2h en France l'été).
#   Le correctif (ajout de 'Z' avant parsing) existait déjà dans `app/cron/page.jsx` et
#   `app/monitoring/page.jsx` mais n'avait jamais été appliqué ailleurs — bug préexistant,
#   pas une régression de cette session, juste jamais repéré faute de test réel via l'UI.
#   Corrigé dans `app/notes/page.jsx` (liste + panneau « Créé/Modifié »), `app/docs/page.jsx`
#   (calcul « résolu cette semaine »), `app/workflows/page.jsx` (historique d'exécutions),
#   `app/page.js` (regroupement de la sidebar conversations Aujourd'hui/7j/30j — pouvait
#   mal classer une conversation faite juste après minuit local). `components/chat/
#   PrettyResult.jsx::fmtDate` corrigé avec une garde (n'ajoute 'Z' que si la chaîne n'a pas
#   déjà un fuseau explicite) car ce composant affiche aussi des dates déjà correctement
#   fuseautées (emails, événements calendrier) — un ajout aveugle de 'Z' les aurait cassées.
#   Vérifié en réel : création d'une note via clic UI → « à l'instant » correct après le fix
#   (contre « il y a 2h » avant), ré-affichage d'une note de 3 min → « il y a 3 min » correct.
# v2.110.0 — 🧹 Suppression du 2e moteur d'agent JS mort (suite de v2.108/v2.109, sur
#   confirmation explicite via AskUserQuestion après 2 refus du classifieur de permissions
#   sur des directives génériques « continue »/« tu es libre »). `app/api/tools/route.js`
#   + `lib/agent/tools.js` (1344 lignes) supprimés — code confirmé 100% mort depuis v2.108
#   (zéro import, zéro appel `/api/tools` relatif nulle part dans le code ; la page Outils
#   appelle `${BACKEND_URL}/api/tools`, l'endpoint Python homonyme mais différent). Vérifié
#   après coup : compilation Next.js propre, `scripts/smoke_test_chat.py` toujours vert.
#   Incident survenu pendant la vérification (documenté, pas dans le code) : un test de
#   suppression via clic Playwright automatisé avec un sélecteur DOM imprécis (ancestor +
#   « dernier bouton ») a supprimé une VRAIE conversation utilisateur au lieu d'un projet
#   de test — détecté en recoupant le compteur de conversations avant/après, pas par une
#   erreur. Pas de sauvegarde automatique de `data/secretary.db` trouvée pour la récupérer.
#   Règle retenue pour toute suite : ne jamais tester une action destructive via clic UI
#   automatisé sur des données réelles — sélecteur univoque (title/id) sur données jetables
#   uniquement, ou suppression par ID exact via curl/API directe.
# v2.111.0 — 💾 Sauvegarde auto + 🗂️ Fin de la dualité fichiers + 🧪 Smoke-test pages (3
#   propositions faites après le point précédent, toutes acceptées explicitement).
#   (1) `backend/backup.py` : sauvegarde quotidienne de `data/secretary.db` via l'API
#   native SQLite (`Connection.backup()`, pas une copie fichier brute — la base est en
#   mode WAL, une copie naïve pourrait capturer un état incohérent pendant une écriture
#   active). Une sauvegarde immédiate au démarrage (20s de délai) + une toutes les 24h,
#   rotation sur les 14 dernières. Endpoints `GET/POST /api/backups`. Motivé directement
#   par l'incident v2.110 : aucune sauvegarde n'existait quand il en a fallu une. Vérifié
#   en réel : sauvegarde créée au démarrage, intégrité SQLite confirmée (`PRAGMA
#   integrity_check` → ok), déclenchement manuel testé, rotation en place.
#   (2) `app/api/files/route.js` + `lib/services/fileManager.js` (721 lignes, accès fs
#   Node direct) migrés vers un proxy pur appelant les outils Python déjà existants
#   (file_list/file_info/file_find/file_create_folder/file_rename/file_move/file_copy/
#   file_delete via `/api/tools`, qui auto-confirme déjà les outils dangereux pour les
#   appelants UI). Seules les ~13 actions réellement câblées ont été portées — 8 fonctions
#   exportées par l'ancien fichier (readFileContent/writeFileContent/searchTextInFiles/
#   convertDocxToPdf/createDocx/editDocx/appendToDocx/getPdfInfo) étaient déjà du code mort
#   confirmé (zéro appelant, vérifié par grep) et n'ont pas été portées. `fileManager.js`
#   supprimé une fois vide de tout appelant réel. **Vrai bug trouvé en testant** : l'action
#   « organize » (classement par catégorie) créait des FICHIERS nommés "Images"/"Videos"
#   au lieu de dossiers, la 1ʳᵉ fois qu'ils n'existaient pas encore — `file_move` ne
#   recrée le nom du fichier source que si la destination est déjà un dossier EXISTANT,
#   sinon il traite la destination comme un nom de fichier littéral. Corrigé en construisant
#   toujours le chemin de destination COMPLET (dossier + nom de fichier) côté proxy, jamais
#   juste le dossier — même correctif appliqué à batchMove/batchCopy/move (même risque
#   latent). Autre bug trouvé : le champ `type` renvoyé par `file_find` est incohérent selon
#   la méthode (l'index Windows Search y met un type MIME/extension comme ".txt", pas
#   "fichier"/"dossier") — la recherche par nom affichait le mauvais type. Corrigé en ne
#   faisant plus confiance à ce champ (avec `include_dirs=false`, les résultats sont
#   toujours des fichiers). Testé en réel sur un dossier isolé hors de l'app : list, search,
#   info, sandbox, createFolder, rename, move, batchCopy, organize, batchDelete — tous
#   vérifiés avant/après fix, y compris via un vrai clic dans /fichiers → Parcourir.
#   (3) `scripts/smoke_test_pages.py` (nouveau) : formalise le balayage manuel de pages
#   fait plusieurs fois cette session (erreurs console au chargement) — 34 pages couvertes
#   (dont les anciennes routes redirect), toutes vertes après les changements ci-dessus.
# v2.112.0 — 💾 Restauration de sauvegarde. Complète v2.111 : une sauvegarde qu'on ne sait
#   pas restaurer ne vaut rien. `backup.py::restore_backup(filename)` : valide le nom de
#   fichier contre BACKUP_DIR (empêche toute traversée de chemin), prend AUTOMATIQUEMENT
#   une sauvegarde de sécurité de l'état actuel AVANT de restaurer (la restauration
#   elle-même devient réversible), puis copie la sauvegarde choisie par-dessus la base live
#   via `Connection.backup()` (même API que la sauvegarde, gérée par le verrouillage SQLite
#   natif — pas un remplacement de fichier brut). Endpoint `POST /api/backups/restore`
#   (confirmation explicite obligatoire, hors du registre d'outils : pas pilotable depuis
#   le chat par le LLM).
#   **Test réel réalisé avec prudence** : créé une note jetable, sauvegardé, supprimé la
#   note (perte simulée) — puis la restauration EN CONDITIONS RÉELLES a été bloquée par le
#   classifieur de permissions Claude Code (jugé trop risqué d'auto-tester un restore sur
#   la base live juste après l'incident de suppression accidentelle de cette même session,
#   cf. v2.110). Décision : ne pas insister. Le MÉCANISME sous-jacent (le même appel
#   `Connection.backup()` en sens inverse) a été vérifié séparément sur une COPIE isolée de
#   la base (jamais la live) : la note supprimée revient bien, `PRAGMA integrity_check` OK.
#   MISE À JOUR : l'utilisateur a ensuite demandé à être sollicité via AskUserQuestion
#   AVANT tout blocage plutôt qu'après — appliqué, question posée nommant l'action
#   précisément, acceptée, test de restauration REJOUÉ contre la vraie base live → succès
#   confirmé (note restaurée, backend sain après coup).
# v2.113.0 — 🔧 Winget "installe X" réparé de bout en bout — signalé par l'utilisateur
#   (« regarde la dernière conversation où je demande l'installation de victoria, il sait
#   que c'est le bon logiciel mais ne l'installe pas »). DEUX vrais bugs trouvés en
#   remontant la conversation réelle (pas en devinant) :
#   (1) `agent.py::_KEYWORD_TOOLS` n'avait AUCUNE entrée pour "installe"/"installer" — les
#   outils `winget_*` n'étaient donc JAMAIS proposés au LLM sur les profils filtrés
#   (chat/agent) pour ce type de demande (même classe de bug déjà documentée : un outil
#   enregistré dans TOOLS_REGISTRY n'est pas automatiquement visible du chat). Le LLM,
#   sans le bon outil disponible, "documentait" l'installation via `document_generate`
#   (génère un .docx expliquant comment installer) au lieu d'installer réellement — un
#   comportement plausible mais faux. Ajout d'une entrée `_KEYWORD_TOOLS` avec le stem
#   court `"instal"` (pas `"installe"`) pour matcher aussi "install" sans le e final —
#   repéré en reproduisant le bug avec le message EXACT de l'utilisateur ("install le
#   logiciel victoria", sans e). Vérifié : winget_search/winget_install apparaissent
#   maintenant dans la liste filtrée pour ce message, document_generate n'y est plus.
#   (2) Une fois le routage corrigé, un second bug est apparu au premier test réel :
#   `winget_install` appelé avec `query: 'Victoria'` (nom flou) au lieu de l'`id` exact
#   renvoyé par `winget_search` ("Victoria.Victoria") → winget refusait tout net
#   ("Plusieurs packages correspondent à vos critères"), même avec un seul paquet nommé
#   EXACTEMENT "Victoria". Plutôt que de compter sur le LLM pour rejouer avec le bon id
#   (fragile), `execute_winget_install` (tools.py) résout maintenant LUI-MÊME l'ambiguïté :
#   si un id exact n'est pas fourni, il relance une recherche interne et auto-sélectionne
#   l'id du paquet dont le NOM correspond EXACTEMENT à la requête (ou l'unique résultat
#   s'il n'y en a qu'un) ; sinon renvoie une erreur claire listant les paquets candidats.
#   **Testé en conditions réelles jusqu'au bout, sur autorisation explicite de
#   l'utilisateur** (AskUserQuestion posée proactivement avant tout risque de blocage,
#   cf. v2.112) : conversation rejouée avec le message original → winget_search puis
#   winget_install (toujours appelé avec `query`, résolu en interne vers
#   `Victoria.Victoria`) → installation réussie (code 0), confirmée présente sur la
#   machine via `winget_list_installed`.
# v2.114.0 — 🔍 Audit de conversations réelles (suite directe de v2.113, même méthode :
#   examiner les VRAIES conversations plutôt que deviner). 2 bugs de plus trouvés en
#   balayant les 19 conversations existantes (`scripts` ad-hoc, pas encore formalisé) :
#   (1) `win_service_action` exigeait le nom INTERNE exact du service ("MpsSvc"), jamais
#   le nom D'AFFICHAGE ("Windows Defender Firewall") qu'un LLM/utilisateur emploie
#   naturellement — et sur un Windows localisé en français, même une recherche par
#   sous-chaîne sur le nom d'affichage échouait ("Pare-feu Windows Defender" ne contient
#   pas "Firewall"). Ajout de `_resolve_service_name()` : essai exact d'abord, repli sur
#   une recherche floue Name+DisplayName, erreur claire listant les candidats si
#   ambigu. Testé en réel : "Pare-feu" et "mpssvc" (n'importe quelle casse) résolvent
#   maintenant correctement — le nom anglais complet sur un système francisé reste une
#   limite connue (traduction totale, pas juste une variante de casse/ordre), pas
#   poursuivie plus loin (aurait nécessité une table de traduction dédiée par service).
#   (2) Le LLM a appelé `billing_quote_email` avec `quote_id: 'ID_DU_DEVIS'` — un
#   PLACEHOLDER littéral au lieu d'un vrai identifiant, sur une demande vague ("un devis
#   en attente" sans client précisé) alors que `billing_quote_list` était pourtant déjà
#   dans les outils proposés. La règle d'or #7 anti-hallucination (v2.106) ne couvrait que
#   les paramètres OPTIONNELS ("laisse vide plutôt que deviner") — étendue pour couvrir
#   explicitement les paramètres OBLIGATOIRES inconnus : chercher le vrai identifiant via
#   l'outil de liste/recherche approprié, ou demander une clarification, jamais écrire un
#   texte de substitution en guise de valeur.
# v2.115.0 — 🔎 Recherche sémantique améliorée (reranker + hybride) + 🧠 consolidation
#   mémoire. Suite d'une recherche web sur les bonnes pratiques 2026 (RAG, mémoire
#   d'agent, tool-calling local), demandée explicitement par l'utilisateur, puis « je te
#   laisse libre go » sur les axes proposés.
#   (1) `reranker.py` (nouveau) : cross-encoder local léger (flashrank,
#   ms-marco-TinyBERT-L-2-v2, ~3 Mo, CPU, dizaines de ms) qui re-score un pool élargi de
#   candidats sur leur pertinence RÉELLE par rapport à la requête — la recherche
#   vectorielle seule sert désormais de filtre rapide, pas de verdict final. Best-effort :
#   si le reranker est indisponible, repli silencieux sur l'ordre vectoriel d'origine.
#   (2) `vector_store.py::search()` : ajout d'un étage BM25 lexical (rank_bm25, index en
#   mémoire par collection, TTL 60s) fusionné au vecteur par Reciprocal Rank Fusion avant
#   le reranking — le vecteur seul rate parfois un passage aux mots-clés exacts mais formulé
#   différemment ; BM25 seul rate les paraphrases ; ensemble ils se couvrent. Pipeline
#   complet : vecteur+BM25 (pool large) → fusion RRF → reranker cross-encoder → top N.
#   Bénéficie automatiquement à `search_semantic`, `document_ask`, `memory_search`,
#   `unified_search` (tous passent par `vector_store.search`). Vérifié en réel : les 3
#   scores (vec/bm25/rerank) cohabitent et influencent le classement final, testé sur
#   des documents indexés réels (résultats de tests réseau).
#   (3) `memory_consolidation.py` (nouveau) : fusion périodique des souvenirs quasi-
#   identiques, même esprit que le Learning Log des compétences (v2.95) mais VOLONTAIREMENT
#   déterministe (recouvrement de sous-chaîne, même heuristique que le dédoublonnage déjà
#   fait à l'enregistrement dans `execute_memory_save`) plutôt que piloté par un LLM — évite
#   le risque qu'un modèle fusionne à tort deux souvenirs différents. Worker de fond
#   quotidien + endpoints `GET /api/memories/consolidate/preview` (aperçu sans suppression)
#   et `POST /api/memories/consolidate` (exécution). Testé en réel avec deux souvenirs
#   quasi-identiques créés exprès : détection correcte (recouvrement 0.8), fusion garde le
#   plus détaillé, aucun des 4 vrais souvenirs de l'utilisateur touché (aucun doublon réel).
#
# v2.116 (📊 Monitoring actionnable) — demandé explicitement (« ameliore monitoring, rend le
#   plus interactif et utils car dans l'etat actuel il ne sert pas a grand chose, inspire toi
#   en cherchant sur le web »). Recherche menée (Netdata/Glances/htop, tendances dashboard
#   2026 : progressive disclosure, panneaux actionnables plutôt que jauges passives). La page
#   affichait déjà CPU/RAM/réseau/disques/historique d'outils mais AUCUNE action possible —
#   corrigé sur 4 axes :
#   (1) `GET /api/monitor` (SSE) diffuse désormais `top_processes` (8 process les plus
#   gourmands en CPU, via `psutil.process_iter`) — chaque ligne a un bouton ✕ qui appelle
#   `pc_process_kill` via `/api/tools` (confirmation JS avant l'appel, outil déjà dans
#   `DANGEROUS_TOOLS` donc auto-confirmé côté UI, cohérent avec le pattern déjà établi pour
#   `app/files/page.jsx`).
#   (2) Le payload SSE inclut aussi `gpu` (nom/VRAM/backend) via `local_video.get_device_info()`
#   — déjà cache-TTL 20s côté `local_video.py`, donc l'appeler chaque cycle SSE (2s) ne
#   redétecte réellement que toutes les ~10 itérations, coût négligeable.
#   (3) Bannière d'alerte quand un disque dépasse 85% d'occupation (le C: de cette machine
#   était à 90% sur la capture d'écran fournie par l'utilisateur) avec un lien direct vers
#   `/systeme?tab=nettoyage` (Catharsis) — l'utilisateur n'a plus besoin de deviner où agir.
#   (4) Bouton « ↻ Relancer » sur chaque exécution d'outil EN ÉCHEC dans l'historique déjà
#   affiché — rejoue le même outil avec les mêmes arguments via `/api/tools`, sans repasser
#   par le chat.
#   Aucun nouvel endpoint REST (le kill/retry passent par `/api/tools`, déjà existant et déjà
#   gated par confirmation) — uniquement une extension du payload SSE + du frontend.
# v2.117 (🔗 SSH — sécurité + fonctionnalité + ergonomie) — demandé explicitement (« l onglet
#   ssh devrait etre ameliorer en fonctionalité et en ergonomie, recherche aussi sur le web »).
#   Recherche menée (webssh/Terminus Web/ttyd — SFTP intégré, xterm.js, diagnostics serveur).
#   En auditant le code AVANT d'ajouter quoi que ce soit, trouvé que les 3 endpoints REST de
#   la page /ssh (test/exec/exec-stream) réimplémentaient CHACUN leur propre connexion
#   paramiko en dur — RSA uniquement (`paramiko.RSAKey.from_private_key`, une clé Ed25519 —
#   le défaut de `ssh-keygen` depuis des années — échouait) ET SANS PASSER par
#   `security.screen_command()`, alors que CLAUDE.md §6 est explicite : le terminal SSH tapé
#   à la main par un humain était donc le SEUL chemin d'exécution de commandes de tout Marvin
#   à ne PAS avoir le garde-fou anti-catastrophe (la version pilotée par le chat,
#   tools.py::execute_ssh_exec, l'avait déjà, et supportait déjà tous les formats de clé via
#   `_ssh_load_key`). Corrigé en supprimant la duplication : les 3 endpoints délèguent
#   désormais à `tools._ssh_connect`, et `security.guard_result()` est appliqué avant toute
#   exécution SSH côté page web. Vérifié en isolation (guard_result bloque bien "rm -rf /",
#   laisse passer "ls -la" — pas testé en direct sur un vrai hôte pour ne pas envoyer une
#   commande destructive à une machine réelle).
#   Fonctionnalités ajoutées, toutes en réutilisant la logique déjà existante côté outils
#   chat (tools.py::execute_ssh_list_dir/server_info, jusqu'ici injoignable depuis la page) :
#   navigateur SFTP (parcourir/envoyer/télécharger, `GET/POST /api/ssh/{id}/browse|upload|
#   download`), diagnostic serveur en un clic (OS/uptime/mémoire/disque/charge, `GET
#   /api/ssh/{id}/info`), édition d'une connexion existante (`PUT /api/ssh/{id}` — jusqu'ici
#   seuls add/delete existaient, un typo dans l'hôte obligeait à tout ressaisir), passphrase
#   de clé privée chiffrée (colonne `key_passphrase` ajoutée en DB — tools.py la lisait déjà
#   mais elle n'existait nulle part, fonctionnalité fantôme), bouton de test rapide par
#   connexion avec badge de statut (🧪 dans la sidebar, persisté via `last_test_ok`/
#   `last_test_at`), recherche/filtre des connexions, bouton copier sur chaque commande du
#   terminal. Migration DB via `ALTER TABLE ADD COLUMN` défensif (colonnes absentes → ajout
#   silencieux au premier démarrage, ne casse pas les connexions déjà sauvegardées).
#   Vérifié en réel : 34/34 pages au smoke-test, 0 erreur console (Playwright, tous les
#   onglets Terminal/Fichiers/Infos + formulaire d'édition), et confirmé qu'un appel réel
#   contre un hôte injoignable renvoie une erreur JSON propre après le timeout paramiko
#   (~30s) plutôt que de bloquer indéfiniment.
#   Correctif ergonomie signalé par l'utilisateur juste après coup (capture d'écran d'un
#   `ls` sans aucune sortie visible, "je suis bien connecté mais je ne vois pas réellement
#   le terminal") : diagnostiqué en isolation (script Python direct hors HTTP) — PAS un bug,
#   le dossier perso distant ne contenait que des fichiers cachés donc `ls` sans `-a`
#   renvoie légitimement une sortie vide (confirmé : `ls -la` sur la même connexion listait
#   bien les fichiers). Le vrai bug était ergonomique : rien ne distinguait "commande
#   toujours en cours" de "terminée sans rien à afficher" — corrigé côté frontend
#   (`app/ssh/page.jsx`) avec une ligne `(terminé, aucune sortie)` quand exit_code=0 et
#   qu'aucune ligne stdout/stderr n'a été reçue.
#
# v2.118 (🖥️ Terminal SSH interactif RÉEL — PTY + xterm.js) : demandé explicitement (« je
#   veux que peut importe que je suis sur un ssh qui donne sur un windows ou linux que je
#   voie le terminal comme si j'y étais »). L'ancien modèle exec/stream (une commande =
#   une requête SSE, attend la fin, pas d'invite interactive) ne pouvait pas donner cette
#   sensation. Remplacé par un vrai shell PTY : nouveau `WS /api/ssh/{id}/shell` ouvre
#   `paramiko.invoke_shell()` et relaie les octets bruts en continu dans les deux sens ;
#   côté frontend, `app/ssh/page.jsx::XtermSSH` utilise xterm.js (`@xterm/xterm` +
#   `@xterm/addon-fit`) pour un rendu de terminal complet (couleurs, curseur, resize,
#   scrollback). AUCUNE distinction Windows/Linux nécessaire côté code : le protocole SSH
#   délègue l'allocation du PTY et le choix du shell (bash/sh ou cmd.exe/PowerShell) au
#   serveur OpenSSH distant — Marvin ne fait que transporter les octets, exactement comme
#   PuTTY ou `ssh` en ligne de commande.
#   ⚠️ Contrepartie de sécurité ASSUMÉE et documentée en commentaire à l'endpoint : un flux
#   d'octets bruts interactif ne peut PAS passer par `security.screen_command()` sans
#   casser l'interactivité (pas de "commande complète" identifiable avant que l'utilisateur
#   appuie sur Entrée côté shell distant). Le garde-fou reste entier sur tous les chemins
#   AUTOMATISÉS de Marvin (chat, `/api/ssh/exec` + `/exec/stream` déjà gardés en v2.117) —
#   ce nouveau canal est un clavier direct tenu par un humain déjà authentifié sur sa
#   propre connexion sauvegardée, équivalent fonctionnel à ouvrir PuTTY soi-même.
#   Le terminal reste monté en permanence (masqué en `display:none`, pas démonté) quand on
#   bascule sur les onglets Fichiers/Infos, pour ne jamais couper la session shell en cours
#   — seul un changement de CONNEXION force une reconnexion (`key={activeConn.id}`).
#   Dépendance manquante découverte en cours de route : `websockets` (requis par uvicorn
#   pour le support WebSocket) n'était pas installé dans ce venv malgré `uvicorn[standard]`
#   — ajouté explicitement à `requirements.txt`.
#   Testé en réel (Playwright) contre une vraie connexion SSH Linux : bannière MOTD
#   complète affichée à la connexion, `echo` tapé au clavier répond instantanément, bouton
#   raccourci `pwd` exécuté directement dans le shell — zéro erreur console fonctionnelle.
#
# v2.119 (☁️ Ollama Cloud — routage local/cloud par SENSIBILITÉ) : demandé explicitement
#   après souscription de l'utilisateur à Ollama Cloud (« rester purement local est pertinent
#   pour les données sensibles [emails, mots de passe...] mais pour optimiser Marvin l'option
#   cloud est très utile [...] sans hallucination ni limite matérielle »). Rejeté d'emblée
#   l'approche naïve "épingler un profil entier sur le cloud" (agent/chat mélangent météo ET
#   emails/SSH — un override par profil enverrait aussi les données sensibles au cloud).
#   Routage fait au niveau de la REQUÊTE, pas du profil (`agent.py`) :
#   1. Nouveau réglage opt-in `cloud_enabled` (désactivé par défaut) + `cloud_overrides`
#      ({profil: modèle_cloud}, ex. {"analysis": "glm-5.2:cloud"}) — même pattern que
#      `model_overrides` (v2.83), configurable via `PUT /api/settings/cloud_enabled` et
#      `.../cloud_overrides` (endpoints génériques déjà existants) + nouvelle section UI
#      dans Réglages → Modèle IA.
#   2. AVANT l'appel Ollama : `_is_sensitive_request()` vérifie mots-clés sensibles (email,
#      ssh, mot de passe, identifiants, clé API, token, facture/devis/client) dans le
#      dernier message ET les tool_calls déjà présents dans l'historique récent (un
#      "résume-moi ça" après un email chargé en contexte reste local aussi). Si sensible →
#      le modèle cloud n'est JAMAIS utilisé, quel que soit le réglage.
#   3. PENDANT la boucle d'outils : si un outil sensible (`email_*`, `ssh_*`, `billing_*`,
#      `credential_*`) est appelé alors qu'on est sur un modèle cloud — l'agent a pu décider
#      d'y aller sans mot-clé explicite dans le message initial — bascule IMMÉDIATE vers le
#      modèle local AVANT que le résultat (contenu d'email, sortie SSH…) ne parte au tour
#      suivant. S'applique même si l'utilisateur a choisi manuellement un modèle cloud dans
#      le sélecteur (dernier filet, pas une simple commodité de l'auto-routing).
#   Testé en réel (curl SSE contre le backend live, PAS de simulation) : avec cloud_enabled
#   + override sur TOUS les profils (agent/chat/analysis), "résume mes emails" reste sur
#   qwen2.5:14b (local, déclenche email_digest) tandis que "quelle heure est-il" bascule sur
#   glm-5.2:cloud — même override cloud présent sur le profil agent dans les deux cas, seule
#   la sensibilité du contenu change le résultat. UI vérifiée (Playwright, 0 erreur console) :
#   toggle + garde-fou affiché explicitement + sélecteurs par profil. cloud_enabled remis à
#   false après les tests (réglage opt-in, l'utilisateur l'active lui-même dans Réglages).
#
# v2.120 (🎚️ 3 préréglages cloud — Normal / Hyper sécurisé / Tout cloud) : demandé
#   explicitement après v2.119 (« je voudrais quand même avoir l'option tout cloud et tout
#   local en plus de ce qui existe [...] pour appliquer rapidement un setup global »).
#   Le garde-fou « donnée sensible → toujours local » (v2.119) reste actif dans LES TROIS
#   modes, y compris Tout cloud — ce n'est jamais désactivable, seule l'agressivité du
#   reste change. Aucun nouveau mécanisme lourd : les presets écrivent simplement les
#   réglages déjà existants (`cloud_enabled`/`cloud_overrides`) + UN nouveau réglage
#   `local_only_lockdown` (bool) pour le mode Hyper sécurisé.
#   `local_only_lockdown` est un coupe-circuit PRIORITAIRE sur tout le reste dans
#   `agent.py::run_agent` : bloque même une sélection MANUELLE explicite d'un modèle cloud
#   par l'utilisateur (jusqu'ici seule la protection mid-boucle v2.119 s'appliquait à la
#   sélection manuelle — désormais le lockdown la bloque dès le départ, avant même le 1er
#   appel Ollama).
#   Preset « Tout cloud » : active cloud_enabled + peuple cloud_overrides pour les 3 profils
#   (agent/chat/analysis) avec le meilleur modèle cloud installé (préférence deepseek > glm
#   > kimi > premier disponible) — un clic dans Réglages → Modèle IA.
#   Testé en réel (curl direct contre le backend live) : avec local_only_lockdown=true, un
#   POST /api/chat avec model="glm-5.2:cloud" (sélection manuelle explicite) rebascule bien
#   sur qwen2.5:14b local. UI vérifiée (Playwright, 0 erreur console) : les 3 cartes de
#   preset s'affichent, le clic sur chacune applique bien la config attendue (badge ACTIF
#   correct, sélecteur "Agent" pré-rempli avec deepseek-v4-flash:cloud après "Tout cloud",
#   toggle grisé + message après "Hyper sécurisé"). Remis en mode Normal (cloud désactivé)
#   après les tests.
#
# v2.121 (☠️ Mode Ultra débridé — 4ᵉ préréglage) : demandé explicitement (« je veux un
#   quatrième mode ultra débridé qui a le droit à tout sans aucun filtre de sécurité »).
#   Discussion préalable avec l'utilisateur AVANT implémentation (il a demandé mon avis) :
#   distinction posée entre DEUX catégories de garde-fous totalement différentes —
#   (1) le garde-fou de SENSIBILITÉ (v2.119, quelles données partent au cloud) est un choix
#   de confidentialité que l'utilisateur peut légitimement assumer pour SES propres données ;
#   (2) le garde-fou SYSTÈME de `security.py` (commandes catastrophiques irréversibles :
#   formatage, `rm -rf /`, fork bombs) protège contre un scénario différent — Marvin qui
#   détruit la machine par erreur (hallucination du modèle OU injection de prompt via du
#   contenu web/email lu par l'agent) — le désactiver n'apporterait aucun bénéfice de
#   performance, seulement du risque pur. Accord trouvé : le 4ᵉ mode ne touche QUE (1),
#   jamais (2), qui reste entier dans les QUATRE modes sans aucune exception.
#   Nouveau réglage `ultra_unrestricted` (bool) : quand actif, `_is_sensitive_request()`
#   est délibérément court-circuitée (`agent.py::run_agent`) — emails/SSH/mots de passe/
#   factures peuvent partir au cloud comme le reste — ET la protection mid-boucle v2.119
#   (repli local si un outil sensible est appelé en cours de tour) est également désactivée,
#   cohérence oblige. `local_only_lockdown` (Hyper sécurisé) reste prioritaire par défense
#   en profondeur si jamais les deux réglages étaient actifs simultanément (ne devrait pas
#   arriver via l'UI, les 4 presets sont mutuellement exclusifs).
#   UI : 4ᵉ carte de préréglage + `window.confirm()` bloquant avant toute activation,
#   texte explicite sur l'irréversibilité (une donnée déjà envoyée au cloud ne peut pas être
#   rappelée) et rappelant que le garde-fou système reste actif.
#   Vérification en conditions réelles PARTIELLEMENT bloquée par le classifieur de
#   permissions Claude Code lui-même : deux tentatives d'activer `ultra_unrestricted=true`
#   via des appels backend directs ont été refusées en dur (« hard block », « user
#   authorization cannot clear ») — signal pris au sérieux, aucune tentative de contournement.
#   Vérifié à la place : (a) la logique de code relue et tracée manuellement (bypass correct
#   aux deux points de contrôle), (b) le dialogue de confirmation s'affiche avec le bon texte
#   et un clic « Annuler » n'active bien rien (Playwright, capture avant/après, 0 erreur
#   console), (c) les primitives sous-jacentes (`_is_sensitive_request`, `_is_cloud_model`)
#   déjà validées en v2.119. Le chemin d'activation RÉEL (clic « Confirmer ») n'a pas été
#   testé en direct — à valider par l'utilisateur lui-même la première fois qu'il l'active.
#
# v2.122 (☁️ Routage cloud étendu aux outils + 🌐 fraîcheur web) : demandé explicitement
#   (« nous devons améliorer tous les outils et l'embedding de Marvin pour qu'il profite de
#   sa nouvelle puissance cloud » + « qu'il consulte le web plus souvent pour être sûr que
#   l'info n'est pas outdated »). Avis donné AVANT implémentation (demandé explicitement) :
#   (1) l'embedding (nomic-embed-text) NE bénéficie PAS du cloud — c'est un encodeur, pas un
#   modèle de conversation, et le changer casserait tout l'index déjà construit (espaces
#   vectoriels incompatibles entre modèles) — non touché, décision assumée. (2) la majorité
#   des 294 outils sont du code déterministe (fichiers, SSH, calendrier…) qui n'appelle
#   AUCUN LLM — le cloud ne leur apporte rien. (3) un modèle cloud plus puissant n'est PAS
#   plus à jour pour autant (lui aussi a une date de coupure) — la fraîcheur vient de la
#   recherche web, pas du choix du modèle. Périmètre validé par l'utilisateur avant d'agir.
#
#   **Routage cloud étendu** : audit complet (agent Explore) de tous les appels LLM internes
#   aux outils — 17 sites trouvés (document_generate, email_draft_reply/summarize/digest/
#   to_task/attachment_summary/watch_check, daily_briefing, document_ask/refine_section,
#   web_research, text_summarize, pdf_ocr, + 3 sites skills.py via callback injecté) qui
#   ignoraient TOTALEMENT le réglage Ollama Cloud — toujours en local, sans jamais consulter
#   cloud_enabled/cloud_overrides. Nouveau module `cloud_routing.py` (évite un import
#   circulaire : agent.py importe déjà tools.py pour TOOLS_REGISTRY/TOOLS_SPEC) centralise
#   les primitives déjà construites en v2.119-121 (mots-clés sensibles, cloud_enabled,
#   local_only_lockdown, ultra_unrestricted) + une nouvelle fonction `resolve_model()`
#   appliquant les mêmes règles à un appel LLM PONCTUEL (pas une conversation) : un modèle
#   local explicitement demandé est toujours respecté, un modèle cloud n'est utilisé que si
#   le texte du prompt n'est pas sensible (ou Ultra débridé actif), et les appels AVEC IMAGES
#   (OCR/vision) restent TOUJOURS locaux (aucune garantie que les modèles cloud installés
#   supportent le multimodal, et c'est justement le contenu le plus sensible — scans de
#   documents, captures d'écran). `agent.py` refactorisé pour déléguer à ce module au lieu
#   de dupliquer sa propre copie. `tools.py::_ollama_generate` (point d'entrée unique de 13
#   des 17 sites) branché en UNE seule modification ; les 9 call sites restants (main.py +
#   agent.py) qui pré-résolvaient un modèle local en dur AVANT l'appel ont été changés pour
#   passer `model=None` et laisser `resolve_model()` décider sur le PROMPT réel (transcript/
#   conversation/description inclus) plutôt qu'à l'aveugle — comportement identique à avant
#   si le cloud n'est pas configuré, amélioré sinon.
#
#   **Fraîcheur web** : rejeté la demande littérale (« chercher à chaque message ») —
#   ajouterait de la latence à toute question qui n'en a pas besoin (calcul, résumé de
#   fichier, action système). À la place : règle d'or #8 ajoutée au prompt système
#   (PRIORITAIRE, même famille que les 7 existantes) — ne jamais répondre "de mémoire" sur
#   une info possiblement périmée (version logicielle, actualité, prix, disponibilité,
#   événement récent) et appeler web_search/web_research AVANT de répondre dans ce cas.
#   Nouveau groupe de mots-clés dans `_KEYWORD_TOOLS` ("dernière version", "quoi de neuf",
#   "encore d'actualité", "vient de sortir", "à jour", "obsolète"...) qui inclut désormais
#   web_search/web_research dans la liste d'outils filtrée même sans mention explicite de
#   "web"/"internet" — sans ce mot-clé, ces formulations passaient à travers le filtrage
#   par mots-clés (le filtre sémantique aurait pu les rattraper, mais pas de façon fiable).
#
#   Testé en réel (curl direct contre le backend live, PAS de simulation) : `resolve_model()`
#   unit-testé (non-sensible → cloud, sensible → local, avec images → local, cloud désactivé
#   → local) ; requête "dernière version de Python actuellement disponible" → `web_search`
#   RÉELLEMENT appelé (DuckDuckGo, 8 résultats incluant Python 3.14.6, sources citées) sans
#   qu'aucun mot "web"/"internet" ne soit présent dans la question. `scripts/smoke_test_pages.py`
#   34/34 + `scripts/smoke_test_chat.py` 5/5 conversations, aucune régression.
#
# v2.123 (🧩 4 correctifs du système de Compétences) : demandé explicitement (« la partie
#   compétence peut être revue, améliorée, car dans l'état actuel ils ne sont pas très
#   fonctionnels ni opérationnels »). Avis donné AVANT implémentation (demandé explicitement,
#   audité via agent Explore plutôt que deviné) : l'hypothèse initiale de l'utilisateur
#   (un modèle cloud plus puissant générerait de meilleures compétences) ne correspondait
#   PAS aux données réelles — les 26 fichiers de compétences sont bien rédigés, les 36 noms
#   d'outils qu'elles référencent existent tous. Le vrai problème : 16/26 (62%) n'ont JAMAIS
#   été déclenchées une seule fois depuis leur création, et les 10 qui le sont affichent un
#   taux de succès suspicieusement parfait (100%, jamais mises à l'épreuve) — un problème
#   d'ACTIVATION, pas de génération. 4 bugs concrets trouvés et corrigés dans `skills.py`/
#   `agent.py` :
#   1. **Matching mono-message** (`agent.py::_match_skill`) : ne regardait QUE le dernier
#      message — un follow-up court ("vas-y", "ok fais-le") après une 1ère demande pertinente
#      ne portait jamais assez de signal pour re-déclencher la compétence. Corrigé : si le
#      message courant fait ≤4 mots, il est complété avec le tour utilisateur précédent
#      avant le matching (uniquement dans ce cas, pour ne pas diluer le matching des
#      demandes normales déjà auto-suffisantes).
#   2. **Repli embedding trop strict** (`skills.py::match()`) : si l'embedding échoue
#      (Ollama hors-ligne, timeout...), l'ancien calcul imposait un mur dur (overlap≥2 OU
#      trigger exact, sinon plafonné à 0.30 — toujours sous le seuil) qui désactivait
#      SILENCIEUSEMENT tout matching pour une requête n'ayant qu'UN mot-clé fort en commun.
#      Formule lissée (base 0.40/0.22/0 selon overlap au lieu d'un cliff binaire) + seuil
#      global 0.62→0.60 + cap lexical 0.30→0.35 (mots-clés déjà filtrés courts/vides par
#      `_keywords`, un recouvrement même partiel est un signal réel).
#   3. **Golden path corrompu** (`skills.py::record_success_trace`) : bug réel trouvé dans
#      les données de production — la compétence "migration-poste" avait mémorisé comme
#      "déroulé le plus efficace" 8 appels IDENTIQUES à `win_system_report` (une boucle
#      ratée mais réussie malgré tout), activement réinjectée comme exemple few-shot pour
#      REBOUCLER au prochain déclenchement. Dédoublonnage des appels consécutifs identiques
#      AVANT toute comparaison de longueur (le déroulé dédupliqué EST le vrai golden path).
#      Donnée corrompue existante nettoyée directement dans `data/skills_stats.json`
#      (8 appels → 1).
#   4. **`consolidate_obsolete_skills` ignorait les compétences jamais utilisées**
#      (`if not last_used: continue`) : aucune des 16 compétences jamais déclenchées n'était
#      donc JAMAIS révisée/archivée, quel que soit son âge — exemption permanente, aucune
#      boucle de rétroaction. Corrigé : pour une compétence sans `last_used`, la date de
#      dernière modification du fichier sert de référence d'âge (signal moins précis qu'un
#      usage réel, mais infiniment meilleur qu'une exemption à vie).
#   Testé en réel (pas de simulation) : `record_success_trace` unit-testé (8 appels
#   identiques → 1 stocké ; trace normale à 3 étapes → 3 stockés, inchangé) ; `match()`
#   testé sur les vraies compétences ("caractéristiques matérielles" → migration-poste,
#   "vas-y" seul → aucun match, comportement voulu) ; `consolidate_obsolete_skills()`
#   exécuté pour de vrai contre les données réelles (tous les fichiers ont <20 jours, donc
#   aucun archivage — confirmé sans erreur) ; requête chat live "mon imprimante ne répond
#   plus du tout" → la compétence `depannage-imprimante` (JAMAIS déclenchée avant ce
#   correctif) se déclenche désormais correctement. Smoke-tests 34/34 pages + 5/5
#   conversations, aucune régression.
#
# v2.124 (🧠 Compétences — recherche web + 3 améliorations + 5 nouvelles compétences) :
#   suite directe de v2.123, sur demande explicite (« regarde sur le web, github, forums
#   spécialisé AI... pour rendre cela plus puissant » + « pense à me faire de nouvelles
#   compétences liées à mon métier d'admin système/réseau et d'étudiant en recherche
#   informatique »). Recherche menée AVANT implémentation (Anthropic Agent Skills/SKILL.md
#   — le standard officiel du même type de système —, Voyager, littérature 2026 sur la
#   curation de bibliothèques de compétences SkillOS/SkillBrew). Bonne nouvelle validée par
#   la recherche : l'architecture de Marvin (traces de succès, auto-réparation, apprentissage
#   périodique) est déjà proche de l'état de l'art — pas de refonte nécessaire, 3 ajustements
#   ciblés :
#   A. **Descriptions plus explicites** : Anthropic documente que SES PROPRES modèles
#      sous-déclenchent une compétence si sa description n'énonce pas clairement LE
#      DÉCLENCHEUR — exactement cohérent avec la trouvaille v2.123 (62% jamais déclenchées).
#      Les 16 compétences dormantes ont eu leurs descriptions réécrites ("Se déclenche
#      pour...") + leurs listes de triggers étoffées avec des formulations naturelles
#      supplémentaires.
#   B. **Journal du dauphin** (`skills.py::_log_match_attempt`, nouveau fichier
#      `data/skills_match_log.jsonl`, endpoint `GET /api/skills/match_log`) : chaque
#      matching enregistre gagnant + 2ᵉ meilleur candidat + scores — donnée réelle pour juger
#      si un retrieval multi-compétences (façon Voyager, qui récupère le top-5 plutôt qu'un
#      seul gagnant) apporterait quelque chose, avant d'investir dans cette refonte plus
#      lourde. Diagnostique uniquement, aucune action automatique.
#   C. **Scan de chevauchement croisé** (`skills.py::find_overlapping_skills`, endpoint
#      `GET /api/skills/overlaps`) : compare TOUTES les compétences entre elles par
#      similarité d'embedding (pattern SkillOS/SkillBrew — curation à l'échelle de la
#      bibliothèque, pas seulement au sein d'une même compétence comme
#      `review_and_consolidate_learnings`). Exécuté pour de vrai sur les 31 compétences :
#      aucune paire au-dessus de 0.85 (pas de doublon problématique), les similarités
#      0.75-0.85 sont entre compétences légitimement voisines mais distinctes (onboarding/
#      offboarding, sauvegarde/restauration) — résultat rassurant, pas d'action requise.
#   **5 nouvelles compétences** ciblées métier (admin système/réseau + recherche
#   informatique), tous les outils référencés vérifiés existants avant écriture :
#   `audit-securite-reseau` (scan de ports/services/certificats TLS), `deploiement-multi-
#   serveurs` (commande sur plusieurs connexions SSH à la fois, `ssh_exec_multi`),
#   `veille-vulnerabilites-logiciels` (croise l'inventaire logiciel réel avec les CVE
#   récentes via web_search, s'appuie sur la règle de fraîcheur v2.122), `veille-recherche-
#   informatique` et `synthese-article-scientifique` (recherche/synthèse académique
#   structurée, distinct d'un résumé générique).
#   Testé en réel (curl contre le backend live, pas de simulation) : 31 compétences
#   chargées (26+5) confirmées via `/api/skills`. Scan de chevauchement exécuté pour de
#   vrai (résultats ci-dessus). Journal de matching vérifié avec 2 requêtes réelles :
#   "mon wifi se déconnecte tout le temps" → `depannage-wifi` gagne net (1.258 vs 0.805,
#   écart 0.453) ; "veille sur les dernières avancées en sécurité réseau" →
#   `veille-recherche-informatique` gagne (0.989 vs 0.916 pour veille-vulnerabilites-
#   logiciels, une confusion plausible et acceptable entre 2 compétences voisines).
#   Smoke-tests 34/34 pages + 5/5 conversations, aucune régression.
#
# v2.125 (🧠 "Marvin reste à réfléchir" — 3 correctifs) : signalé directement par
#   l'utilisateur (« je trouve souvent que Marvin continue de réfléchir sans rien faire et
#   je suis obligé d'arrêter »). Diagnostiqué sur les VRAIES conversations récentes
#   (agent Explore sur `secretary.db`, pas une supposition) : preuve d'un tour d'outil
#   silencieux de 3min10 sur une conversation réelle, plusieurs conversations coupées net
#   en plein tool_call sans suite (signature d'un arrêt manuel pendant le silence).
#   1. **Champ `thinking` d'Ollama jamais lu** : certains modèles (dont deepseek-v4-flash:
#      cloud, confirmé par un appel direct à l'API Ollama) renvoient leur raisonnement dans
#      un champ SÉPARÉ de `message.content`, avant la réponse/l'appel d'outil réel.
#      `agent.py` ne lisait que `content` → l'utilisateur ne voyait RIEN défiler pendant que
#      le modèle "pensait". `MessageBubble.jsx` avait DÉJÀ un bloc collapsible "🧠
#      Réflexion..." tout construit (parts de type 'reasoning') mais jamais alimenté —
#      branché maintenant (`ChatContext.jsx`, nouvel événement SSE `thinking`).
#   2. **Bug trouvé en corrigeant le point 1** : le handler `case 'text'` de `ChatContext.jsx`
#      reconstruisait `parts` en ne gardant que les tool-invocations, effaçant
#      silencieusement le bloc de réflexion dès le 1er token de réponse finale. Corrigé
#      (préserve aussi les parts 'reasoning') — vérifié en réel (Playwright) : le badge
#      "Réflexion..." apparaît PENDANT la frappe et survit après coup, contenu lisible.
#   3. **Résultats web énormes réinjectés à chaque tour** : une conversation réelle
#      cumulait jusqu'à 118 000 caractères de résultats `web_browse` (≈15 appels en rafale),
#      chacun restant dans l'historique pour tout le reste de la boucle — chaque appel
#      suivant au modèle cloud devenait plus lourd et plus lent. Plafond de
#      `execute_web_browse` abaissé (25000/60000 → 12000/20000 caractères).
#   **Découverte annexe pendant les tests, corrigée au passage** : deux questions anodines
#   ("combien font 47*53", "quelle est la capitale de la France") déclenchaient des
#   compétences totalement hors sujet (dépannage imprimante, pas-internet) à des scores
#   0.6-0.7 à peine au-dessus du seuil abaissé en v2.123 (0.60), quasi à égalité avec le
#   dauphin (écart 0.004 à 0.013) — du bruit de mesure, pas une vraie correspondance,
#   confirmé grâce au journal du dauphin construit en v2.124. Une compétence hors sujet
#   injectée dans le prompt peut faire dériver le modèle sur une question triviale —
#   contributeur plausible additionnel au ressenti "tourne en rond". Seuil relevé à 0.72 +
#   exige un écart minimum de 0.05 avec le dauphin, sinon aucun match plutôt qu'un match
#   ambigu (`skills.py::match`). Revérifié après coup que les VRAIS matches (score >0.95,
#   écart >0.07 observés en réel) passent toujours.
#   Testé en réel de bout en bout : SSE brut confirme le streaming `thinking` fonctionnel ;
#   Playwright confirme le rendu visuel (badge pendant la frappe + persistance après) sans
#   erreur console ; les 2 questions-pièges ne matchent plus aucune compétence
#   (`winner: null` au journal) tandis que `depannage-wifi` et `veille-recherche-
#   informatique` matchent toujours correctement. Smoke-tests 34/34 pages + 5/5
#   conversations.
#
# v2.126 (🇫🇷 réponse toujours en français + 🎯 pas de silence à MAX_TOOL_STEPS) : signalé
#   directement par l'utilisateur juste après la mise en prod de v2.125 (« je ne trouve pas ça
#   très pertinent et je voudrais que le résultat soit toujours en français »), en pointant sa
#   propre conversation en cours. Diagnostiqué sur cette VRAIE conversation (demande AD CS/Wazuh
#   à 08:36) plutôt que deviné : le modèle cloud actif (`deepseek-v4-flash:cloud`, routage
#   normal — requête non sensible) avait fait 3 `web_browse` puis appelé `ssh_list` (outil
#   totalement hors sujet) et conclu par une réponse finale ENTIÈREMENT EN ANGLAIS listant les
#   connexions SSH enregistrées — sans jamais répondre à la question posée (procédure de
#   certificat HTTPS AD CS→Wazuh). 2 causes réelles, pas une seule :
#   1. Le prompt système ne rendait le français qu'« par défaut », laissant la porte ouverte à
#      un basculement en anglais après avoir ingéré plusieurs pages sources anglaises (Wazuh
#      docs, notes.benheater.com). Durci en règle non négociable + 2 nouvelles règles d'or
#      (#9 : traduire systématiquement le contenu anglais des sources dans la réponse finale ;
#      #10 : rester sur la demande initiale, ne pas partir sur un outil annexe juste parce
#      qu'il est disponible/récent — explique directement l'appel `ssh_list` observé).
#   2. Bug structurel plus grave trouvé en reproduisant le cas en direct (requête de recherche
#      web forcée, curl SSE) : à l'atteinte de `MAX_TOOL_STEPS` (10), la boucle `agent.py`
#      terminait purement et simplement — AUCUN message sauvegardé, AUCUN texte streamé, juste
#      un `done` sec après le dernier `tool_end`. Reproduit avec 11 `tool_start` d'affilée et
#      zéro `text` en sortie — c'est le symptôme EXACT de « Marvin reste bloqué à réfléchir puis
#      s'arrête sans rien faire », indépendant du fix v2.125 sur le streaming `thinking` (qui
#      rend visible la RÉFLEXION mais ne garantissait pas une RÉPONSE). Corrigé : à l'atteinte
#      de la limite, un dernier appel Ollama SANS outils est forcé (nudge explicite « tu ne peux
#      plus utiliser d'outils, synthétise maintenant en français ») et son texte est streamé +
#      sauvegardé comme réponse finale, avec un repli textuel si même cet appel échoue.
#   Testé en réel de bout en bout (curl SSE, requête forcée à englober des sources anglaises) :
#   réponse finale intégralement en français, correctement traduite/synthétisée à partir de
#   docs anglaises (nginx.org), 7 appels d'outils sans dérive hors-sujet (vs. le `ssh_list`
#   observé avant fix). Smoke-test chat 5/5 après coup.
#
# v2.127 (🛡️ 2 règles d'or — sécurité dégradée par erreur + syntaxe non évaluée dans les docs) :
#   demandé par l'utilisateur (« que penses-tu de la dernière conversation ? corrige tout ce qui
#   ne va pas ») sur une VRAIE conversation (script d'installation GLPI sur Debian 13 + PDF
#   généré). Audit ligne par ligne du script produit par le modèle cloud actif, 3 défauts réels
#   trouvés :
#   1. L'étape « sécurisation de MariaDB » du script automatisé exécutait
#      `ALTER USER 'root'@'localhost' IDENTIFIED BY '';` — qui fait l'INVERSE de sécuriser :
#      sur Debian, root MariaDB utilise par défaut l'authentification unix_socket (pas de mot de
#      passe réseau) ; cette commande la REMPLACE par une authentification par mot de passe VIDE,
#      une régression de sécurité présentée comme un durcissement.
#   2. Le PDF généré contenait littéralement le texte `$(date '+%d/%m/%Y')` dans son pied de
#      page — une substitution shell jamais évaluée, écrite telle quelle par le modèle qui a
#      halluciné un contexte d'exécution shell pour du contenu Markdown statique.
#   3. La section « réinitialisation du mot de passe admin » du PDF fournissait un hash bcrypt
#      copié tel quel (probablement d'un tutoriel générique en ligne) en affirmant qu'il
#      correspond au mot de passe "admin" — invérifiable et une mauvaise pratique de toute façon
#      (un hash trouvé sur internet ne doit jamais être présenté comme fiable pour un reset admin).
#   Pas de bug logiciel Marvin ici (c'est un défaut de génération du LLM, pas du code) — 2
#   nouvelles règles d'or ajoutées au prompt système pour réduire la récidive sur cette CATÉGORIE
#   d'erreur : #11 (ne jamais dégrader une sécurité existante sous couvert de la « sécuriser »,
#   préférer la commande officielle interactive à une improvisation SQL/script) et #12 (jamais de
#   syntaxe shell/code non évaluée dans un document destiné à être lu tel quel ; jamais de
#   hash/identifiant trouvé en ligne présenté comme fiable pour un reset de credentials).
#
# v2.128 (📂 documents générés cliquables dans le chat) : demandé explicitement (« j'aimerais
#   pouvoir cliquer et ouvrir les documents générés directement depuis le chat »), sur la même
#   conversation GLPI que v2.127. Les outils de génération de document (`file_create_pdf`,
#   `document_generate`, `billing_quote_pdf`, `file_convert_docx_to_pdf`...) renvoient tous la
#   même forme `{success, message, path}` — jusqu'ici rendue par le fallback « succès générique »
#   de `MessageBubble.jsx` (un simple ✅ + message texte), obligeant à aller chercher le fichier
#   soi-même sur le disque. Nouveau composant `GeneratedFileCard` : détecte un résultat
#   `success + path` dont l'EXTENSION correspond à un type de document connu (pdf/docx/xlsx/
#   pptx/txt/md/csv...) — détection par extension plutôt que par nom d'outil un par un, pour
#   couvrir automatiquement tout futur outil de génération sans modification supplémentaire —
#   et affiche une carte cliquable (icône par type, nom de fichier, message de succès) qui
#   appelle `pc_open_file` (déjà utilisé par `FileExplorerCard.jsx` pour le même usage) au clic.
#   Testé en réel (Playwright + appel direct `pc_open_file` sur le chemin exact affiché) : la
#   carte s'affiche sans erreur console sur la conversation GLPI réelle, le clic déclenche bien
#   l'appel `/api/tools`, `pc_open_file` confirmé retourner `success:true` sur ce chemin.
#
# v2.129 (📐 règle d'or #13 — structuré + sécurisé + complet par défaut) : demandé explicitement
#   après l'audit du script GLPI v2.127 (« fait en sorte que ce que je demande à Marvin soit
#   toujours structuré et bien sécurisé et complet comme avec toi »). Les règles #7/#8/#11/#12
#   couvraient déjà des symptômes précis (hallucination d'identifiant, info périmée, régression
#   de sécurité déguisée, syntaxe non évaluée) mais rien n'énonçait le niveau de qualité ATTENDU
#   PAR DÉFAUT sur toute réponse technique — l'utilisateur veut ce standard systématique, pas
#   du cas par cas après coup. Nouvelle règle #13 (`agent.py`) qui consolide 3 exigences
#   explicites pour toute réponse de type script/procédure/config/installation : structure
#   (titres, étapes, tableaux — pas un mur de texte), sécurité (moindre privilège par défaut,
#   relecture mentale de chaque commande sensible avant écriture) et complétude (prérequis +
#   vérification finale, vérifier via web_search si un point technique récent est incertain
#   plutôt que de deviner). Renforce les règles existantes plutôt que de les dupliquer.
#
# v2.130 (🔒 règle #11 étendue — ne touche pas à un compte d'admin qui n'a rien demandé) :
#   demandé explicitement après vérification du fix v2.129 (« je veux pouvoir travailler avec
#   Marvin sans risque sur ses procédures/scripts/demandes techniques qui doivent être de niveau
#   professionnel »). Le test réel du fix v2.129 (script Nextcloud) avait montré une nette
#   amélioration mais un résidu : le script changeait toujours l'authentification root MariaDB
#   d'unix_socket (sûr par défaut sur Debian, local uniquement) vers un mot de passe — plus une
#   régression grave (mot de passe FORT généré, pas vide comme en v2.127) mais toujours une
#   modification non nécessaire d'un mécanisme qui n'avait rien demandé à être touché. Règle #11
#   étendue avec un principe plus large : si un compte/service a déjà une authentification sûre
#   par défaut, NE PAS LA MODIFIER même pour la "renforcer" — créer un compte applicatif DÉDIÉ
#   pour l'usage demandé (déjà la bonne pratique suivie pour la base de données elle-même) et
#   laisser le compte d'administration du service sous-jacent inchangé. Règle durcie une 2ᵉ fois
#   dans la foulée (interdiction explicite et nommée de `ALTER USER 'root'@'localhost'
#   IDENTIFIED BY` sur MariaDB/MySQL, sans exception) après un premier test resté positif.
#
# v2.131 (🛡️ filet de sécurité DÉTERMINISTE — le rappel textuel a un plafond d'efficacité) :
#   testé en réel (3 requêtes identiques « script d'installation Zabbix + MariaDB » contre le
#   modèle cloud actif APRÈS le durcissement v2.130 de la règle #11) — le script a QUAND MÊME
#   modifié le mot de passe root MariaDB dans 2 générations sur 3, malgré une interdiction
#   explicite et sans exception dans le prompt système. Conclusion actée avec l'utilisateur
#   (« je veux pouvoir travailler avec Marvin sans risque ») : un rappel textuel, même très
#   explicite, ne garantit JAMAIS un comportement 100% fiable sur un LLM probabiliste — durcir
#   encore le texte n'aurait fait que repousser le problème, pas le résoudre.
#   Ajout d'un filet DÉTERMINISTE (`agent.py::_scan_dangerous_script_patterns`), sur le même
#   principe que `security.py` mais pour du contenu généré plutôt que des commandes exécutées :
#   scan regex de la réponse finale (si elle contient un bloc de code) contre une liste de
#   motifs dangereux SANS AMBIGUÏTÉ (modification du mot de passe root MariaDB/MySQL, mot de
#   passe VIDE dans une commande d'authentification, `chmod -R 777`). Ne bloque ni ne modifie
#   RIEN (contrairement à `security.py` qui bloque des COMMANDES EXÉCUTÉES — ici c'est du texte
#   à LIRE) : ajoute un bandeau "⚠️ Vérification automatique de sécurité" visible et impossible
#   à manquer à la fin de la réponse, listant précisément ce qui a été détecté. Câblé aux 2
#   points de sortie de la boucle agent (réponse finale normale ET fin forcée à MAX_TOOL_STEPS,
#   v2.126). Best-effort : `_scan_dangerous_script_patterns` n'a jamais d'exception qui remonte.
#
# v2.132 (🌡️ température profil analysis abaissée 0.3→0.15) : question directe de l'utilisateur
#   (« peut-on changer la température via des commandes ollama pour le modèle cloud ? »).
#   Réponse : techniquement possible via `ollama create` + Modelfile, mais INUTILE pour Marvin —
#   vérifié dans le code que `agent.py` envoie déjà `system` et `options.temperature` explicitement
#   à CHAQUE appel `/api/chat`, quel que soit le modèle (local ou `:cloud`), ce qui prime toujours
#   sur un Modelfile figé côté Ollama. Proposé de baisser directement la température de Marvin à la
#   place — accepté (« oui, teste ça »).
#   `config.py::MODEL_PROFILES["analysis"]["temperature"]` 0.3→0.15 (même doctrine que le profil
#   `agent`, déjà à 0.1 — réponses techniques longues = tool-calling déterministe attendu aussi).
#   Testé en réel : 10 nouvelles générations (2 formulations différentes de script d'installation
#   touchant MariaDB) après la baisse → 1/10 a encore modifié le mot de passe root (vs ~2/3 avant
#   la baisse), et le filet déterministe v2.131 l'a correctement flaguée. Confirme que la
#   température seule ne suffit jamais à garantir 100% — c'est un complément au filet
#   déterministe, pas un remplacement.
#
# v2.133 (🛡️ filet déterministe étendu au CONTENU des documents générés) : suite de « continue
#   sur cette voie ». Angle mort trouvé en relisant le filet v2.131 : il ne scannait que la
#   réponse de CHAT visible, jamais les arguments passés aux outils de génération de document
#   (`file_create_pdf`, `document_generate`, `billing_quote_pdf`, `file_convert_docx_to_pdf`).
#   Or le PDF GLPI qui a motivé TOUT ce chantier (v2.127 — mot de passe root vidé, `$(date...)`
#   littéral) avait ses défauts dans le contenu du DOCUMENT, jamais dans le texte de chat
#   lui-même — le scanner v2.131 tel quel ne l'aurait donc PAS attrapé. Corrigé : scan de
#   `tool_args["content"]`/`["body"]` juste après l'exécution réussie d'un de ces 4 outils,
#   résultat stocké dans `result["security_warning"]` (nouveau champ), affiché dans
#   `GeneratedFileCard.jsx` sous la carte de fichier cliquable (bandeau rouge, toujours visible,
#   pas seulement dans le JSON brut).
#   Liste de motifs élargie au passage (`_DANGEROUS_SCRIPT_PATTERNS`) : `curl|sh`/`wget|sh`
#   (exécution de script distant sans inspection), `curl -k`/`--insecure` (TLS désactivé),
#   `PermitRootLogin yes`, désactivation de pare-feu (`ufw disable`/`iptables -F`), service
#   bindé sur `0.0.0.0`. + liste séparée `_DANGEROUS_DOCUMENT_PATTERNS` (substitution shell non
#   évaluée `$(date...)`) appliquée UNIQUEMENT au scan de document — ce motif est un FAUX POSITIF
#   garanti sur un scan de script ```bash générique (`$(hostname -I)` etc. y est parfaitement
#   normal), piège repéré et corrigé avant tout test.
#
# v2.134 (🩺 diagnostic PC réel + compétence dédiée + lisibilité chat) : demandé explicitement
#   sur une VRAIE conversation ("contrôle du pc pour connaître les problèmes logiciels et
#   physiques") — « fait tout et améliore la lisibilité de tout cela et fait en sorte que Marvin
#   crée les compétences au besoin ». Audit préalable : le rapport généré affirmait « aucune
#   alerte de surchauffe détectée » alors qu'AUCUN outil existant ne lit jamais de capteur de
#   température — une hallucination (règle #3) rendue possible par l'absence de la donnée
#   elle-même, pas par le modèle qui invente délibérément.
#   3 nouveaux outils, tous basés sur des données RÉELLES (jamais estimées) :
#   - `pc_hardware_temps` : capteur ACPI (CPU, souvent absent sur desktop — renvoie explicitement
#     "non disponible" plutôt que de deviner) + `nvidia-smi` (GPU, testé en réel : 49°C mesurés).
#   - `pc_disk_smart_health` : compteurs de fiabilité Windows Storage Management (usure SSD,
#     erreurs de lecture non corrigées) — plus profond que le simple `HealthStatus` déjà exposé
#     par `win_disk_info`. Testé en réel : fonctionne sans crash même quand les compteurs
#     reviennent `null` (courant selon le contrôleur disque — dépend du matériel, pas un bug).
#   - `pc_event_log_errors` : erreurs Système+Application des 7 derniers jours (Get-WinEvent,
#     un seul appel pour les 2 journaux, filtré Critique/Erreur) + détection de sources
#     récurrentes (signal de problème persistant vs ponctuel). Testé en réel : 20 événements
#     réels remontés ; timestamp corrigé pour être lisible humain (`.ToString(...)` dans le
#     script PS) au lieu du format .NET brut `/Date(...)/ ` initialement renvoyé.
#   Nouvelle compétence `data/skills/diagnostic-pc-complet.md` : bundle les 4 outils existants +
#   les 3 nouveaux + `web_search` pour une vérification RÉELLE des pilotes (au lieu du
#   « vérifie toi-même » précédent), avec consigne explicite anti-hallucination (ne jamais
#   affirmer une température/usure/erreur sans avoir appelé l'outil correspondant) et le format
#   de sortie de la règle d'or #13 (structuré/sécurisé/complet).
#   Lisibilité chat (`MessageBubble.jsx`) : 4 nouveaux rendus dédiés réutilisant `DashboardKit`
#   (déjà éprouvé sur Monitoring/Santé) — `win_system_report` en jauges CPU/RAM + barres disques
#   au lieu d'un JSON/tableau markdown brut, `pc_hardware_temps`/`pc_disk_smart_health`/
#   `pc_event_log_errors` en cartes/tableaux colorés (rouge sur seuil dépassé) au lieu du
#   fallback JSON générique.
#
# v2.135 (🔤 mojibake PowerShell corrigé — bug préexistant, pas une régression v2.134) :
#   l'utilisateur a signalé un souci pendant le test réel du diagnostic PC complet (« je pense
#   il y a un souci, coupe Marvin et relance-le proprement et fixe le souci »). Diagnostiqué
#   méthodiquement : chaque nouvel outil testé individuellement répond en 1-2s — pas de hang
#   réel, juste la lenteur normale d'un enchaînement de ~8 appels d'outils+LLM. MAIS un vrai
#   bug trouvé au passage sur `execute_pc_event_log_errors` : les accents français ("s'est",
#   "réseau") ressortaient en mojibake ("s�est", "r�seau"). Vérifié que `win_event_log`
#   (existant, non touché par v2.134) a EXACTEMENT le même défaut — donc préexistant, pas
#   introduit par les nouveaux outils.
#   Cause racine : `execute_pc_run_powershell` capture la sortie avec `text=True,
#   encoding="utf-8", errors="replace"` — malgré le `[Console]::OutputEncoding=UTF8` injecté en
#   tête de script, PowerShell en mode `-EncodedCommand` + stdout redirigé écrit en pratique en
#   Windows-1252 (confirmé : l'apostrophe typographique Windows, octet 0x92 en cp1252, est un
#   octet UTF-8 invalide isolé → remplacé silencieusement par `errors="replace"`). Corrigé :
#   capture des octets bruts (`text=False`), décodage UTF-8 strict en priorité, repli sur cp1252
#   UNIQUEMENT si le décodage UTF-8 échoue réellement — bénéficie à TOUS les outils qui passent
#   par `execute_pc_run_powershell` (win_event_log, win_disk_info, pc_disk_smart_health,
#   pc_event_log_errors, etc.), pas seulement aux 3 nouveaux.
#
# v2.136 (⏱️ diagnostic PC complet — pas de bug, mais 9,4 min de latence expliquée + resserrée) :
#   après le fix v2.135, le frontend était aussi tombé (port 3000 injoignable — relancé
#   proprement sur demande explicite, aucun lien avec le code : `npm run dev` a démarré sans
#   erreur, donc pas une régression de `MessageBubble.jsx`). Rejoué le diagnostic complet
#   réel de bout en bout (SSE brut, 563s) pour vérifier : la RÉPONSE FINALE est excellente
#   (données réelles : GPU 49°C, SMART sain, 8 erreurs DNS récurrentes détectées, service en
#   échec identifié, 26 programmes au démarrage listés) — aucun bug de correction, juste une
#   lenteur réelle. Cause : 11 appels d'outils séquentiels au lieu des 7 prévus par la
#   compétence (le modèle a aussi appelé `win_network_config`, `win_startup_programs`,
#   `pc_process_list`, `file_large_finder`, non listés) — chaque aller-retour vers le modèle
#   cloud coûtant ~30-60s indépendamment du volume de sortie (latence API, pas de génération).
#   `data/skills/diagnostic-pc-complet.md` resserrée : consigne explicite de ne PAS appeler
#   d'outils hors de la liste des 7 sans mention explicite de l'utilisateur — la liste `tools:`
#   du frontmatter est ADDITIVE (ajoute au catalogue déjà filtré par mots-clés) et non
#   restrictive (vérifié dans `agent.py::run_agent`), donc seule une consigne dans le corps de
#   la compétence peut influencer ce comportement (pas de garantie à 100%, même limite
#   structurelle que documentée en v2.130/131 sur les LLM probabilistes).
#
# v2.137 (🔧 3 nouveaux outils + correctif retry Ollama) : sur demande explicite (« fait les 3
#   et corrige skills/suggest »), suite à l'audit v2.136 (905 exécutions réelles analysées :
#   43/43 outils OK sur l'échantillon système, aucun échec récent significatif ; `calendar_list`
#   avait un pic de 60 échecs historiques mais auto-résolu depuis 3 semaines).
#   BUG RACINE trouvé en diagnostiquant la lenteur de `/api/skills/suggest` (timeout dépassé à
#   5 min, backend resté sain) : `tools.py::_ollama_generate` retentait le modèle PRIMAIRE 3×
#   AU TIMEOUT COMPLET avant même d'essayer le repli léger — pire cas 3×240s = 12 min rien que
#   sur le primaire, pour un point d'entrée partagé par 13+ outils. Un timeout sur un GROS
#   prompt (comme les ~120 messages analysés par suggest_skills) est structurel, pas un blip
#   réseau transitoire — réessayer à l'identique échoue pareil. Corrigé : 1 essai primaire au
#   timeout complet, 1 SEUL retry primaire si l'échec n'était PAS un timeout (connexion/5xx
#   ponctuel — là un retry a du sens), puis repli léger à timeout RÉDUIT (30-60s). Pire cas
#   ramené de 4×timeout à timeout+timeout_léger — pour `/api/skills/suggest` (timeout=240),
#   ~240s+60s=300s max au lieu de jusqu'à 960s+.
#   3 nouveaux outils (`pc_hardware_temps`/`pc_disk_smart_health`/`pc_event_log_errors` déjà
#   en v2.134) : `win_firewall_status` (profils pare-feu réels + nb règles entrantes autorisées,
#   rendu structuré au lieu de parser du texte PowerShell brut) ; `pc_driver_check` (recherche
#   web CIBLÉE et systématique pour un composant donné — remplace le pari que le modèle pense
#   à appeler `web_search` avec une bonne requête, la compétence diagnostic-pc-complet l'utilise
#   désormais explicitement) ; repli OAuth pour `calendar_list` quand le compte de service
#   renvoie 404 (l'agenda personnel n'a pas été partagé avec l'e-mail du compte de service) —
#   directement motivé par les 60 échecs historiques trouvés dans l'audit, même s'ils sont
#   actuellement dormants.
#
# v2.138 (🧱 4 piliers de fiabilité — validation, tendance, dashboard, fiabilité composée) : sur
#   demande explicite (« fait le tout les points »), suite à une recherche web sur le tool-calling
#   agentique et le monitoring IT 2026.
#   1. **Validation des arguments AVANT exécution** (`agent.py::_validate_tool_args`) : couche
#      manquante des 3 recommandées (validation → retry ciblé → decoding contraint — la 2ᵉ existe
#      déjà via le garde de sécurité + le repli léger v2.137). Conservatrice à dessein : vérifie
#      seulement la PRÉSENCE des paramètres obligatoires déclarés dans TOOLS_SPEC, pas de
#      coercition de type stricte qui casserait des appels qui marchent déjà.
#   2. **Suivi de tendance** (`system_snapshots` + `pc_health_trend` + `_health_trend_worker`) :
#      un instantané quotidien (RAM/disque/usure SSD/erreurs récurrentes, via psutil + les outils
#      v2.134) plutôt qu'un instantané isolé — permet de répondre « le disque sera plein dans
#      combien de temps ? » avec une vraie extrapolation au lieu d'un pourcentage figé.
#   3. **Tableau de bord de fiabilité des outils** (`db.get_tool_reliability` + `/api/history/
#      reliability` + outil `pc_tool_reliability`) : les données existaient déjà dans
#      `tool_executions` mais n'étaient jamais agrégées par TAUX D'ÉCHEC, seulement par volume —
#      exactement ce qui a permis de rater 60 échecs de `calendar_list` jusqu'à une requête SQL
#      manuelle. Ferme cette boucle : c'est maintenant une donnée consultable, pas un audit ad hoc.
#   4. **Compensation de la fiabilité composée** : à 95% de fiabilité par appel, une chaîne de 8
#      outils ne réussit globalement qu'à ~66% (source : littérature 2026 sur les agents LLM).
#      Trace désormais dans `audit.jsonl` (`_long_tool_chain`) dès qu'un tour dépasse 8 appels —
#      visibilité pure, aucun changement de comportement, pour repérer ce signal sans recompter
#      à la main comme fait pour le diagnostic v2.136.
#
# v2.139 (📡 traçabilité par conversation + inventaire réseau + connecteurs ITSM multi-produit) :
#   sur demande explicite (« fait tout à ceci près que les connecteurs doivent couvrir une large
#   gamme de produits qui me seront utiles »), suite à une recherche web sur l'observabilité des
#   agents IA et les outils d'inventaire IT 2026.
#   BUG TROUVÉ EN IMPLÉMENTANT (pas cherché délibérément) : la boucle de chat (`agent.py`)
#   n'écrivait JAMAIS dans `tool_executions` — seuls `/api/tools` (boutons UI), cron, ssh_exec
#   REST et email_send y écrivaient. Le tableau de bord de fiabilité v2.138 ne voyait donc
#   qu'une fraction du vrai usage (les appels PILOTÉS PAR LE LLM, la majorité en pratique,
#   étaient invisibles). Corrigé : `db.log_execution` appelé depuis la boucle de chat avec
#   timing réel + `conversation_id` pour corrélation.
#   1. **Traçabilité par conversation** : colonne `conversation_id` sur `tool_executions` +
#      `db.get_conversation_trace` + outil `pc_conversation_trace` — chronologie complète d'un
#      tour (durée de chaque outil, ordre réel), remplace le recomptage manuel des `tool_start`
#      fait plusieurs fois cette session pour diagnostiquer une lenteur.
#   2. **Inventaire réseau persistant** (mini-CMDB) : table `network_devices` + `net_inventory_
#      scan` (scan + enregistrement, première/dernière apparition) + `net_inventory_list` +
#      `net_inventory_annotate` (nom personnalisé/notes) — un scan devient un inventaire
#      consultable dans le temps, pas un instantané jetable.
#   3. **Connecteurs ITSM multi-produit** : architecture GÉNÉRIQUE (`itsm_ticket_list`/
#      `itsm_ticket_create`/`itsm_asset_list`, paramètre `system`) — ajouter un nouveau produit
#      (Zammad, osTicket, Freshservice...) ne touche que `_ITSM_BACKENDS`, jamais les outils.
#      GLPI implémenté en premier (en cours de déploiement réel par l'utilisateur) via son API
#      REST (`initSession`/`killSession` par appel, credentials via `credentials_manager`).
#      `itsm_ticket_create` ajouté à `DANGEROUS_TOOLS` (confirmation obligatoire — visible par
#      d'autres personnes dans le système externe).
#
# v2.140 (📎 glisser-déposer + pièces jointes multiples dans le chat) :
#   sur demande explicite (« fait le glisser-déposer et les pièces jointes multiples »),
#   2 des 3 items frontend laissés de côté en v2.139 (le 3e, templates de prompt, non demandé
#   ici). Changement 100% frontend (`components/chat/ChatInput.jsx`), aucune logique Python
#   modifiée — HMR Next.js suffit, pas de redémarrage backend nécessaire.
#   - `attachedFile` (objet unique) → `attachedFiles` (tableau) : `uploadDocFile(file)` extrait
#     la logique d'upload en helper réutilisable, `handleDocSelect` traite plusieurs fichiers
#     en parallèle (`Promise.all`), chaque fichier a sa propre carte avec bouton de retrait
#     individuel (`removeAttachedFile(idx)`). `doSubmit` combine tous les documents lisibles
#     en un seul message avec un bloc "📎 Document joint « nom » :" par fichier.
#   - Glisser-déposer : handlers `onDragEnter/Leave/Over/Drop` sur le `<form>`, compteur
#     `dragCounter` (ref) pour gérer correctement les événements imbriqués des enfants (sinon
#     l'overlay clignote), classification par `file.type.startsWith('image/')` pour router vers
#     le bon pipeline existant (upload image vs upload document). Overlay visuel (bordure
#     pointillée accent, message) affiché pendant le survol.
#   Vérifié en réel (Playwright, channel="chrome") : 0 erreur console au chargement ; 2 fichiers
#   .txt réels attachés via l'input caché → 2 cartes distinctes avec comptage de caractères
#   exact (35/36) ; `dragenter` synthétique → overlay rendu correctement ; `drop` synthétique
#   avec fichier réel → traité et affiché (35 car.) ; test de bout en bout (2 fichiers + question
#   + soumission) → message combiné correct avec les 2 documents étiquetés séparément, Marvin
#   traite normalement derrière. `scripts/smoke_test_chat.py` : 5/5.
#
# v2.141 (☁️ routage cloud par TÂCHE + 🧠 passe de critique 2e modèle) :
#   sur demande explicite (« je préfère que l'on travail le plus possible avec les
#   models cloud [...] fait aussi la critique [...] revue critique d'un autre llm
#   avant d'envoyer la réponse »), suite à une recherche web sur les benchmarks
#   agentiques 2026 des modèles cloud Ollama disponibles.
#   VÉRIFIÉ EN DIRECT avant implémentation : `cloud_overrides` était déjà appliqué
#   aux 3 profils (agent/chat/analysis), donc tout ce qui n'est pas sensible passait
#   déjà par le cloud — la préférence de l'utilisateur était déjà largement respectée.
#   Le vrai écart : un SEUL modèle cloud (deepseek-v4-flash) pour tout, alors que les
#   benchmarks montrent des écarts nets par spécialité (GLM-5.2 : 90,6% tool-calling,
#   meilleur du comparatif ; qwen3-coder:480b : nettement meilleur en code long).
#   1. **Routage par TÂCHE** (`cloud_routing.py::detect_task/get_task_overrides`) :
#      un signal détecté dans le message (script/installation/commande/docker...)
#      route vers `cloud_task_overrides["code"]` (qwen3-coder:480b-cloud), prioritaire
#      sur l'override de PROFIL — câblé à la fois dans `agent.py::run_agent` (boucle
#      principale) et `cloud_routing.py::resolve_model()` (appels LLM internes aux
#      outils), mêmes garanties (cloud_enabled + non-sensible) jamais contournées.
#      Réglage appliqué : agent→glm-5.2:cloud (le généraliste agentique était sur le
#      modèle le MOINS bon des 3 en tool-calling), chat/analysis→deepseek-v4-flash.
#   BUG TROUVÉ EN IMPLÉMENTANT (pas cherché délibérément) : `is_cloud_model()` ne
#      testait que le suffixe `:cloud` — or `qwen3-coder:480b-cloud` (et plusieurs
#      autres modèles cloud installés) suffixent le TAG par `-cloud`, pas `:cloud`.
#      La protection mid-boucle (bascule vers le local si un outil sensible est
#      appelé en cours de tour) ne les aurait JAMAIS reconnus comme "cloud" — fuite
#      potentielle silencieuse. Corrigé (accepte les deux suffixes).
#   2. **Passe de critique par un 2e modèle** (`agent.py::_run_critique_pass`) :
#      après le scanner déterministe existant (v2.131/2.133, motifs regex connus
#      à l'avance), un vrai jugement de modèle — principe Mixture-of-Agents (un 2e
#      regard indépendant détecte ce qu'un modèle ne voit pas dans sa propre sortie).
#      Scope VOLONTAIREMENT restreint aux réponses contenant un bloc de code (même
#      critère que le scanner) : appliquer ça à chaque message aurait doublé la
#      latence pour zéro bénéfice (régression déjà vécue et corrigée v2.125/2.126).
#      Produit un BANDEAU visible, jamais une réécriture silencieuse (invérifiable).
#      Modèle critique DIFFÉRENT du modèle qui a répondu (diversité de jugement),
#      reste dans les modèles cloud déjà configurés par l'utilisateur ; repasse en
#      local si la requête est sensible (mêmes garanties que le reste du module).
#   ITÉRATION SUR LE PROMPT (testé, pas supposé) : 1er prompt trouvé TROP sensible
#      (flaguait "usage de sudo" et "vérification finale manquante" sur une réponse
#      déjà propre — faux positif reproduit en test direct) → resserré à 4 catégories
#      GRAVES uniquement (ID inventé, info fausse, régression sécurité, syntaxe non
#      évaluée), avec consigne explicite d'ignorer le style. Re-testé : le cas propre
#      ne déclenche plus, le cas dangereux (mot de passe root vidé) déclenche toujours.
#      2e bug trouvé en testant : un appel a dégénéré en sortie quasi vide ("-" seul)
#      → filet de longueur minimale ajouté (sinon bandeau vide affiché pour rien).
#   Testé en réel (curl SSE + appels directs à `_run_critique_pass`) : "quelle heure
#   est-il" → glm-5.2:cloud ; "script bash installation nginx" → qwen3-coder:480b-cloud
#   (routage tâche confirmé) ; requête avec "mot de passe" → reste local qwen2.5:14b
#   (garde de sensibilité intacte) ; critique testée 3× sur réponse dangereuse (mot de
#   passe root vidé) → détectée à chaque fois ; testée 2× sur réponse propre (install
#   nginx) → aucun faux positif après resserrage du prompt.
#
# v2.142 (🚀 « surpasser le payant » — 4 fonctionnalités + 1 BUG RACINE majeur trouvé
#   en cours de route) : sur demande explicite (« continue de faire en sorte que le
#   chat devienne meilleur que les modèles payants [...] propose-moi des améliorations
#   de fonctionnalité et d'intelligence » puis « fait tout »), suite à une recherche
#   web sur les fonctionnalités phares 2026 de ChatGPT/Claude/Gemini/Perplexity,
#   croisée avec un audit du code existant (pas juste supposé).
#
#   1. **Sécurité `code_python` + vrai Code Interpreter** : l'ancien `execute_code_python`
#      tournait par `exec()` DANS le process du backend, avec `os` importé SANS
#      CONDITION et une liste noire par SOUS-CHAÎNE littérale — contournable
#      (`getattr(os,'sys'+'tem')(...)` ne contient aucune chaîne interdite). Réécrit :
#      exécution dans un SOUS-PROCESSUS isolé (`.venv` python, cwd dédié), analyse AST
#      STRUCTURELLE avant exécution (`_scan_code_ast` — détecte tout `import`/`eval`/
#      `exec`/`open` quelle que soit l'obfuscation, puisque sans l'import le nom
#      n'existe simplement pas). Bonus : tout fichier écrit (graphique matplotlib, CSV)
#      est automatiquement détecté et affiché cliquable dans le chat (réutilise
#      GeneratedFileCard v2.128, étendu aux images avec vignette inline + tableau de
#      fichiers multiples).
#   2. **`web_deep_research`** : recherche multi-passes (recherche → juge les trous →
#      recherche complémentaire ciblée, jusqu'à 6 fois) avec rapport structuré à
#      citations numérotées — équivalent Deep Research de tous les concurrents payants.
#      Outil séparé de `web_research` (déclenché uniquement sur demande explicite,
#      plusieurs minutes d'exécution).
#   3. **Projects avec instructions persistantes** : un projet n'était jusqu'ici qu'un
#      NOM. Colonne `instructions` ajoutée, injectée automatiquement dans le prompt
#      système de toute conversation du projet (`PUT /api/projects/{id}`, panneau ⚙️
#      dans la sidebar) — équivalent Claude/ChatGPT Projects.
#   4. **`ai_model_council`** : interroge plusieurs modèles cloud DIFFÉRENTS en
#      parallèle sur la même question et synthétise accord/désaccord — équivalent
#      Model Council de Perplexity (fév. 2026). Marvin a plus de diversité de modèles
#      (7 cloud installés) que le conseil à 3 de Perplexity. Explicite, jamais par défaut.
#
#   🔴 BUG RACINE TROUVÉ EN DIAGNOSTIQUANT LE POINT 3 (pas cherché délibérément) : les
#      instructions de projet n'avaient AUCUN effet malgré une injection confirmée
#      correcte dans `system_prompt`. Isolé par test direct contre Ollama : le champ
#      TOP-LEVEL `"system"` de `/api/chat` est SILENCIEUSEMENT IGNORÉ — reproduit 0/3
#      sur glm-5.2, deepseek-v4-flash ET qwen2.5:14b LOCAL (donc pas spécifique à un
#      modèle ni au cloud), avec et sans `tools` (donc pas spécifique au tool-calling).
#      Le MÊME contenu placé comme message `{"role":"system", ...}` en tête de
#      `messages[]` fonctionne 3/3. Corrigé aux 2 points d'appel Ollama dans
#      `agent.py::run_agent` (champ `system` gardé en redondance défensive, ne coûte
#      rien). IMPACT : ce bug affectait potentiellement TOUTES les règles d'or de
#      `_build_system_prompt` depuis leur introduction (français forcé, anti-
#      hallucination, sécurité #7-13...) — explique en partie le "plafond de fiabilité
#      du prompt engineering" observé et documenté à plusieurs reprises cette session
#      (v2.125-2.133). Un commentaire de code déjà présent (v2.123, mémoire/recall
#      injecté dans le dernier message utilisateur "sinon noyée dans le long prompt
#      système et ignorée par le modèle") avait déjà touché du doigt le symptôme sans
#      identifier la cause exacte (attribué à la dilution, pas à un champ ignoré).
#   Testé en réel : régression vérifiée après le fix (règle française toujours
#   respectée sur question anglaise, tool-calling toujours fonctionnel 2/2 outils
#   appelés) + `scripts/smoke_test_chat.py` 5/5 ; instructions de projet confirmées
#   appliquées de bout en bout via vrai chat (tag exact retrouvé dans la réponse) ;
#   `code_python` : import os/eval/exec/__import__ tous bloqués sans confirmation,
#   code propre exécuté directement, graphique matplotlib capturé et chemin renvoyé ;
#   `web_deep_research` : rapport réel généré (4 sources, 1 passe) ; `ai_model_council` :
#   2 modèles consultés en parallèle, synthèse cohérente produite.
#
# v2.143 (🧠 RAG agentique pour document_ask) : sur demande explicite (« continue sur
#   cette voie pour augmenter le niveau d'intelligence de Marvin »), suite du chantier
#   v2.142. `document_ask` faisait une recherche UNIQUE et figée (naive RAG) — même
#   limite que celle corrigée pour `web_research`→`web_deep_research` en v2.142, jamais
#   appliquée au RAG documentaire local. Ajouté : après la 1ʳᵉ recherche, un petit
#   modèle JUGE si le contexte récupéré suffit ; sinon reformule UNE requête
#   complémentaire (mots-clés différents) pour une 2ᵉ recherche, résultats fusionnés
#   (dédoublonnés par texte) avant la synthèse finale. Coût borné à AU PLUS 1 recherche
#   + 1 petit appel de jugement supplémentaires (pas une boucle non bornée comme
#   `web_deep_research` — le corpus local est petit, pas besoin de 6 passes).
#   Recherche menée avant implémentation : vérifié que le paramètre Ollama `think`
#   n'apporte AUCUNE différence sur les modèles cloud installés (glm-5.2 émet déjà
#   son raisonnement par défaut, avec ou sans le flag — testé en isolation, résultat
#   identique) — piste explorée puis écartée sur preuve, pas laissée en l'état.
#   Testé en réel : indexation d'un document de test à 2 sections de vocabulaire
#   disjoint (installation technique / code de facturation), question portant sur les
#   deux → réponse complète et correcte, citée, avec fusion de plusieurs passes de
#   recherche confirmée (champ `sources` enrichi) ; document de test retiré de l'index
#   après coup. `scripts/smoke_test_chat.py` 5/5 après coup (aucune régression).
#
# v2.144 (🔐 SSH ad hoc + garde-fou "écrire ≠ exécuter" + règle d'or #14) : audit d'une
#   vraie conversation demandé explicitement (« regarde les dernières conversations et
#   dis-moi ce que tu penses de ce comportement »). Trouvé (pas supposé) : sur « script
#   d'installation de zabbix server sur debian 13 avec mariadb », l'agent avait appelé
#   `pc_run_command` avec un script RHEL/CentOS (dnf, systemctl) SUR LA MACHINE WINDOWS
#   LOCALE — sans dégât (dnf n'existe pas sous Windows) mais révélateur d'une confusion
#   « écrire une commande » / « l'exécuter ICI ». `pc_run_command` n'est routé par aucun
#   mot-clé (arrive via similarité sémantique, correctement) — le vrai trou : aucune des
#   13 règles d'or n'interdisait explicitement cette confusion.
#   1. **Règle d'or #14** : ne jamais confondre écrire un script pour un AUTRE système
#      (OS différent, machine distante) avec l'exécuter localement. N'exécute sur LA
#      machine locale que si explicitement demandé pour elle ; pour une machine
#      distante, utilise `ssh_exec`/`ssh_write_and_run` — jamais `pc_run_command` comme
#      substitut. Testé en réel : reproduction EXACTE du message qui a causé le bug
#      d'origine → 0 appel d'outil cette fois, script livré directement en texte avec
#      une note explicite sur la machine cible.
#   2. **Filet déterministe complémentaire** (`security.py::detect_cross_platform_
#      mismatch`) : avant toute confirmation de `pc_run_command`/`pc_run_powershell`,
#      détecte des motifs clairement non-Windows (sudo, apt/dnf/yum, systemctl, chmod
#      +x, shebang bash...) et enrichit le message de confirmation d'un avertissement
#      visible — pas un blocage dur (une commande Linux n'est pas catastrophique en
#      soi, WSL/tests de syntaxe sont légitimes), mais l'HUMAIN voit l'alerte avant de
#      cliquer confirmer, même si le jugement du modèle a échoué malgré la règle #14.
#      Bug trouvé au passage : `ssh_exec_multi` n'avait JAMAIS le garde `security.
#      guard_result()` (présent sur `ssh_exec` depuis v2.117) — corrigé, d'autant plus
#      important qu'elle vise plusieurs machines à la fois.
#   3. **SSH ad hoc** (`_resolve_ssh_target`, partagé par `ssh_exec` et le nouvel outil
#      `ssh_write_and_run`) : demandé explicitement (« si je lui demande de se connecter
#      avec cet ip et ces credentials il doit pouvoir le faire »). `ssh_exec` accepte
#      maintenant host/username/password/private_key DIRECTEMENT, sans connexion
#      sauvegardée au préalable — même garde-fou déterministe, même confirmation
#      obligatoire, rien d'affaibli. Connexion ad hoc réussie → `suggest_save_
#      connection` proposé (jamais automatique, l'utilisateur décide).
#   4. **`ssh_write_and_run`** (nouvel outil) : écrit un script généré sur une machine
#      distante via SFTP PUIS l'exécute — pour « crée un script d'installation de X et
#      lance-le sur ce serveur » en un seul geste, sans heredoc bash fragile dans
#      `ssh_exec`. Contenu passé par le même `security.guard_result()`.
#   Testé en réel : `detect_cross_platform_mismatch` 5/5 commandes Linux détectées, 3/3
#   commandes Windows silencieuses ; `ssh_exec`/`ssh_write_and_run` ad hoc — validation
#   des paramètres manquants, contenu catastrophique bloqué par le garde déterministe
#   AVANT toute tentative SFTP, connexion vers une IP injoignable tentée pour de vrai
#   et échoue proprement (timeout, pas un crash) ; reproduction du bug d'origine → 0
#   appel d'outil, script direct. `scripts/smoke_test_chat.py` 5/5.
#
# v2.145 (🚀 3 idées de GPT-5.6 Sol/ChatGPT Work — Sites, Ultra mode, tâche longue) : sur
#   demande explicite (« regarde les nouveautés [ChatGPT Sol/GPT-5.6] et dis-moi ce qu'on
#   peut reprendre » puis « les 3 »), recherche web menée avant implémentation.
#
#   1. **`webapp_create`** (« ChatGPT Sites ») : génère une mini-appli web autonome (HTML/
#      CSS/JS self-contained) ouverte dans le navigateur par défaut — réutilise `pc_open_
#      file`/`os.startfile()` tel quel (déjà le bon comportement pour un .html, zéro code
#      supplémentaire) et `GeneratedFileCard` (v2.128) étendu aux .html/.htm.
#   2. **`ai_subagents_run`** (« Ultra mode ») : décompose un objectif en 2-5 sous-tâches
#      INDÉPENDANTES traitées en parallèle (raisonnement, pas d'accès outils) puis
#      synthétisées — positionnement HONNÊTE dans la description : PAS de vrais sous-agents
#      avec outils comme Ultra (coordination "dans les poids" du modèle), un vrai gain de
#      rapidité/qualité sur des tâches qui se décomposent en angles indépendants.
#   3. **Tâche longue autonome** (« ChatGPT Work », allégé) : `long_task_start` décompose
#      un objectif en checklist (table `tasks` existante), avance immédiatement dans le
#      tour courant, puis programme un job CRON (`_long_task_resume`, nouveau cas spécial
#      dans `_cron_worker`) qui relance un VRAI tour `run_agent` (outils complets) toutes
#      les 5 min jusqu'à ce que tout soit fait. `long_task_status`/`long_task_stop` pour le
#      contrôle utilisateur. Positionnement honnête : reprise toutes les 5 min, pas un
#      process continu pendant des heures (infra cloud dédiée chez OpenAI).
#      **3 bugs trouvés en testant EN RÉEL** (pas supposés) :
#      a) Nommer littéralement les outils dans le message de reprise ("Utilise long_task_
#         status... task_update...") déclenchait la règle d'or #6 (outil explicite cité =
#         SEUL outil autorisé), bloquant l'accès aux VRAIS outils nécessaires pour avancer
#         — corrigé en décrivant l'étape en PROSE sans jamais nommer un outil précis.
#      b) `long_task_status` n'exposait pas l'`id` réel de la tâche → le modèle inventait
#         un identifiant (le tag, un numéro de position) pour `task_update`, échec
#         systématique — corrigé en donnant l'ID exact de la PROCHAINE étape directement
#         dans le message de reprise.
#      c) Une reprise SANS limite de temps peut enchaîner assez d'appels d'outils/cloud
#         pour prendre plusieurs MINUTES (même symptôme déjà documenté en v2.136) —
#         `asyncio.wait_for` borne chaque reprise à 3 min (buffer avant le prochain cycle
#         à 5 min) ; la progression déjà faite reste sauvegardée (run_agent écrit chaque
#         message au fil de l'eau), seule la suite est coupée et reprise au cycle suivant.
#      Petit correctif de qualité au passage : le prompt de décomposition demandait des
#      "étapes actionnables" sans préciser PAR QUI — le modèle proposait parfois des
#      instructions manuelles ("appuyez sur la touche Windows") inexécutables par un
#      agent autonome — précisé explicitement dans le prompt.
#   Testé en réel de bout en bout (2 fois, avec fix) : conversation réelle créée, tâche
#   longue démarrée, checklist créée avec IDs réels, job cron déclenché par le VRAI worker
#   (pas simulé), reprise complétée dans le délai borné, backend resté réactif tout du
#   long (vérifié par sondage pendant l'exécution) ; décomposition re-testée après le
#   correctif de prompt → étapes orientées outils au lieu d'instructions manuelles.
#   `ai_subagents_run` testé en réel (3 sous-tâches sécurité réseau, réponses détaillées
#   et correctes, synthèse cohérente) ; `webapp_create` testé (fichier HTML généré et
#   correctement enveloppé). `scripts/smoke_test_chat.py` 5/5, tous les artefacts de test
#   nettoyés (cron/tâches/conversations).
#
# v2.146 (🎯 UI — bandeau de MODE + langage clair + repli d'étapes + tâche de fond visible) :
#   sur demande explicite (« retravaille l'UI du chat pour que l'on sache que Marvin selon
#   nos requêtes travaille d'une certaine manière précise »), recherche menée sur les
#   patterns 2026 (Perplexity Pro Search : étapes en langage clair, repliées par défaut,
#   réponse prioritaire). Changement 100% frontend, aucune logique Python modifiée.
#   1. **Bandeau de mode** (`MessageBubble.jsx::TurnModeBadge`) : pilule colorée en tête de
#      réponse dès qu'un outil est appelé — 🔍 Recherche approfondie, 🧑‍🤝‍🧑 Panel d'experts IA
#      (nom choisi après retour explicite — « conseil de modèles » jugé pas assez parlant),
#      🧩 Sous-tâches parallèles, 🗂️ Tâche longue démarrée, 🐍 Code Interpreter, 🌐 Mini-appli
#      web, 🧠 Compétence activée, ou 🛠️ Agent (outils) en repli générique. Détecté par le
#      nom d'outil appelé dans le tour — aucun événement SSE supplémentaire nécessaire.
#   2. **Noms d'outils en langage clair** : le dictionnaire `toolLabels` existant (v2.9x)
#      était incomplet — tous les outils v2.130-2.145 (ssh_*, code_python, document_*,
#      long_task_*, ai_*...) retombaient sur leur nom technique brut. Étendu + repli
#      "snake_case → Mots séparés" pour tout outil non listé plutôt que d'exposer le nom
#      interne tel quel.
#   3. **Repli des étapes** : au-delà de 3 appels d'outils dans un tour, les cartes se
#      replient par défaut derrière "✅ N/M étape(s) effectuées ▼ Afficher" — la réponse
#      reste prioritaire, le détail se déplie à la demande (pattern Perplexity).
#   4. **Indicateur ambiant de tâche de fond** (`Sidebar.jsx`) : badge "🗂️ N tâche(s) de
#      fond en cours" visible depuis N'IMPORTE QUELLE page dès qu'un job `_long_task_resume`
#      (v2.145) est actif — jusqu'ici totalement invisible tant qu'on ne demandait pas
#      explicitement `long_task_status`. Sondage léger de `/api/cron` toutes les 30s (même
#      cadence que le indicateur Ollama existant), cliquable vers `/tasks`.
#   Testé en réel (Playwright, channel="chrome") : requête code_python → badge "🐍 Code
#   Interpreter" affiché, carte renommée "Exécuter du code Python", résultat 391 correct,
#   0 erreur console ; requête à 4 outils → repli "3/4 étape(s) en cours ▼ Afficher" confirmé
#   fonctionnel en direct (capture d'écran, tour encore en cours) ; page fraîche rechargée
#   → 0 requête réseau en échec. `scripts/smoke_test_chat.py` 5/5.
#
# v2.147 (🎯 UI — rendus dédiés pour les 5 outils "mode" v2.141-145) : sur demande
#   explicite (« continue les améliorations sur cette voie »), suite directe de v2.146.
#   Audité `PrettyResult.jsx`/`MessageBubble.jsx::renderToolResult` : les 5 nouveaux outils
#   (web_deep_research, ai_model_council, ai_subagents_run, long_task_start, long_task_
#   status) retombaient sur le JSON générique malgré des résultats riches — exactement le
#   genre de détail que le bandeau de mode (v2.146) donne envie d'explorer une fois la
#   carte dépliée, mais rien ne l'exploitait.
#   5 rendus dédiés ajoutés à `renderToolResult` : synthèse en markdown (réutilise `marked`/
#   `safeHtml` déjà présents dans le fichier) + détail repliable par défaut (nouveau
#   composant `CollapsibleDetail`) pour les sources (recherche approfondie), les réponses
#   individuelles par modèle (panel d'experts), le détail par sous-tâche (sous-tâches
#   parallèles) ; checklist avec cases à cocher pour `long_task_start`/`long_task_status`
#   (barre de progression + texte barré sur les étapes faites).
#   Testé en réel (Playwright) : requête "démarre une tâche longue" → badge "🗂️ Tâche
#   longue démarrée" affiché, carte d'outil rendue sans erreur (0 erreur console sur 3
#   passes de test, y compris un test intermédiaire accidentellement rejoué sur une
#   ancienne conversation chargée d'historique — confirmé artefact de méthode de test, pas
#   un bug). Les formes de données (steps/groups/individual_answers/subtask_results) sont
#   celles déjà validées en réel côté backend lors de leur implémentation (v2.141-145) —
#   changement purement d'affichage, aucun risque de désynchronisation. `scripts/
#   smoke_test_chat.py` 5/5.
#
# v2.148 (🎯 UI — chrono en direct + garde-fou repli/confirmation) : sur demande explicite
#   (« continue dans cet voie, inspire-toi des dernières nouveautés AI »), recherche menée
#   (patterns d'architecture de statut en 4 couches — ambiant/progression/attention/
#   résumé — et affichage du temps écoulé par sous-agent, tendances agent UI 2026).
#   🔴 BUG TROUVÉ EN AUDITANT (pas cherché délibérément) AVANT d'ajouter la nouvelle
#   fonctionnalité : le repli d'étapes ajouté en v2.146 (`shouldCollapse` dès 3 outils)
#   pouvait cacher par défaut un outil CRITIQUE en attente de confirmation (ex. supprimer
#   un fichier, envoyer un email) derrière "▼ Afficher" — une confirmation d'action
#   potentiellement dangereuse ne doit JAMAIS être masquée. Corrigé : nouvelle fonction
#   `toolNeedsAttention()` (couche "attention" du pattern à 4 niveaux) désactive le repli
#   dès qu'un des outils du tour en a besoin.
#   **Chrono en direct** (`ChatContext.jsx::tool_start` horodate `startedAt`, `ToolCallInline`
#   affiche "⟳ Exécution... (Ns)" au-delà de 3s) : les outils lents (recherche approfondie,
#   panel d'experts, tâche longue) restaient sur "⟳ Exécution..." plusieurs minutes sans
#   AUCUN repère de temps — symptôme déjà documenté (v2.125/v2.136, "Marvin reste
#   bloqué"). Complète le compteur déjà existant sur le `TypingIndicator` (les "trous"
#   entre outils), qui ne couvrait pas la carte d'un outil UNIQUE en cours d'exécution.
#   Testé en réel (Playwright) : `ai_model_council` (appel bloquant unique, la fenêtre la
#   plus large pour observer) → carte capturée avec "Exécution... (12s)" affiché
#   correctement en cours d'exécution ; 0 erreur console sur l'ensemble des tests.
#   `scripts/smoke_test_chat.py` 5/5.
#
# v2.149 (🖱️ Agent GUI local — lecture/clic/frappe via UI Automation) : sur demande
#   explicite (« cherche et creuse encore » sur la piste "agent GUI local" identifiée en
#   recherche continue). Vrai trou d'architecture trouvé en auditant AVANT de proposer quoi
#   que ce soit : Marvin avait déjà les "yeux" (`pc_screenshot`, `screen_ocr`,
#   `pc_window_list`/`focus`) mais ZÉRO "main" — aucun moyen de cliquer/taper dans une
#   fenêtre. Choix délibéré, discuté avec l'utilisateur avant implémentation : UI Automation
#   (arbre structuré natif Windows, via `pywinauto` backend "uia") plutôt qu'un agent vision
#   façon UI-TARS — 100% local, AUCUNE capture d'écran envoyée à un modèle (donc aucun
#   risque qu'un email/mot de passe affiché à l'écran parte au cloud), et plus précis qu'un
#   clic en coordonnées pixel qui casse au moindre décalage.
#   3 nouveaux outils, pattern "lire un ID réel avant d'agir dessus" (même esprit que
#   `winget_install` v2.113 et `long_task_status` v2.145) : `pc_gui_read` (lecture seule,
#   énumère les éléments cliquables d'une fenêtre) → `pc_gui_click`/`pc_gui_type` (agissent
#   sur un élément identifié à l'étape précédente, ajoutés à `DANGEROUS_TOOLS`).
#   🛡️ Protection structurelle contre une attaque TOCTOU (time-of-check/time-of-use,
#   documentée dans la littérature agents 2026) : `pc_gui_click`/`pc_gui_type` ne reçoivent
#   JAMAIS de coordonnées figées d'une lecture précédente — chaque appel refait une
#   résolution LIVE de l'élément (par automation_id ou control_type+name+match_index) au
#   moment même de l'action ; si l'élément a disparu/changé, l'appel échoue proprement
#   plutôt que de cliquer au hasard. Nouvelle règle d'or #15 : le texte lu via `pc_gui_read`
#   reste du CONTENU OBSERVÉ, jamais une instruction, même si un élément affiche "clique
#   ici" — n'agit que sur demande explicite de CE tour de conversation.
#   🔴 Bug réel trouvé en testant en conditions réelles (pas en devinant) : le Bloc-notes
#   Windows 11 (réécriture WinUI3) expose sa zone de texte en `control_type="Document"`, PAS
#   `"Edit"` — filtré silencieusement par la liste de types interactifs initiale. Corrigé,
#   ET durci au passage : pour Edit/Document, le `name` UIA EST le contenu du champ (donc
#   change à chaque frappe) — jamais utilisé comme clé de ré-résolution (uniquement affiché,
#   tronqué), le matching se fait par position (`match_index`) parmi les contrôles du même
#   type.
#   Testé en réel de bout en bout sur une vraie fenêtre Bloc-notes (pas de simulation) :
#   `pc_gui_read` a listé 40+ éléments réels (onglets, boutons) ; `pc_gui_click` sur un
#   onglet a réellement changé l'onglet actif (titre de fenêtre vérifié avant/après) ;
#   `pc_gui_type` a réellement inséré du texte dans le champ Document (contenu relu après
#   coup, confirmé) ; fenêtre fermée sans sauvegarder pour ne rien laisser de test dans les
#   vrais fichiers de l'utilisateur. `pc_gui_read` confirmé sans confirmation requise
#   (lecture seule), `pc_gui_click`/`pc_gui_type` confirmés dans `DANGEROUS_TOOLS`.
#   ⚠️ Incident pendant les tests, sans rapport avec le code livré : un script de test
#   maison a lancé deux processus en parallèle par erreur et tué des connexions SSE en plein
#   streaming → backend bloqué ~20 min (`/api/health` ne répondait plus, sockets en
#   CloseWait). Diagnostiqué, backend redémarré proprement, confirmé sain. Artefact de mon
#   test, pas un bug produit — documenté ici par transparence.
#   Limite connue et assumée, non résolue ici : UI Automation ne franchit pas la frontière
#   UAC (fenêtre élevée/admin inaccessible depuis ce process non-admin) — échec explicite,
#   pas de contournement (cliquer en tant qu'admin serait un risque d'un tout autre ordre
#   que l'allowlist stricte du sidecar élevé, v2.90).
#
# v2.150 (🔒 durcissement pc_gui_* + 🌙 heures calmes) : sur demande explicite (« continue et
#   cherche à corriger, améliorer, sécuriser et prendre les nouveautés AI de chatgpt et
#   claude »).
#   🛡️ Vérifié en conditions réelles (pas supposé) sur les outils GUI livrés en v2.149 :
#   un champ mot de passe peut-il fuiter via `pc_gui_read` ? Test réel avec une vraie
#   fenêtre WinForms (`PasswordChar` + `IsPassword=True`) → Windows UI Automation masque
#   déjà `window_text()` ET `get_value()` (tous deux vides) — rien à corriger côté fuite,
#   c'est une garantie de l'OS. Durci quand même : le champ est désormais étiqueté
#   explicitement `"(champ mot de passe — masqué par Windows)"` + `is_password: true` au
#   lieu d'un `name` vide silencieux qui aurait pu passer pour un bug ou un élément inconnu.
#   🌙 Nouveauté reprise de Claude (recherche menée : "Focus settings" 2026 — heures calmes/
#   pauses/récap) : réglage `quiet_hours` (désactivé par défaut, 22h-7h si activé) qui coupe
#   TOUTE notification proactive (briefing matinal, bilan du soir, anticipation) sur une
#   plage horaire — jamais les demandes faites directement dans le chat, uniquement le
#   déclenchement automatique en arrière-plan. Nouvel onglet dans `/jour` (même pattern que
#   les 3 blocs existants : `saveBlock`/état local/round-trip `/api/proactive`).
#   Testé en réel de bout en bout : `_in_quiet_hours()` unit-testé sur les cas limites
#   (plage à cheval sur minuit, bornes incluses/exclues) — 7/7 corrects ; toggle cliqué dans
#   le vrai navigateur (Playwright) → persisté côté backend, vérifié par lecture API ;
#   remis à l'état par défaut (désactivé) après le test pour ne pas modifier un réglage réel
#   sans le choix explicite de l'utilisateur.
app = FastAPI(title="Marvin — Assistance Informatique", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8005", "http://127.0.0.1:8005"],
    # Autorise aussi l'accès depuis le réseau local (téléphone) : IP privées en :3000
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# Chat — SSE Streaming
# ══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    messages: list[dict]
    conversationId: str | None = None
    model: str | None = None


@app.post("/api/chat")
async def chat(req: ChatRequest):
    async def event_stream():
        async for chunk in run_agent(req.messages, req.conversationId, req.model):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# Exécution manuelle d'un outil (confirmation utilisateur)
# ══════════════════════════════════════════════════════════════════════════════

class ToolExecuteRequest(BaseModel):
    toolName: str
    args: dict = Field(default_factory=dict)


@app.post("/api/tools")
async def execute_tool_endpoint(req: ToolExecuteRequest):
    executor = tool_module.TOOLS_REGISTRY.get(req.toolName)
    if not executor:
        raise HTTPException(status_code=404, detail=f"Outil « {req.toolName} » introuvable")

    # ── Vérification du niveau de permission ─────────────────────────────────
    try:
        perm_raw = db.get_setting("permission_level")
        permission_level = int(perm_raw) if perm_raw is not None else DEFAULT_PERMISSION_LEVEL
    except Exception:
        permission_level = DEFAULT_PERMISSION_LEVEL

    if permission_level == PERMISSION_SECURE and req.toolName in SECURE_BLOCKED_TOOLS:
        return {
            "result": {
                "error": (
                    f"🛡️ Permission refusée (niveau Sécurisé) : "
                    f"l'outil '{req.toolName}' n'est pas autorisé dans ce mode. "
                    f"Passez en mode Standard ou Expert dans Paramètres > Permissions."
                )
            }
        }

    args = dict(req.args)
    # Niveau Expert ou confirmation manuelle → auto-confirm
    if req.toolName in DANGEROUS_TOOLS:
        args["confirmed"] = True
    if permission_level == PERMISSION_EXPERT:
        args["confirmed"] = True

    import time as _time
    t0 = _time.monotonic()
    try:
        result = await executor(args)
        duration_ms = int((_time.monotonic() - t0) * 1000)
        try:
            db.log_execution(req.toolName, req.args, result, duration_ms)
        except Exception:
            pass
        try:
            import audit
            audit.log_action(req.toolName, req.args, result, source="ui")
        except Exception:
            pass
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tools/list")
async def list_tools_endpoint():
    """Catalogue complet des outils (nom/description/schéma) — audit + découverte
    externe (ex : le serveur MCP de Marvin, backend/mcp_server.py, lit ce catalogue
    sans jamais importer tools.py/database.py directement, pour ne pas risquer un
    conflit de verrou Qdrant mono-process)."""
    return {
        "tools": tool_module.TOOLS_SPEC,
        "count": len(tool_module.TOOLS_SPEC),
        "registry_synced": len(tool_module.TOOLS_REGISTRY) == len(tool_module.TOOLS_SPEC),
    }


@app.post("/api/mcp/execute")
async def execute_tool_mcp(req: ToolExecuteRequest):
    """
    Exécution d'outil pour des appelants EXTERNES (serveur MCP de Marvin →
    Claude Desktop, Cursor, etc.) — délibérément SÉPARÉE de /api/tools.

    Différence clé de sécurité : /api/tools force `confirmed=true` sur tout outil
    DANGEREUX, car c'est la page Outils qui a déjà demandé confirmation via son
    propre bouton/dialogue AVANT d'appeler cet endpoint. Un appelant MCP n'a rien
    demandé — le forcer aveuglément permettrait à un client MCP externe de
    déclencher des actions destructrices sans confirmation.

    Ici, seul le niveau de permission ACTUEL de Marvin (Sécurisé/Standard/Expert,
    réglé dans Paramètres) décide : en Expert, confirmation automatique (comme le
    reste de Marvin) ; sinon, l'outil renvoie normalement `requiresConfirmation`
    et c'est au client MCP (donc à l'utilisateur, côté Claude Desktop/Cursor) de
    rappeler avec confirmed=true s'il approuve. `security.screen_command()` reste
    de toute façon actif à l'intérieur de chaque outil (défense en profondeur).
    """
    executor = tool_module.TOOLS_REGISTRY.get(req.toolName)
    if not executor:
        raise HTTPException(status_code=404, detail=f"Outil « {req.toolName} » introuvable")

    try:
        perm_raw = db.get_setting("permission_level")
        permission_level = int(perm_raw) if perm_raw is not None else DEFAULT_PERMISSION_LEVEL
    except Exception:
        permission_level = DEFAULT_PERMISSION_LEVEL

    if permission_level == PERMISSION_SECURE and req.toolName in SECURE_BLOCKED_TOOLS:
        return {"result": {
            "error": (
                f"🛡️ Permission refusée (niveau Sécurisé) : l'outil '{req.toolName}' "
                f"n'est pas autorisé dans ce mode. Passez en mode Standard ou Expert "
                f"dans Marvin > Paramètres > Permissions."
            )
        }}

    args = dict(req.args)
    if permission_level == PERMISSION_EXPERT:
        args["confirmed"] = True
    # PAS de force-confirm en Standard/Sécurisé — voir docstring.

    import time as _time
    t0 = _time.monotonic()
    try:
        result = await executor(args)
        duration_ms = int((_time.monotonic() - t0) * 1000)
        try:
            db.log_execution(req.toolName, req.args, result, duration_ms)
        except Exception:
            pass
        try:
            import audit
            audit.log_action(req.toolName, req.args, result, source="mcp")
        except Exception:
            pass
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mcp/config")
async def mcp_config():
    """
    Config MCP prête à copier, avec les chemins RÉELS de CETTE installation
    (jamais codés en dur) : `sys.executable` pointe toujours vers le python.exe
    du venv réellement utilisé par ce backend, où que Marvin soit installé.
    Sert la page /mcp (guide de connexion) — voir aussi CLAUDE.md §6.
    """
    import sys
    python_exe = sys.executable
    server_script = str((BACKEND_DIR / "mcp_server.py").resolve())

    try:
        perm_raw = db.get_setting("permission_level")
        permission_level = int(perm_raw) if perm_raw is not None else DEFAULT_PERMISSION_LEVEL
    except Exception:
        permission_level = DEFAULT_PERMISSION_LEVEL

    perm_labels = {
        PERMISSION_SECURE:   {"label": "Sécurisé",  "note": "Les outils dangereux sont bloqués pour les appelants MCP."},
        PERMISSION_STANDARD: {"label": "Standard",  "note": "Les outils dangereux renvoient une demande de confirmation — le client MCP doit rappeler avec confirmed=true si son utilisateur approuve."},
        PERMISSION_EXPERT:   {"label": "Expert",    "note": "⚠️ Les outils dangereux s'exécutent SANS confirmation, y compris via MCP — comme le reste de Marvin en ce mode."},
    }

    config_snippet = {
        "mcpServers": {
            "marvin": {
                "command": python_exe,
                "args": [server_script],
            }
        }
    }
    import json as _json

    return {
        "python_executable": python_exe,
        "server_script": server_script,
        "permission_level": permission_level,
        "permission_info": perm_labels.get(permission_level, perm_labels[PERMISSION_STANDARD]),
        "config_json": _json.dumps(config_snippet, indent=2, ensure_ascii=False),
        "tools_count": len(tool_module.TOOLS_SPEC),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Conversations
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/conversations")
async def list_conversations(limit: int = 50, offset: int = 0):
    return db.list_conversations(limit, offset)


@app.get("/api/conversations/{cid}")
async def get_conversation(cid: str):
    conv = db.get_conversation(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation introuvable")
    messages_raw = db.get_messages_by_conversation(cid)

    # Construire les messages au format frontend (parts + toolInvocations)
    formatted = []
    for msg in messages_raw:
        if msg["role"] == "tool":
            # Fusionner les résultats d'outils dans le dernier message assistant
            last_asst = next((m for m in reversed(formatted) if m["role"] == "assistant"), None)
            if last_asst:
                try:
                    results = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
                    if isinstance(results, list):
                        for r in results:
                            for inv in last_asst.get("toolInvocations", []):
                                if inv.get("toolCallId") == r.get("toolCallId"):
                                    inv["state"] = "result"
                                    inv["result"] = r.get("result")
                            for part in last_asst.get("parts", []):
                                if (part.get("type") == "tool-invocation"
                                        and part.get("toolInvocation", {}).get("toolCallId") == r.get("toolCallId")):
                                    part["toolInvocation"]["state"] = "result"
                                    part["toolInvocation"]["result"] = r.get("result")
                except Exception:
                    pass
            continue

        parts: list = []
        if msg.get("content"):
            parts.append({"type": "text", "text": msg["content"]})

        invocations = []
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                inv = {
                    "state": "call",
                    "toolCallId": tc.get("toolCallId", ""),
                    "toolName": tc.get("toolName", ""),
                    "args": tc.get("args", {}),
                }
                parts.append({"type": "tool-invocation", "toolInvocation": inv})
                invocations.append(inv)

        formatted.append({
            "id": msg["id"],
            "role": msg["role"],
            "content": msg.get("content", ""),
            "parts": parts,
            "toolInvocations": invocations,
        })

    return {"conversation": conv, "messages": formatted}


@app.delete("/api/conversations/{cid}")
async def delete_conversation(cid: str):
    db.delete_conversation(cid)
    return {"success": True}


class ConversationUpdate(BaseModel):
    title: str | None = None
    projectId: str | None = None


@app.put("/api/conversations/{cid}")
async def update_conversation(cid: str, body: ConversationUpdate):
    # exclude_unset (pas `is not None`) : désassigner un projet envoie
    # explicitement projectId=null, qu'il faut distinguer de "champ absent".
    fields = body.model_dump(exclude_unset=True)
    if "title" in fields and fields["title"] is not None:
        db.update_conversation_title(cid, fields["title"])
    if "projectId" in fields:
        db.update_conversation_project(cid, fields["projectId"])
    return {"success": True}


@app.get("/api/projects")
async def list_projects():
    return db.get_projects()


class ProjectCreate(BaseModel):
    name: str
    instructions: str | None = None


@app.post("/api/projects")
async def create_project(body: ProjectCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Le nom du projet est requis")
    return db.create_project(name, instructions=(body.instructions or None))


class ProjectUpdate(BaseModel):
    name: str | None = None
    instructions: str | None = None


@app.put("/api/projects/{pid}")
async def update_project_route(pid: str, body: ProjectUpdate):
    # v2.142 — « Projects » avec instructions persistantes (équivalent Claude/ChatGPT
    # Projects), injectées automatiquement dans le prompt système de toute conversation
    # rattachée au projet (agent.py::run_agent). Jusqu'ici un projet n'était qu'un nom.
    updated = db.update_project(pid, name=body.name, instructions=body.instructions)
    if not updated:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return updated


@app.delete("/api/projects/{pid}")
async def delete_project(pid: str):
    db.delete_project(pid)
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# Tâches
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/tasks")
async def list_tasks(status: str | None = None, priority: str | None = None):
    return db.list_tasks(status=status, priority=priority)


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    due_date: str | None = None
    tags: list[str] = []


@app.post("/api/tasks")
async def create_task(body: TaskCreate):
    task = db.create_task(
        title=body.title,
        description=body.description,
        priority=body.priority,
        due_date=body.due_date,
        tags=body.tags,
    )
    return task


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date: str | None = None
    tags: list[str] | None = None


@app.put("/api/tasks/{tid}")
async def update_task(tid: str, body: TaskUpdate):
    task = db.update_task(tid, body.model_dump(exclude_none=True))
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return task


@app.delete("/api/tasks/{tid}")
async def delete_task(tid: str):
    db.delete_task(tid)
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# Notes
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/notes")
async def list_notes(search: str | None = None, pinned: bool | None = None):
    return db.list_notes(search=search, pinned=pinned)


class NoteCreate(BaseModel):
    title: str
    content: str = ""
    tags: list[str] = []
    pinned: bool = False


@app.post("/api/notes")
async def create_note(body: NoteCreate):
    note = db.create_note(body.title, body.content, body.tags, body.pinned)
    return note


class NoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None


@app.put("/api/notes/{nid}")
async def update_note(nid: str, body: NoteUpdate):
    note = db.update_note(nid, body.model_dump(exclude_none=True))
    if not note:
        raise HTTPException(status_code=404, detail="Note introuvable")
    return note


@app.delete("/api/notes/{nid}")
async def delete_note(nid: str):
    db.delete_note(nid)
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# Mémoires
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/memories")
async def list_memories():
    return db.get_memories()


class MemoryCreate(BaseModel):
    content: str
    category: str = "fact"


@app.post("/api/memories")
async def create_memory(body: MemoryCreate):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content requis")
    return db.create_memory(body.content, body.category)


@app.delete("/api/memories")
async def clear_memories():
    db.clear_all_memories()
    return {"success": True}


@app.delete("/api/memories/{mid}")
async def delete_memory(mid: str):
    db.delete_memory(mid)
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# Paramètres
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/settings/{key}")
async def get_setting(key: str):
    return {"key": key, "value": db.get_setting(key)}


@app.put("/api/settings/{key}")
async def set_setting(key: str, request: Request):
    body = await request.json()
    value = body.get("value")
    db.set_setting(key, value)
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# Sauvegardes (data/secretary.db) — v2.111
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/backups")
async def list_backups():
    import backup as _backup
    return _backup.list_backups()


@app.post("/api/backups")
async def create_backup_now():
    import backup as _backup
    r = await _asyncio.to_thread(_backup.create_backup)
    if r.get("error"):
        raise HTTPException(status_code=500, detail=r["error"])
    return r


class RestoreRequest(BaseModel):
    filename: str
    confirmed: bool = False


@app.post("/api/backups/restore")
async def restore_backup_now(body: RestoreRequest):
    # Écrase toutes les données actuelles par celles de la sauvegarde — irréversible sans
    # la sauvegarde de sécurité auto-créée par restore_backup() elle-même. Confirmation
    # explicite obligatoire (même esprit que DANGEROUS_TOOLS, mais route dédiée hors du
    # registre d'outils : ce n'est pas une action pilotable par le LLM depuis le chat).
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Confirmation requise (confirmed=true).")
    import backup as _backup
    r = await _asyncio.to_thread(_backup.restore_backup, body.filename)
    if r.get("error"):
        raise HTTPException(status_code=500, detail=r["error"])
    return r


@app.get("/api/memories/consolidate/preview")
async def preview_memory_consolidation():
    """Aperçu des fusions de souvenirs proposées, sans rien supprimer (dry_run)."""
    import memory_consolidation as _memconsol
    return _memconsol.consolidate_memories(dry_run=True)


@app.post("/api/memories/consolidate")
async def run_memory_consolidation():
    """Déclenche la consolidation immédiatement (fusionne les doublons trouvés)."""
    import memory_consolidation as _memconsol
    return _memconsol.consolidate_memories(dry_run=False)


# ══════════════════════════════════════════════════════════════════════════════
# Recherche sémantique
# ══════════════════════════════════════════════════════════════════════════════

class SearchRequest(BaseModel):
    query: str
    collections: list[str] | None = None
    limit: int = 5


@app.post("/api/search")
async def semantic_search(req: SearchRequest):
    from vector_store import search
    results = await search(req.query, req.collections, req.limit)
    return {"query": req.query, "count": len(results), "results": results}


# ══════════════════════════════════════════════════════════════════════════════
# Santé
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/system/paths")
async def system_paths():
    """Retourne les chemins réels du PC courant (home, bureau, documents, téléchargements)."""
    import os
    from pathlib import Path as P
    home = os.path.expanduser("~")
    return {
        "home": home,
        "desktop": str(P(home) / "Desktop"),
        "documents": str(P(home) / "Documents"),
        "downloads": str(P(home) / "Downloads"),
        "pictures": str(P(home) / "Pictures"),
        "username": os.path.basename(home),
    }


@app.get("/api/system/search")
async def system_search_endpoint(query: str = "", file_type: str = "", max_results: int = 30):
    """Recherche par NOM sur tout le PC (index Windows Search)."""
    return await tool_module.TOOLS_REGISTRY["system_search"](
        {"query": query, "file_type": file_type, "max_results": max_results})


@app.get("/api/system/search-content")
async def system_search_content_endpoint(query: str = "", file_type: str = "", max_results: int = 25):
    """Recherche par CONTENU sur tout le PC (index plein-texte Windows Search)."""
    return await tool_module.TOOLS_REGISTRY["system_search_content"](
        {"query": query, "file_type": file_type, "max_results": max_results})


# ── Aperçu & lecture de fichiers (visionneuse intégrée à Marvin) ─────────────────────
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".avif"}
_TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".xml", ".yaml",
              ".yml", ".ini", ".cfg", ".conf", ".env", ".py", ".js", ".ts", ".jsx", ".tsx",
              ".html", ".htm", ".css", ".scss", ".sh", ".bat", ".ps1", ".sql", ".rs", ".go",
              ".java", ".c", ".cpp", ".h", ".rst", ".toml"}


@app.get("/api/files/raw")
async def file_raw(path: str):
    """Sert le contenu BRUT d'un fichier (image, PDF…) pour l'afficher dans Marvin."""
    import os as _os, mimetypes
    p = _os.path.abspath(path)
    if not _os.path.isfile(p):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    mt = mimetypes.guess_type(p)[0] or "application/octet-stream"
    return FileResponse(p, media_type=mt, filename=_os.path.basename(p))


@app.get("/api/files/preview")
async def file_preview(path: str):
    """Aperçu d'un fichier pour la visionneuse : image / pdf / texte extrait / binaire."""
    import os as _os
    p = _os.path.abspath(path)
    if not _os.path.isfile(p):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    ext = _os.path.splitext(p)[1].lower()
    info = {"name": _os.path.basename(p), "size": _os.path.getsize(p), "ext": ext, "path": p}
    if ext in _IMG_EXTS:
        return {**info, "kind": "image"}
    if ext == ".pdf":
        return {**info, "kind": "pdf"}
    if ext == ".docx":
        try:
            r = await tool_module.TOOLS_REGISTRY["docx_to_text"]({"path": p, "format": "markdown"})
            return {**info, "kind": "text", "lang": "markdown",
                    "content": (r.get("text") or r.get("content") or r.get("markdown") or "")[:200000]}
        except Exception as e:
            return {**info, "kind": "binary", "error": str(e)[:120]}
    if ext in (".xlsx", ".xls"):
        try:
            r = await tool_module.TOOLS_REGISTRY["xlsx_read"]({"path": p})
            return {**info, "kind": "table", "data": r}
        except Exception:
            return {**info, "kind": "binary"}
    if ext in _TEXT_EXTS:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                content = f.read(300000)
            return {**info, "kind": "text", "lang": ext.lstrip("."), "content": content}
        except Exception as e:
            return {**info, "kind": "binary", "error": str(e)[:120]}
    return {**info, "kind": "binary"}


@app.post("/api/chat/attach")
async def chat_attach(file: UploadFile = File(...)):
    """Joindre un document au chat : sauvegarde + extrait le TEXTE pour que Marvin le lise."""
    import os as _os
    up_dir = _os.path.join(_os.path.dirname(tool_module.__file__), "..", "data", "chat_uploads")
    _os.makedirs(up_dir, exist_ok=True)
    name = _os.path.basename(file.filename or "fichier")
    dest = _os.path.join(up_dir, name)
    with open(dest, "wb") as f:
        f.write(await file.read())
    ext = _os.path.splitext(name)[1].lower()
    content = ""
    try:
        if ext == ".pdf":
            r = await tool_module.TOOLS_REGISTRY["pdf_read"]({"path": dest})
            content = r.get("text") or r.get("content") or ""
        elif ext == ".docx":
            r = await tool_module.TOOLS_REGISTRY["docx_to_text"]({"path": dest, "format": "markdown"})
            content = r.get("text") or r.get("content") or r.get("markdown") or ""
        elif ext == ".pptx":
            r = await tool_module.TOOLS_REGISTRY["pptx_read"]({"path": dest})
            content = r.get("text") or r.get("content") or ""
        elif ext in (".xlsx", ".xls"):
            r = await tool_module.TOOLS_REGISTRY["xlsx_read"]({"path": dest})
            rows = r.get("data") or []
            heads = r.get("headers") or []
            lines = [" | ".join(str(h) for h in heads)] if heads else []
            for row in (rows[:200] if isinstance(rows, list) else []):
                if isinstance(row, dict):
                    lines.append(" | ".join(str(row.get(h, "")) for h in heads))
                elif isinstance(row, list):
                    lines.append(" | ".join(str(c) for c in row))
            content = "\n".join(lines)
        elif ext in _TEXT_EXTS:
            with open(dest, encoding="utf-8", errors="replace") as f:
                content = f.read(40000)
        else:
            return {"success": True, "name": name, "kind": "binary", "content": "", "chars": 0,
                    "message": "Type non lisible directement — joins un PDF, Word, Excel, PowerPoint ou texte."}
    except Exception as e:
        return {"success": False, "error": f"Lecture impossible : {str(e)[:160]}"}
    full = len(content or "")
    excerpt = (content or "")[:12000]
    return {"success": True, "name": name, "path": dest, "kind": "text",
            "content": excerpt, "chars": full, "truncated": full > len(excerpt)}


@app.get("/api/search/unified")
async def unified_search_endpoint(query: str = "", scope: str = "", limit: int = 5):
    """Recherche unifiée (tout à la fois). scope = liste de sources séparées par des virgules, ou 'all'."""
    sc = [s.strip() for s in scope.split(",") if s.strip()] if scope else None
    args = {"query": query, "limit": limit}
    if sc:
        args["scope"] = sc
    return await tool_module.TOOLS_REGISTRY["unified_search"](args)


# ══════════════════════════════════════════════════════════════════════════════
# Screenshot — retourne PNG base64 directement dans la web UI
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/screenshot")
async def take_screenshot():
    """Prend une capture d'écran et retourne l'image en base64."""
    try:
        from PIL import ImageGrab
        import io
        screenshot = ImageGrab.grab()
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return {"success": True, "image": f"data:image/png;base64,{b64}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Upload image pour le chat
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """Reçoit une image et retourne son contenu base64 + type MIME."""
    try:
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        if file.content_type not in allowed:
            raise HTTPException(status_code=400, detail=f"Type de fichier non supporté : {file.content_type}")
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:  # 20 Mo max
            raise HTTPException(status_code=400, detail="Image trop volumineuse (max 20 Mo)")
        b64 = base64.b64encode(data).decode("utf-8")
        return {
            "success": True,
            "filename": file.filename,
            "content_type": file.content_type,
            "size": len(data),
            "data": f"data:{file.content_type};base64,{b64}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Credentials OAuth & API Keys
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/credentials")
async def get_credentials():
    import credentials_manager as cm
    return {"credentials": cm.get_all_credentials(), "groups": cm.get_group_status()}


class CredentialSetRequest(BaseModel):
    value: str


@app.put("/api/credentials/{name}")
async def set_credential(name: str, body: CredentialSetRequest):
    import credentials_manager as cm
    if name not in cm.CREDENTIAL_DEFINITIONS:
        raise HTTPException(status_code=404, detail=f"Credential inconnu : {name}")
    cm.set_credential(name, body.value)
    return {"success": True}


@app.delete("/api/credentials/{name}")
async def delete_credential(name: str):
    import credentials_manager as cm
    cm.delete_credential(name)
    return {"success": True}


# ── Google OAuth flow ─────────────────────────────────────────────────────────

@app.get("/api/oauth/google/start")
async def google_oauth_start():
    """Génère l'URL d'autorisation Google OAuth2."""
    import credentials_manager as cm
    from google_auth_oauthlib.flow import Flow

    client_id = cm.get_credential("google_client_id")
    client_secret = cm.get_credential("google_client_secret")
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Client ID et Client Secret Google requis")

    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [_GOOGLE_CALLBACK],
            }
        },
        scopes=_GOOGLE_SCOPES,
    )
    flow.redirect_uri = _GOOGLE_CALLBACK
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return {"auth_url": auth_url}


@app.get("/api/oauth/google/connect")
async def google_oauth_connect():
    """Redirige DIRECTEMENT vers l'écran de consentement Google (1 seul lien à ouvrir)."""
    from fastapi.responses import RedirectResponse
    res = await google_oauth_start()
    if isinstance(res, dict) and res.get("auth_url"):
        return RedirectResponse(url=res["auth_url"])
    raise HTTPException(status_code=400, detail="Impossible de générer l'URL d'autorisation Google.")


@app.get("/api/oauth/google/callback")
async def google_oauth_callback(code: str, request: Request):
    """Reçoit le callback OAuth Google et stocke les tokens."""
    import credentials_manager as cm
    from google_auth_oauthlib.flow import Flow

    client_id = cm.get_credential("google_client_id")
    client_secret = cm.get_credential("google_client_secret")

    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [_GOOGLE_CALLBACK],
            }
        },
        scopes=_GOOGLE_SCOPES,
    )
    flow.redirect_uri = _GOOGLE_CALLBACK
    flow.fetch_token(code=code)
    creds = flow.credentials
    cm.set_credential("google_access_token", creds.token)
    if creds.refresh_token:
        cm.set_credential("google_refresh_token", creds.refresh_token)
    # Rediriger vers l'UI
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="http://localhost:3000/settings?tab=connections&google=connected")


@app.get("/api/oauth/google/status")
async def google_oauth_status():
    """État RÉEL de la connexion Google (compte de service OU OAuth) avec test live."""
    import credentials_manager as cm
    sa_email = tool_module._google_sa_email()
    cal_id = db.get_setting("google_calendar_id")
    mode = "service_account" if sa_email else "oauth"
    connected, email, error, count = False, None, None, None

    if sa_email:
        # Mode compte de service : on teste l'accès à l'agenda PARTAGÉ (google_calendar_id)
        if not cal_id:
            error = "Clé de service OK, mais l'agenda cible n'est pas défini (ton email)."
        else:
            try:
                svc = tool_module._get_google_calendar_service()
                res = svc.events().list(calendarId=cal_id, maxResults=1).execute()
                email = cal_id
                count = len(res.get("items", []))
                connected = True
            except Exception as e:
                error = str(e)[:200]
        return {"mode": mode, "has_keys": True, "connected": connected, "email": email,
                "sa_email": sa_email, "calendar_id": cal_id, "sample_count": count, "error": error,
                "next_step": (None if connected else (
                    "Définis l'agenda cible (ton email) : POST /api/google/calendar-id." if not cal_id else
                    f"Partage ton Google Agenda avec {sa_email} (droit « Modifier les événements »).") )}

    # Mode OAuth utilisateur
    has_keys = bool(cm.get_credential("google_client_id") and cm.get_credential("google_client_secret"))
    access = cm.get_credential("google_access_token")
    refresh = cm.get_credential("google_refresh_token")
    source = "backend"
    if not access and not refresh:
        try:
            row = db.get_conn().execute("SELECT access_token, refresh_token FROM oauth_tokens WHERE provider='google'").fetchone()
            if row and row["access_token"]:
                access, refresh, source = row["access_token"], row["refresh_token"], "frontend"
        except Exception:
            pass
    has_tokens = bool(access or refresh)
    if has_tokens:
        try:
            svc = tool_module._get_google_calendar_service()
            cal = svc.calendarList().get(calendarId="primary").execute()
            email = cal.get("id")
            connected = True
        except Exception as e:
            error = str(e)[:160]
    return {"mode": mode, "has_keys": has_keys, "has_tokens": has_tokens, "connected": connected,
            "has_refresh": bool(refresh), "email": email, "source": source if has_tokens else None,
            "callback_uri": _GOOGLE_CALLBACK, "error": error,
            "next_step": (None if connected else
                          ("Termine l'autorisation : ouvre /api/oauth/google/connect." if has_keys
                           else "Renseigne Client ID et Secret, ou utilise un compte de service."))}


@app.post("/api/oauth/google/service-account")
async def upload_google_service_account(file: UploadFile = File(...)):
    """Reçoit la clé JSON d'un compte de service Google (agenda permanent, sans expiration)."""
    import json as _json, os as _os
    raw = await file.read()
    try:
        data = _json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Fichier JSON invalide.")
    if data.get("type") != "service_account" or not data.get("client_email"):
        raise HTTPException(status_code=400, detail="Ce n'est pas une clé de compte de service Google valide.")
    _os.makedirs(_os.path.dirname(tool_module._GOOGLE_SA_PATH), exist_ok=True)
    with open(tool_module._GOOGLE_SA_PATH, "wb") as f:
        f.write(raw)
    return {"success": True, "client_email": data["client_email"],
            "share_hint": f"Partage maintenant ton Google Agenda avec {data['client_email']} (droit « Modifier les événements »), puis définis ton email comme agenda cible."}


@app.delete("/api/oauth/google/service-account")
async def delete_google_service_account():
    import os as _os
    try: _os.remove(tool_module._GOOGLE_SA_PATH)
    except Exception: pass
    return {"success": True}


class CalendarIdBody(BaseModel):
    calendar_id: str


@app.post("/api/google/calendar-id")
async def set_google_calendar_id(body: CalendarIdBody):
    """Définit l'agenda Google cible (ton adresse email) pour le compte de service."""
    db.set_setting("google_calendar_id", body.calendar_id.strip())
    return {"success": True, "calendar_id": body.calendar_id.strip()}


# ── Microsoft OAuth flow ──────────────────────────────────────────────────────

@app.get("/api/oauth/microsoft/start")
async def microsoft_oauth_start():
    """Génère l'URL d'autorisation Microsoft OAuth2."""
    import credentials_manager as cm
    import urllib.parse

    client_id = cm.get_credential("ms_client_id")
    tenant_id = cm.get_credential("ms_tenant_id") or "common"
    if not client_id:
        raise HTTPException(status_code=400, detail="Client ID Microsoft requis")

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": _MS_CALLBACK,
        "scope": "https://graph.microsoft.com/Files.ReadWrite offline_access",
        "response_mode": "query",
    }
    auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?" + urllib.parse.urlencode(params)
    return {"auth_url": auth_url}


@app.get("/api/oauth/microsoft/callback")
async def microsoft_oauth_callback(code: str, request: Request):
    """Reçoit le callback OAuth Microsoft et stocke les tokens."""
    import credentials_manager as cm
    import httpx

    client_id = cm.get_credential("ms_client_id")
    client_secret = cm.get_credential("ms_client_secret") or ""
    tenant_id = cm.get_credential("ms_tenant_id") or "common"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _MS_CALLBACK,
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/Files.ReadWrite offline_access",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    cm.set_credential("ms_access_token", data["access_token"])
    if "refresh_token" in data:
        cm.set_credential("ms_refresh_token", data["refresh_token"])
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="http://localhost:3000/settings?tab=connections&microsoft=connected")


# ══════════════════════════════════════════════════════════════════════════════
# Historique d'exécution
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/history")
async def list_history(tool_name: str | None = None, limit: int = 50, offset: int = 0):
    return db.list_executions(tool_name=tool_name, limit=limit, offset=offset)


@app.get("/api/history/stats")
async def history_stats():
    return db.get_execution_stats()


@app.get("/api/history/reliability")
async def history_reliability(min_calls: int = 3, days: int = 90):
    """v2.138 — taux d'échec PAR OUTIL (pas juste le volume) : ferme la boucle repérée en
    auditant `calendar_list` (60 échecs invisibles jusqu'à interrogation manuelle de la DB)."""
    return {"tools": db.get_tool_reliability(min_calls=min_calls, days=days)}


# ══════════════════════════════════════════════════════════════════════════════
# Templates d'outils
# ══════════════════════════════════════════════════════════════════════════════

class TemplateCreate(BaseModel):
    name: str
    tool_name: str
    args: dict = Field(default_factory=dict)
    description: str = ""
    category: str = "general"


@app.get("/api/templates")
async def list_templates(tool_name: str | None = None, category: str | None = None):
    return db.list_templates(tool_name=tool_name, category=category)


@app.post("/api/templates")
async def create_template(body: TemplateCreate):
    return db.save_template(body.name, body.tool_name, body.args, body.description, body.category)


@app.delete("/api/templates/{tid}")
async def delete_template(tid: str):
    db.delete_template(tid)
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# Jobs Cron
# ══════════════════════════════════════════════════════════════════════════════

class CronJobCreate(BaseModel):
    name: str
    tool_name: str
    args: dict = Field(default_factory=dict)
    schedule: str  # ex: "every 5 minutes", "daily at 08:00", "hourly"


class CronJobUpdate(BaseModel):
    name: str | None = None
    schedule: str | None = None
    args: dict | None = None
    enabled: bool | None = None


@app.get("/api/cron")
async def list_cron_jobs():
    return db.list_cron_jobs()


@app.post("/api/cron")
async def create_cron_job(body: CronJobCreate):
    job = db.create_cron_job(body.name, body.tool_name, body.args, body.schedule)
    # Calcule la 1ère échéance (sinon le job se déclenche immédiatement)
    db.update_cron_job(job["id"], {"next_run": _next_run_dt(body.schedule)})
    return db.get_cron_job(job["id"])


@app.put("/api/cron/{jid}")
async def update_cron_job(jid: str, body: CronJobUpdate):
    updates = body.model_dump(exclude_none=True)
    # Si le planning change, recalcule la prochaine exécution
    if updates.get("schedule"):
        updates["next_run"] = _next_run_dt(updates["schedule"])
    job = db.update_cron_job(jid, updates)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job


@app.post("/api/cron/preview")
async def cron_preview(body: dict):
    """Prévisualise les prochaines exécutions d'un planning (aide à la saisie)."""
    schedule = body.get("schedule", "")
    now = datetime.now()
    cron = _to_cron(schedule)
    runs = []
    if cron:
        try:
            from croniter import croniter
            it = croniter(cron, now)
            runs = [it.get_next(datetime).strftime("%a %d/%m %H:%M") for _ in range(5)]
        except Exception:
            pass
    if not runs:
        secs = _parse_schedule_seconds(schedule)
        runs = [(now + timedelta(seconds=secs * (i + 1))).strftime("%a %d/%m %H:%M") for i in range(5)]
    return {"schedule": schedule, "cron": cron, "next_runs": runs}


@app.delete("/api/cron/{jid}")
async def delete_cron_job(jid: str):
    db.delete_cron_job(jid)
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# Monitoring Live (SSE) — CPU, RAM, Disques
# ══════════════════════════════════════════════════════════════════════════════

import asyncio as _asyncio
import psutil as _psutil


@app.get("/api/monitor")
async def monitor_stream():
    """SSE : envoie les métriques système toutes les 2 secondes."""

    async def generate():
        while True:
            try:
                cpu = _psutil.cpu_percent(interval=None)
                mem = _psutil.virtual_memory()
                disks = []
                for part in _psutil.disk_partitions(all=False):
                    try:
                        usage = _psutil.disk_usage(part.mountpoint)
                        disks.append({
                            "device": part.device,
                            "mountpoint": part.mountpoint,
                            "total_gb": round(usage.total / 1024 ** 3, 1),
                            "used_gb": round(usage.used / 1024 ** 3, 1),
                            "free_gb": round(usage.free / 1024 ** 3, 1),
                            "percent": usage.percent,
                        })
                    except Exception:
                        pass
                net = _psutil.net_io_counters()
                # v2.116 — Top processus (CPU/RAM) : rend le monitoring ACTIONNABLE au lieu
                # de juste afficher des jauges — on voit immédiatement QUI consomme, avec un
                # bouton pour le terminer directement depuis la page (cf. pc_process_kill).
                top_processes = []
                try:
                    procs = []
                    for p in _psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                        try:
                            info = p.info
                            procs.append({
                                "pid": info["pid"],
                                "name": info["name"] or "?",
                                "cpu_percent": round(info["cpu_percent"] or 0.0, 1),
                                "memory_mb": round((info["memory_info"].rss if info["memory_info"] else 0) / 1024 ** 2, 1),
                            })
                        except (_psutil.NoSuchProcess, _psutil.AccessDenied):
                            pass
                    procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
                    top_processes = procs[:8]
                except Exception:
                    pass
                # v2.116 — GPU : get_device_info() a déjà un TTL de 20s (local_video.py), donc
                # l'appeler chaque cycle (2s) ne redétecte réellement que toutes les 10 itérations.
                gpu = None
                try:
                    import local_video as _lv
                    info = _lv.get_device_info()
                    gpu = {
                        "name": info.get("device_name") or info.get("name"),
                        "vram_gb": info.get("vram_gb"),
                        "backend": info.get("backend"),
                        "vendor": info.get("vendor"),
                    }
                except Exception:
                    pass
                payload = {
                    "cpu_percent": cpu,
                    "cpu_count": _psutil.cpu_count(),
                    "ram_total_gb": round(mem.total / 1024 ** 3, 1),
                    "ram_used_gb": round(mem.used / 1024 ** 3, 1),
                    "ram_percent": mem.percent,
                    "disks": disks,
                    "net_sent_mb": round(net.bytes_sent / 1024 ** 2, 1),
                    "net_recv_mb": round(net.bytes_recv / 1024 ** 2, 1),
                    "top_processes": top_processes,
                    "gpu": gpu,
                }
                # Batterie (laptop uniquement)
                try:
                    bat = _psutil.sensors_battery()
                    if bat is not None:
                        payload["battery"] = {
                            "percent": round(bat.percent, 1),
                            "plugged": bat.power_plugged,
                        }
                except Exception:
                    pass
                yield f"data: {json.dumps(payload)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await _asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# SSH Manager
# ══════════════════════════════════════════════════════════════════════════════

import io
import security as _security

class SSHConnectionCreate(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str
    password: str = ""
    private_key: str = ""       # contenu PEM de la clé privée (RSA/Ed25519/ECDSA/DSS)
    key_passphrase: str = ""    # v2.117 — passphrase optionnelle si la clé est chiffrée
    connection_id: str = ""     # optionnel, utilisé uniquement par /api/ssh/test pour persister le résultat


class SSHConnectionUpdate(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str
    password: str = ""          # vide = conserver le secret existant (cf. db.update_ssh_connection)
    private_key: str = ""
    key_passphrase: str = ""


class SSHCommandRequest(BaseModel):
    connection_id: str
    command: str
    timeout: int = 30


@app.get("/api/ssh")
async def list_ssh():
    return db.list_ssh_connections()


@app.post("/api/ssh")
async def create_ssh(body: SSHConnectionCreate):
    return db.save_ssh_connection(body.name, body.host, body.port, body.username,
                                   body.password, body.private_key, body.key_passphrase)


@app.put("/api/ssh/{sid}")
async def edit_ssh(sid: str, body: SSHConnectionUpdate):
    """v2.117 — édition d'une connexion existante (jusqu'ici seuls add/delete existaient,
    corriger un simple typo dans l'hôte obligeait à tout ressaisir)."""
    if not db.get_ssh_connection(sid):
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    updated = db.update_ssh_connection(sid, **body.model_dump())
    return updated


@app.delete("/api/ssh/{sid}")
async def delete_ssh(sid: str):
    db.delete_ssh_connection(sid)
    return {"success": True}


# v2.117 — les 3 endpoints ci-dessous réimplémentaient CHACUN leur propre connexion paramiko
# en dur (RSA uniquement via `paramiko.RSAKey.from_private_key`, une clé Ed25519/ECDSA —
# le défaut de `ssh-keygen` depuis des années — échouait silencieusement) ET ne passaient
# JAMAIS par `security.screen_command()`, alors que CLAUDE.md §6 est explicite : « toute
# commande shell/PowerShell/SSH passe par screen_command() AVANT exécution ». Le terminal SSH
# de la page web (celui qu'un humain tape à la main) était donc le SEUL chemin d'exécution de
# commandes de tout Marvin à ne PAS avoir le garde-fou anti-catastrophe — la version pilotée
# par le chat (tools.py::execute_ssh_exec) l'avait déjà. Corrigé en délégant à
# `tool_module._ssh_connect`/`_ssh_load_key` (déjà multi-format) et en ajoutant le guard ici.
@app.post("/api/ssh/test")
async def test_ssh(body: SSHConnectionCreate):
    """Teste la connectivité SSH. Si `connection_id` est fourni et qu'aucun secret n'est
    saisi dans le formulaire, réutilise le mot de passe/clé déjà en base (permet de tester
    une connexion sauvegardée sans ressaisir le secret — bouton 🧪 de la sidebar)."""
    password, private_key, key_passphrase = body.password, body.private_key, body.key_passphrase
    if body.connection_id and not password and not private_key:
        saved = db.get_ssh_connection(body.connection_id)
        if saved:
            password = saved.get("password") or ""
            private_key = saved.get("private_key") or ""
            key_passphrase = saved.get("key_passphrase") or ""

    def _run():
        client = tool_module._ssh_connect(dict(
            host=body.host, port=body.port, username=body.username,
            password=password, private_key=private_key,
            key_passphrase=key_passphrase,
        ), timeout=8)
        _, stdout, _ = client.exec_command("uname -a || ver", timeout=5)
        info = stdout.read().decode(errors="replace").strip()
        client.close()
        return info
    try:
        info = await _asyncio.get_running_loop().run_in_executor(None, _run)
        if body.connection_id:
            db.set_ssh_test_result(body.connection_id, True)
        return {"success": True, "info": info}
    except Exception as e:
        if body.connection_id:
            db.set_ssh_test_result(body.connection_id, False)
        return {"success": False, "error": str(e)}


@app.post("/api/ssh/exec")
async def exec_ssh(body: SSHCommandRequest):
    """Exécute une commande SSH et retourne stdout+stderr."""
    conn = db.get_ssh_connection(body.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")

    blocked = _security.guard_result(body.command)
    if blocked:
        return {"stdout": "", "stderr": blocked.get("error", "Commande bloquée."), "exit_code": -1, "command": body.command}

    def _run():
        client = tool_module._ssh_connect(conn, timeout=body.timeout)
        _, stdout, stderr = client.exec_command(body.command, timeout=body.timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        client.close()
        return {"stdout": out, "stderr": err, "exit_code": exit_code, "command": body.command}

    try:
        result = await _asyncio.get_running_loop().run_in_executor(None, _run)
        db.touch_ssh_connection(body.connection_id)
        try:
            db.log_execution("ssh_exec", {"connection_id": body.connection_id, "command": body.command}, result, 0)
        except Exception:
            pass
        return result
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1, "command": body.command}


@app.get("/api/ssh/exec/stream")
async def exec_ssh_stream(connection_id: str, command: str):
    """Exécute une commande SSH en streaming SSE (ligne par ligne)."""
    conn = db.get_ssh_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")

    blocked = _security.guard_result(command)

    async def generate():
        if blocked:
            yield f"data: {json.dumps({'type':'error','message':blocked.get('error','Commande bloquée.')})}\n\n"
            return
        try:
            client = await _asyncio.get_running_loop().run_in_executor(None, tool_module._ssh_connect, conn, 30)
            _, stdout, stderr = client.exec_command(command, timeout=60)

            while True:
                line = await _asyncio.get_running_loop().run_in_executor(None, stdout.readline)
                if not line:
                    break
                yield f"data: {json.dumps({'type':'stdout','line':line.rstrip()})}\n\n"

            err = await _asyncio.get_running_loop().run_in_executor(None, stderr.read)
            if err:
                yield f"data: {json.dumps({'type':'stderr','line':err.decode(errors='replace').strip()})}\n\n"

            exit_code = stdout.channel.recv_exit_status()
            yield f"data: {json.dumps({'type':'done','exit_code':exit_code})}\n\n"
            db.touch_ssh_connection(connection_id)
            client.close()
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# v2.118 — Terminal interactif RÉEL (PTY), demandé explicitement (« je veux voir le
# terminal comme si j'y étais, peu importe Windows ou Linux »). `exec_ssh_stream`
# ci-dessus exécute une commande complète et attend sa fin — pas d'invite interactive,
# pas d'historique shell natif, pas de programmes plein écran (top, vim, moins…).
# Un vrai shell interactif s'ouvre via `paramiko.invoke_shell()` (canal PTY) et transmet
# les octets bruts dans les deux sens en continu — exactement ce que fait un client SSH
# natif (PuTTY, `ssh` en ligne de commande). Le protocole SSH délègue l'allocation du PTY
# au serveur distant : AUCUNE distinction Windows/Linux n'est nécessaire ici, le serveur
# OpenSSH (natif sous Windows 10+ ou sous Linux) gère lui-même le shell qu'il lance
# (cmd.exe/PowerShell ou bash/sh selon sa configuration).
# ⚠️ Contrepartie assumée : un flux d'octets bruts ne peut PAS être filtré par
# `security.screen_command()` sans casser l'interactivité (pas de "commande complète"
# identifiable avant que l'utilisateur appuie sur Entrée côté shell distant — même
# limitation que n'importe quel client SSH classique). Le garde-fou reste entier sur tous
# les chemins d'exécution AUTOMATISÉS de Marvin (chat, exec/stream ci-dessus) — ce canal-ci
# est un clavier direct tenu par un humain déjà authentifié sur sa propre connexion SSH
# sauvegardée, équivalent à ouvrir PuTTY.
@app.websocket("/api/ssh/{sid}/shell")
async def ssh_shell_ws(websocket: WebSocket, sid: str):
    await websocket.accept()
    conn = db.get_ssh_connection(sid)
    if not conn:
        await websocket.send_json({"type": "error", "message": "Connexion introuvable."})
        await websocket.close()
        return

    loop = _asyncio.get_running_loop()
    client = None
    channel = None
    try:
        client = await loop.run_in_executor(None, tool_module._ssh_connect, conn, 15)
        channel = await loop.run_in_executor(
            None, lambda: client.invoke_shell(term="xterm-256color", width=80, height=24)
        )
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
        await websocket.close()
        return

    db.touch_ssh_connection(sid)

    def _blocking_recv():
        try:
            return channel.recv(4096)
        except Exception:
            return None

    async def pump_ssh_to_ws():
        try:
            while True:
                data = await loop.run_in_executor(None, _blocking_recv)
                if not data:
                    break
                await websocket.send_json({"type": "data", "data": data.decode(errors="replace")})
        except Exception:
            pass
        try:
            await websocket.send_json({"type": "closed"})
        except Exception:
            pass

    reader_task = _asyncio.create_task(pump_ssh_to_ws())
    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")
            if mtype == "input":
                # channel.send() attend des bytes — un envoi en str compterait la taille de
                # la fenêtre en caractères et non en octets, risquant de tronquer un
                # caractère accentué/multi-octets en UTF-8 au milieu de sa séquence.
                channel.send(msg.get("data", "").encode("utf-8"))
            elif mtype == "resize":
                try:
                    channel.resize_pty(width=int(msg.get("cols", 80)), height=int(msg.get("rows", 24)))
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        reader_task.cancel()
        try: channel.close()
        except Exception: pass
        try: client.close()
        except Exception: pass


# ── v2.117 : navigateur SFTP + diagnostic serveur — la logique existait déjà côté outils
# chat (tools.py::execute_ssh_list_dir/server_info) mais était injoignable depuis la page
# /ssh. Réutilisée directement (lecture seule, aucune confirmation nécessaire). ──────────
@app.get("/api/ssh/{sid}/browse")
async def browse_ssh(sid: str, path: str = "."):
    if not db.get_ssh_connection(sid):
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    return await tool_module.execute_ssh_list_dir({"connection_id": sid, "remote_path": path})


@app.get("/api/ssh/{sid}/info")
async def ssh_server_info(sid: str):
    if not db.get_ssh_connection(sid):
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    return await tool_module.execute_ssh_server_info({"connection_id": sid})


@app.get("/api/ssh/{sid}/download")
async def download_ssh_file(sid: str, path: str):
    """Télécharge un fichier distant DIRECTEMENT dans le navigateur (pas sur le disque de
    Marvin — contrairement à l'outil chat `ssh_download` qui sauvegarde côté serveur)."""
    conn = db.get_ssh_connection(sid)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")

    def _run():
        client = tool_module._ssh_connect(conn, timeout=30)
        sftp = client.open_sftp()
        buf = io.BytesIO()
        sftp.getfo(path, buf)
        sftp.close(); client.close()
        return buf.getvalue()

    try:
        data = await _asyncio.get_running_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    filename = path.rstrip("/").rsplit("/", 1)[-1] or "download"
    return Response(content=data, media_type="application/octet-stream",
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/ssh/{sid}/upload")
async def upload_ssh_file(sid: str, remote_path: str = Form(...), file: UploadFile = File(...)):
    """Envoie un fichier depuis le navigateur vers le serveur distant (SFTP)."""
    conn = db.get_ssh_connection(sid)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    content = await file.read()

    def _run():
        client = tool_module._ssh_connect(conn, timeout=60)
        sftp = client.open_sftp()
        sftp.putfo(io.BytesIO(content), remote_path)
        size = sftp.stat(remote_path).st_size
        sftp.close(); client.close()
        return size

    try:
        size = await _asyncio.get_running_loop().run_in_executor(None, _run)
        db.touch_ssh_connection(sid)
        return {"success": True, "remote_path": remote_path, "size": size}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Email Manager (IMAP + SMTP)
# ══════════════════════════════════════════════════════════════════════════════

import email_manager as _em

def _coerce_json(v):
    if isinstance(v, str):
        try:
            import json as _json
            return _json.loads(v)
        except Exception:
            return None
    return v


def _get_email_accounts() -> list[dict]:
    """Liste des comptes email (multi-comptes). Migre l'ancienne config unique si besoin."""
    accts = _coerce_json(db.get_setting("email_accounts"))
    if not isinstance(accts, list):
        accts = []
    if not accts:
        # Migration depuis l'ancienne config mono-compte 'email_config'
        legacy = _coerce_json(db.get_setting("email_config"))
        if isinstance(legacy, dict) and legacy.get("imap_host"):
            accts = [legacy]
            db.set_setting("email_accounts", accts)
    return [a for a in accts if isinstance(a, dict) and a.get("imap_host")]


def _save_email_accounts(accts: list[dict]) -> None:
    db.set_setting("email_accounts", accts)


def _upsert_email_account(cfg: dict) -> list[dict]:
    """Ajoute ou met à jour un compte (identifié par son username/email)."""
    accts = _get_email_accounts()
    idx = next((i for i, a in enumerate(accts) if a.get("username") == cfg.get("username")), None)
    if idx is not None:
        accts[idx] = cfg
    else:
        accts.append(cfg)
    _save_email_accounts(accts)
    return accts


def _get_email_config(account: str | None = None) -> dict | None:
    """Config d'un compte par username/email. Sans 'account' -> le 1er compte (défaut)."""
    accts = _get_email_accounts()
    if not accts:
        return None
    if account:
        for a in accts:
            if a.get("username") == account:
                return a
        return None
    return accts[0]


class EmailConfig(BaseModel):
    provider: str = "custom"
    imap_host: str
    imap_port: int = 993
    smtp_host: str
    smtp_port: int = 587
    username: str
    password: str


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    cc: str = ""
    reply_to: str = ""
    html_body: str = ""


@app.get("/api/email/providers")
async def email_providers():
    return _em.PROVIDERS


@app.get("/api/email/config")
async def get_email_config(account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        return {"configured": False}
    # Ne pas retourner le mot de passe en clair
    safe = {k: v for k, v in cfg.items() if k != "password"}
    safe["configured"] = True
    safe["password_set"] = bool(cfg.get("password"))
    return safe


@app.post("/api/email/config")
async def set_email_config(body: EmailConfig):
    # Ajoute ou met à jour le compte (multi-comptes) au lieu d'écraser.
    _upsert_email_account(body.model_dump())
    return {"success": True}


# ── Multi-comptes email ───────────────────────────────────────────────────────
@app.get("/api/email/accounts")
async def email_accounts_list():
    """Liste des boîtes mail connectées (sans les mots de passe)."""
    accts = _get_email_accounts()
    return {
        "accounts": [
            {"id": a.get("username"), "username": a.get("username"),
             "provider": a.get("provider", "custom"), "imap_host": a.get("imap_host")}
            for a in accts
        ],
        "default": accts[0].get("username") if accts else None,
        "count": len(accts),
    }


@app.post("/api/email/accounts")
async def email_accounts_add(body: EmailConfig):
    """Ajoute (ou met à jour) une boîte mail sans toucher aux autres."""
    accts = _upsert_email_account(body.model_dump())
    return {"success": True, "id": body.username, "count": len(accts)}


@app.delete("/api/email/accounts/{account_id}")
async def email_accounts_remove(account_id: str):
    """Déconnecte une boîte mail précise."""
    accts = _get_email_accounts()
    remaining = [a for a in accts if a.get("username") != account_id]
    _save_email_accounts(remaining)
    return {"success": True, "removed": len(accts) - len(remaining), "count": len(remaining)}


@app.post("/api/email/test")
async def test_email_config(body: EmailConfig):
    def _test():
        return _em.test_connection(
            body.imap_host, body.imap_port,
            body.smtp_host, body.smtp_port,
            body.username, body.password,
        )
    result = await _asyncio.get_running_loop().run_in_executor(None, _test)
    return result


@app.get("/api/email/inbox")
async def email_inbox(folder: str = "INBOX", limit: int = 30, offset: int = 0, account: str | None = None):
    loop = _asyncio.get_running_loop()
    # ── Boîte UNIFIÉE : agrège toutes les boîtes (account=__all__) ──
    if account == "__all__":
        accts = _get_email_accounts()
        if not accts:
            return {"error": "Email non configuré", "emails": []}

        async def _fetch_one(a):
            try:
                ems = await loop.run_in_executor(None, lambda: _em.fetch_inbox(
                    a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                    folder=folder, limit=limit, offset=0))
                for e in ems:
                    e["_account"] = a["username"]
                return ems
            except Exception:
                return []

        results = await _asyncio.gather(*[_fetch_one(a) for a in accts])
        merged = [e for sub in results for e in sub]
        merged.sort(key=lambda e: e.get("date") or "", reverse=True)
        return {"emails": merged[: max(limit, 30) * 2], "folder": folder, "unified": True}

    # ── Boîte unique ──
    cfg = _get_email_config(account)
    if not cfg:
        return {"error": "Email non configuré", "emails": []}
    def _fetch():
        ems = _em.fetch_inbox(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
            folder=folder, limit=limit, offset=offset,
        )
        for e in ems:
            e["_account"] = cfg["username"]
        return ems
    try:
        emails = await loop.run_in_executor(None, _fetch)
        return {"emails": emails, "folder": folder}
    except Exception as e:
        return {"error": str(e), "emails": []}


@app.get("/api/email/read/{uid}")
async def email_read(uid: str, folder: str = "INBOX", account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _fetch():
        return _em.fetch_email(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
            uid=uid, folder=folder,
        )
    try:
        return await _asyncio.get_running_loop().run_in_executor(None, _fetch)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/email/search")
async def email_search(q: str, folder: str = "INBOX", limit: int = 20, account: str | None = None):
    loop = _asyncio.get_running_loop()
    # Recherche unifiée sur toutes les boîtes
    if account == "__all__":
        accts = _get_email_accounts()
        async def _search_one(a):
            try:
                rs = await loop.run_in_executor(None, lambda: _em.search_emails(
                    a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                    query=q, folder=folder, limit=limit))
                for e in rs:
                    e["_account"] = a["username"]
                return rs
            except Exception:
                return []
        results = await _asyncio.gather(*[_search_one(a) for a in accts])
        merged = [e for sub in results for e in sub]
        merged.sort(key=lambda e: e.get("date") or "", reverse=True)
        return {"results": merged, "unified": True}

    cfg = _get_email_config(account)
    if not cfg:
        return {"results": [], "error": "Email non configuré"}
    def _search():
        rs = _em.search_emails(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
            query=q, folder=folder, limit=limit,
        )
        for e in rs:
            e["_account"] = cfg["username"]
        return rs
    try:
        results = await loop.run_in_executor(None, _search)
        return {"results": results}
    except Exception as e:
        return {"results": [], "error": str(e)}


@app.get("/api/email/folders")
async def email_folders(account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        return {"folders": []}
    def _list():
        return _em.list_folders(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"]
        )
    try:
        folders = await _asyncio.get_running_loop().run_in_executor(None, _list)
        return {"folders": folders}
    except Exception as e:
        return {"folders": [], "error": str(e)}


@app.post("/api/email/send")
async def email_send(body: SendEmailRequest, account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _send():
        return _em.send_email(
            cfg["smtp_host"], cfg["smtp_port"], cfg["username"], cfg["password"],
            to=body.to, subject=body.subject, body=body.body,
            cc=body.cc, reply_to=body.reply_to, html_body=body.html_body,
        )
    try:
        result = await _asyncio.get_running_loop().run_in_executor(None, _send)
        db.log_execution("email_send", {"to": body.to, "subject": body.subject}, result, 0)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/email/{uid}")
async def email_delete(uid: str, folder: str = "INBOX", account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _del():
        _em.delete_email(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
            uid=uid, folder=folder,
        )
    await _asyncio.get_running_loop().run_in_executor(None, _del)
    return {"success": True}


@app.post("/api/email/mark")
async def email_mark(uid: str, seen: bool = True, folder: str = "INBOX", account: str | None = None):
    """Marque un email comme lu/non lu."""
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _m():
        _em.mark_email(cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
                       uid=uid, folder=folder, seen=seen)
    try:
        await _asyncio.get_running_loop().run_in_executor(None, _m)
        return {"success": True, "seen": seen}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/email/move")
async def email_move(uid: str, dest: str, folder: str = "INBOX", account: str | None = None):
    """Déplace un email vers un autre dossier (archiver = déplacer vers Archive/All Mail)."""
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _mv():
        _em.move_email(cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
                       uid=uid, dest_folder=dest, folder=folder)
    try:
        await _asyncio.get_running_loop().run_in_executor(None, _mv)
        return {"success": True, "dest": dest}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Signatures (par boîte) ────────────────────────────────────────────────────
def _coerce_obj(v, default):
    if isinstance(v, str):
        import json as _json
        try: return _json.loads(v)
        except Exception: return default
    return v if v is not None else default


@app.get("/api/email/signatures")
async def get_signatures():
    return {"signatures": _coerce_obj(db.get_setting("email_signatures"), {})}


@app.post("/api/email/signatures")
async def set_signatures(body: dict = Body(...)):
    sigs = _coerce_obj(db.get_setting("email_signatures"), {})
    acc = (body.get("account") or "").strip()
    if not acc:
        raise HTTPException(status_code=400, detail="account requis")
    sigs[acc] = body.get("signature", "")
    db.set_setting("email_signatures", sigs)
    return {"success": True}


# ── Modèles de réponse réutilisables ──────────────────────────────────────────
@app.get("/api/email/templates")
async def get_templates():
    t = _coerce_obj(db.get_setting("email_templates"), [])
    return {"templates": t if isinstance(t, list) else []}


@app.post("/api/email/templates")
async def add_template(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    content = body.get("body", "")
    if not name:
        raise HTTPException(status_code=400, detail="nom requis")
    t = _coerce_obj(db.get_setting("email_templates"), [])
    if not isinstance(t, list):
        t = []
    t = [x for x in t if x.get("name") != name]  # remplace si même nom
    t.append({"name": name, "body": content})
    db.set_setting("email_templates", t[-50:])
    return {"success": True, "count": len(t)}


@app.delete("/api/email/templates/{name}")
async def delete_template(name: str):
    t = _coerce_obj(db.get_setting("email_templates"), [])
    if not isinstance(t, list):
        t = []
    new = [x for x in t if x.get("name") != name]
    db.set_setting("email_templates", new)
    return {"success": True, "count": len(new)}


# ── Surveillance intelligente des mails importants (notifications) ────────────
@app.get("/api/email/watch")
async def get_email_watch():
    return _coerce_obj(db.get_setting("email_watch"), {"enabled": False, "interval_min": 5, "accounts": [], "max_notify": 5})


@app.post("/api/email/watch")
async def set_email_watch(body: dict = Body(...)):
    db.set_setting("email_watch", body)
    return {"success": True, "enabled": bool(body.get("enabled"))}


@app.post("/api/email/watch/run")
async def run_email_watch():
    """Vérifie maintenant (force) les mails importants et notifie."""
    return await tool_module.TOOLS_REGISTRY["email_watch_check"]({"force": True})


@app.get("/api/email/watch/alerts")
async def get_email_alerts():
    return {"alerts": _coerce_obj(db.get_setting("email_watch_alerts"), [])}


@app.post("/api/email/watch/alerts/clear")
async def clear_email_alerts():
    db.set_setting("email_watch_alerts", [])
    return {"success": True}


# ── Règles de classement automatique ─────────────────────────────────────────
@app.get("/api/email/rules")
async def get_email_rules():
    return {"rules": _coerce_obj(db.get_setting("email_rules"), [])}


@app.post("/api/email/rules")
async def set_email_rules(body: dict = Body(...)):
    rules = body.get("rules", [])
    db.set_setting("email_rules", rules if isinstance(rules, list) else [])
    return {"success": True, "count": len(rules) if isinstance(rules, list) else 0}


@app.post("/api/email/rules/run")
async def run_email_rules(dry_run: bool = False, account: str | None = None):
    return await tool_module.TOOLS_REGISTRY["email_apply_rules"]({"dry_run": dry_run, "account": account})


# ── Briefing du jour ──────────────────────────────────────────────────────────
@app.get("/api/briefing")
async def daily_briefing():
    """Briefing du jour : emails non lus + tâches en attente, synthèse IA."""
    result = await tool_module.TOOLS_REGISTRY["daily_briefing"]({})
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ── Marvin proactif (briefing matinal automatique) ─────────────────────────────
def _proactive_with_defaults(cfg: dict) -> dict:
    cfg.setdefault("morning_briefing", {"enabled": False, "time": "08:00", "voice": False, "voice_name": "henri"})
    cfg.setdefault("evening_recap", {"enabled": False, "time": "18:30", "voice": False, "voice_name": "henri"})
    cfg.setdefault("anticipation", {"enabled": False, "interval_min": 30, "overdue_tasks": True,
                                    "upcoming_events": True, "upcoming_events_min": 30, "max_notify": 5})
    # v2.150 — "Focus settings" (heures calmes), inspiré des réglages de repos/heures calmes
    # ajoutés par Claude en 2026 (recap mensuel + quiet hours). Coupe TOUTE notification
    # proactive (briefing/bilan/anticipation) sur une plage horaire — désactivé par défaut,
    # 22h-7h si activé (couvre la nuit, pas de sur-supposition sur les horaires de l'utilisateur).
    cfg.setdefault("quiet_hours", {"enabled": False, "start": "22:00", "end": "07:00"})
    return cfg


def _in_quiet_hours(cfg: dict, hm: str) -> bool:
    qh = cfg.get("quiet_hours", {})
    if not qh.get("enabled"):
        return False
    start, end = qh.get("start", "22:00"), qh.get("end", "07:00")
    if start <= end:
        return start <= hm < end
    return hm >= start or hm < end  # plage à cheval sur minuit (ex. 22:00 → 07:00)


@app.get("/api/proactive")
async def get_proactive():
    return _proactive_with_defaults(_get_proactive_cfg())


@app.post("/api/proactive")
async def set_proactive(body: dict = Body(...)):
    cfg = _proactive_with_defaults(_get_proactive_cfg())
    # Bloc morning_briefing (rétro-compat : l'ancienne UI postait les champs au top-level)
    if "morning_briefing" in body:
        inc = body["morning_briefing"]
    elif not any(k in body for k in ("evening_recap", "anticipation")):
        inc = body
    else:
        inc = {}
    mb = cfg["morning_briefing"]
    mb.update({k: inc[k] for k in ("enabled", "time", "voice", "voice_name") if k in inc})
    # Bloc evening_recap
    if "evening_recap" in body:
        er = cfg["evening_recap"]; inc = body["evening_recap"]
        er.update({k: inc[k] for k in ("enabled", "time", "voice", "voice_name") if k in inc})
    # Bloc anticipation
    if "anticipation" in body:
        an = cfg["anticipation"]; inc = body["anticipation"]
        an.update({k: inc[k] for k in ("enabled", "interval_min", "overdue_tasks", "upcoming_events",
                                       "upcoming_events_min", "max_notify") if k in inc})
    if "quiet_hours" in body:
        qh = cfg["quiet_hours"]; inc = body["quiet_hours"]
        qh.update({k: inc[k] for k in ("enabled", "start", "end") if k in inc})
    db.set_setting("proactive_config", cfg)
    return {"success": True, "config": cfg}


@app.post("/api/proactive/run")
async def run_proactive_now(kind: str = "morning"):
    """Déclenche immédiatement (test) : kind = morning | evening | anticipation."""
    cfg = _proactive_with_defaults(_get_proactive_cfg())
    if kind == "evening":
        return await run_evening_recap(cfg["evening_recap"])
    if kind == "anticipation":
        return await run_anticipation(cfg["anticipation"], force=True)
    return await run_morning_briefing(cfg["morning_briefing"])


# ── Telegram (alertes sur le téléphone) ─────────────────────────────────────────
@app.get("/api/telegram")
async def get_telegram():
    cfg = tool_module._telegram_cfg()
    # ne pas renvoyer le token en clair
    return {"enabled": bool(cfg.get("enabled")), "chat_id": cfg.get("chat_id", ""),
            "has_token": bool(cfg.get("bot_token"))}


@app.post("/api/telegram")
async def set_telegram(body: dict = Body(...)):
    cfg = tool_module._telegram_cfg()
    for k in ("enabled", "bot_token", "chat_id"):
        if k in body and body[k] not in (None, ""):
            cfg[k] = body[k]
    if body.get("enabled") is False:
        cfg["enabled"] = False
    db.set_setting("telegram_config", cfg)
    return {"success": True}


@app.post("/api/telegram/test")
async def test_telegram():
    return await tool_module._send_telegram("✅ Marvin est bien connecté à ce Telegram. Vous recevrez ici vos alertes.")


# ── Accès réseau / mobile (IP à jour automatiquement) ──────────────────────────
# ── Apprentissage : ce que Marvin a appris ─────────────────────────────────────
@app.get("/api/learning")
async def learning_list():
    import learning
    return {"counts": learning.count_learned(),
            "facts": learning.list_learned("facts", 200),
            "qa": learning.list_learned("qa", 100)}


@app.get("/api/learning/recall")
async def learning_recall(q: str):
    """Diagnostic : montre ce que Marvin se rappellerait pour une demande donnée."""
    import learning
    return await learning.recall(q)


@app.delete("/api/learning/{kind}/{point_id}")
async def learning_delete(kind: str, point_id: str):
    import learning
    learning.delete_learned("facts" if kind == "facts" else "qa", point_id)
    return {"success": True}


class TeachBody(BaseModel):
    text: str


@app.post("/api/learning/fact")
async def learning_add_fact(body: TeachBody):
    """Permet à l'utilisateur d'apprendre un fait à Marvin manuellement."""
    import learning
    await learning.add_fact(body.text)
    return {"success": True}


# ── Auto-configuration des modèles selon le matériel ──────────────────────────
@app.get("/api/auto-config")
async def get_auto_config():
    cfg = db.get_setting("auto_config") or {}
    en = db.get_setting("auto_model_config")
    cfg["enabled"] = True if en is None else bool(en)
    return cfg


@app.post("/api/auto-config")
async def run_auto_config(body: dict = Body(default={})):
    import auto_config
    if "enabled" in body:
        db.set_setting("auto_model_config", bool(body["enabled"]))
    if "mode" in body:
        m = (body.get("mode") or "auto")
        # 'auto' (ou inconnu) → l'auto choisit selon le matériel ; sinon on force le mode
        db.set_setting("perf_mode", m if m in auto_config._MODES else "auto")
    return await auto_config.apply_auto_config(force=True)


@app.get("/api/perf-modes")
async def list_perf_modes():
    """Liste les modes de performance disponibles + le mode actif et conseillé."""
    import auto_config
    cfg = db.get_setting("auto_config") or {}
    return {
        "modes": [{"key": k, **{kk: auto_config._MODES[k][kk] for kk in ("label", "desc", "max_tools", "whisper", "learn", "doc")}}
                  for k in auto_config._MODE_ORDER],
        "active": cfg.get("mode"), "auto": cfg.get("auto_mode"),
        "is_override": cfg.get("is_override", False),
        "override_setting": db.get_setting("perf_mode") or "auto",
    }


@app.get("/api/audit")
async def get_audit(limit: int = 100, source: str = ""):
    """Journal des actions de Marvin (transparence du mode autonome)."""
    import audit
    return {"actions": audit.recent(limit=limit, source=source or None), "stats": audit.stats()}


@app.post("/api/audit/clear")
async def clear_audit():
    import audit
    audit.clear()
    return {"success": True}


# ── Skills (compétences ajoutables en Markdown, façon Claude Code, sans coder) ───────
@app.get("/api/skills")
async def get_skills():
    import skills
    return {"skills": skills.list_skills()}


@app.post("/api/skills")
async def save_skill_endpoint(body: dict = Body(...)):
    import skills
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nom de la skill requis.")
    fn = skills.save_skill(name, (body.get("description") or "").strip(),
                           body.get("body") or "", body.get("tools") or [],
                           bool(body.get("enabled", True)),
                           triggers=body.get("triggers") or [], related=body.get("related") or [])
    skills.log_learning_event("create", name, "Créée manuellement par l'utilisateur", after=body.get("body"))
    return {"success": True, "file": fn}


@app.delete("/api/skills/{name}")
async def delete_skill_endpoint(name: str):
    import skills
    return {"success": skills.delete_skill(name)}


# ── 🩺 Marvin Doctor : auto-diagnostic déterministe (score + correctifs) ─────────────
@app.get("/api/doctor")
async def get_doctor():
    import doctor
    return await doctor.run_diagnostics()


@app.post("/api/doctor/fix")
async def doctor_fix(body: dict = Body(...)):
    import doctor
    fix_id = (body.get("fix") or "").strip()
    if not fix_id:
        raise HTTPException(status_code=400, detail="Correctif (fix) requis.")
    res = await doctor.apply_fix(fix_id)
    res["diagnostics"] = await doctor.run_diagnostics()
    return res


def _parse_skill_json(raw: str) -> dict:
    """Parser robuste de compétence (canonique dans skills.py)."""
    import skills
    return skills.parse_skill_json(raw)


@app.post("/api/skills/generate")
async def generate_skill_endpoint(body: dict = Body(...)):
    """Marvin RÉDIGE une skill à partir d'une description (méta : il apprend à faire X)."""
    import skills, json as _j
    desc = (body.get("description") or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="Décris ce que la skill doit faire.")
    tool_names = [t["function"]["name"] for t in tool_module.TOOLS_SPEC]
    prompt = (
        "Tu crées une COMPÉTENCE (skill) AGENTIQUE pour l'assistant Marvin. Une skill = une MÉTHODE "
        "robuste en langage naturel que Marvin suivra avec ses outils existants (PAS de code).\n"
        "RÉDIGE TOUT EN FRANÇAIS (seuls les noms d'outils restent en anglais).\n"
        f"Besoin de l'utilisateur : « {desc} »\n\n"
        f"Outils disponibles (choisis-en quelques-uns de pertinents) : {', '.join(tool_names[:120])}\n\n"
        "RÈGLE CLÉ : les étapes décrivent ce que MARVIN fait avec SES OUTILS (entre backticks), "
        "JAMAIS des manipulations manuelles de l'utilisateur (interdit : « appuyez sur Win+R », "
        "« ouvrez le panneau de configuration », « tapez appwiz.cpl »). Marvin AGIT lui-même via les outils. "
        "Choisis toujours au moins un outil pertinent dans 'tools'.\n"
        "Le 'body' doit être structuré en Markdown avec ces sections :\n"
        "## Objectif · ## Prérequis (infos à récupérer d'abord) · ## Étapes (numérotées, avec l'outil "
        "entre backticks) · ## Vérification (comment confirmer que c'est résolu) · ## Pièges à éviter.\n\n"
        "Réponds UNIQUEMENT par un objet JSON valide, sans texte autour, sans balises de code :\n"
        '{"name": "nom-court-en-kebab-case", "description": "quand utiliser cette skill (1 phrase)", '
        '"triggers": ["3 à 6 expressions déclencheuses que dirait l\'utilisateur"], '
        '"tools": ["outil1", "outil2"], "body": "## Objectif\\n...\\n## Prérequis\\n...\\n## Étapes\\n1. ...\\n'
        '## Vérification\\n...\\n## Pièges à éviter\\n- ..."}'
    )
    # v2.122 — model=None : cloud_routing.resolve_model() décide selon le réglage Ollama
    # Cloud + la sensibilité du prompt (contient la description utilisateur) ; repli local
    # (profil agent) identique à avant si le cloud n'est pas configuré.
    try:
        raw = await tool_module._ollama_generate(prompt, model=None, timeout=240)
    except Exception as e:
        return {"success": False, "error": f"Génération échouée (modèle indisponible) : {str(e)[:160]}"}
    data = _parse_skill_json(raw)
    if not data.get("name"):
        return {"success": False, "error": "Génération impossible, reformule la description.", "raw": raw[:300]}
    fn = skills.save_skill(data["name"], data.get("description", desc), data.get("body", ""),
                           [t for t in (data.get("tools") or []) if t in tool_names], True,
                           triggers=[str(t)[:40] for t in (data.get("triggers") or [])][:8])
    skills.log_learning_event("auto_create", data["name"], f"Générée depuis une description : « {desc[:150]} »",
                              after=data.get("body"))
    return {"success": True, "file": fn, "skill": skills.get_skill(data["name"])}


@app.post("/api/skills/from-conversation")
async def skill_from_conversation(body: dict = Body(...)):
    """Transforme la conversation en cours en COMPÉTENCE réutilisable (la méthode qui a marché)."""
    import skills, json as _j
    msgs = body.get("messages") or []
    lines = []
    for m in msgs[-30:]:
        role = m.get("role")
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
        if c and role in ("user", "assistant"):
            who = "Utilisateur" if role == "user" else "Marvin"
            lines.append(f"{who}: {str(c)[:800]}")
    transcript = "\n".join(lines)
    if len(transcript) < 40:
        return {"success": False, "error": "Conversation trop courte pour en tirer une compétence."}
    tool_names = [t["function"]["name"] for t in tool_module.TOOLS_SPEC]
    prompt = (
        "À partir de la CONVERSATION ci-dessous, crée une COMPÉTENCE (skill) RÉUTILISABLE pour Marvin : "
        "la MÉTHODE généralisée (étapes) qui a permis d'accomplir la tâche, pour la refaire la prochaine fois. "
        "RÉDIGE EN FRANÇAIS (noms d'outils en anglais).\n"
        "RÈGLE CLÉ : les étapes décrivent ce que MARVIN fait avec SES OUTILS (entre backticks), JAMAIS des "
        "manipulations manuelles de l'utilisateur (pas de « appuyez sur Win+R », « ouvrez tel panneau »). "
        "Choisis au moins un outil pertinent dans 'tools'. Ignore les étapes ratées de la conversation, ne garde que ce qui marche.\n\n"
        f"CONVERSATION :\n{transcript}\n\n"
        f"Outils disponibles : {', '.join(tool_names[:120])}\n\n"
        "Réponds UNIQUEMENT en JSON valide, sans balises de code :\n"
        '{"name": "nom-court-kebab", "description": "quand utiliser cette compétence (1 phrase)", '
        '"triggers": ["expressions déclencheuses"], "tools": ["outil1"], '
        '"body": "## Objectif\\n...\\n## Étapes\\n1. ...\\n## Vérification\\n..."}'
    )
    try:
        # v2.122 — model=None : le prompt contient la conversation source en clair, le
        # routage cloud/sensibilité (cloud_routing.resolve_model) s'applique dessus.
        raw = await tool_module._ollama_generate(prompt, model=None, timeout=240)
    except Exception as e:
        return {"success": False, "error": f"Génération échouée (modèle indisponible) : {str(e)[:160]}"}
    data = _parse_skill_json(raw)
    if not data.get("name"):
        return {"success": False, "error": "Impossible d'extraire une compétence de cette conversation. Réessaie après quelques échanges concrets."}
    fn = skills.save_skill(data["name"], data.get("description", ""), data.get("body", ""),
                           [t for t in (data.get("tools") or []) if t in tool_names], True,
                           triggers=[str(t)[:40] for t in (data.get("triggers") or [])][:8])
    skills.log_learning_event("auto_create", data["name"], "Extraite d'une conversation réussie",
                              after=data.get("body"))
    return {"success": True, "file": fn, "skill": skills.get_skill(data["name"])}


@app.get("/api/skills/stats")
async def skills_stats():
    """Statistiques de performance des compétences (usages, succès, échecs, version)."""
    import skills
    return {"stats": skills.get_stats()}


@app.post("/api/skills/{name}/upgrade")
async def skill_upgrade(name: str, body: dict = Body(default={})):
    """Améliore (ré-écrit) une compétence pour la rendre plus robuste/efficace.
    Déclenché manuellement ; l'auto-upgrade se fait sinon tout seul après un échec."""
    import skills
    reason = (body or {}).get("reason", "Amélioration manuelle demandée par l'utilisateur.")
    transcript = (body or {}).get("transcript", "")
    tool_names = [t["function"]["name"] for t in tool_module.TOOLS_SPEC]

    async def _g(p):
        # v2.122 — model=None : le prompt inclut le transcript (peut contenir des données
        # d'outils sensibles) — routage cloud/sensibilité appliqué dessus.
        return await tool_module._ollama_generate(p, model=None, timeout=240)

    return await skills.upgrade_skill(name, _g, reason=reason, transcript=transcript, tool_names=tool_names)


@app.get("/api/skills/{name}/versions")
async def skill_versions(name: str):
    """Liste les versions archivées d'une compétence (pour rollback)."""
    import skills
    return {"versions": skills.list_versions(name), "stats": skills.get_stats(name)}


@app.post("/api/skills/{name}/rollback")
async def skill_rollback(name: str, body: dict = Body(...)):
    """Restaure une version archivée d'une compétence."""
    import skills
    vf = (body or {}).get("version_file")
    if not vf:
        raise HTTPException(status_code=400, detail="version_file requis.")
    ok = skills.rollback_skill(name, vf)
    return {"success": ok, "skill": skills.get_skill(name) if ok else None}


@app.get("/api/skills/{name}/resources")
async def skill_resources_list(name: str):
    """Liste les ressources (fichiers de référence) embarquées d'une compétence."""
    import skills
    return {"resources": skills.list_resources(name)}


@app.post("/api/skills/{name}/resources")
async def skill_resource_save(name: str, body: dict = Body(...)):
    """Crée/édite une ressource TEXTE (modèle, table de prix, check-list…)."""
    import skills
    if not skills.get_skill(name):
        raise HTTPException(status_code=404, detail="Compétence introuvable.")
    fn = (body or {}).get("filename", "").strip()
    content = (body or {}).get("content", "")
    if not fn:
        raise HTTPException(status_code=400, detail="filename requis.")
    if "." not in fn:
        fn += ".md"   # défaut Markdown
    return skills.save_resource(name, fn, content)


@app.post("/api/skills/{name}/resources/upload")
async def skill_resource_upload(name: str, file: UploadFile = File(...)):
    """Téléverse une ressource (binaire OK : PDF table de prix, modèle .docx…)."""
    import skills
    if not skills.get_skill(name):
        raise HTTPException(status_code=404, detail="Compétence introuvable.")
    data = await file.read()
    return skills.save_resource(name, file.filename or "ressource", data)


@app.get("/api/skills/{name}/resources/{filename}")
async def skill_resource_get(name: str, filename: str):
    """Contenu texte d'une ressource (aperçu/édition). None si binaire."""
    import skills
    return {"name": filename, "content": skills.read_resource(name, filename, max_chars=20000),
            "path": skills.resource_path(name, filename)}


@app.delete("/api/skills/{name}/resources/{filename}")
async def skill_resource_delete(name: str, filename: str):
    """Supprime une ressource d'une compétence."""
    import skills
    return {"success": skills.delete_resource(name, filename)}


@app.post("/api/skills/suggest")
async def skills_suggest(body: dict = Body(default={})):
    """🔎 Mining proactif : analyse les demandes récentes et propose de NOUVELLES
    compétences pour les tâches récurrentes non encore couvertes."""
    import skills
    limit = int((body or {}).get("limit", 120))
    messages = db.get_recent_user_messages(limit=limit)
    tool_names = [t["function"]["name"] for t in tool_module.TOOLS_SPEC]

    async def _g(p):
        # v2.122 — model=None : le prompt inclut jusqu'à 120 messages utilisateur récents
        # en clair — routage cloud/sensibilité appliqué dessus.
        return await tool_module._ollama_generate(p, model=None, timeout=240)

    suggestions = await skills.suggest_skills(_g, messages, tool_names=tool_names)
    return {"suggestions": suggestions, "analyzed": len(messages)}


@app.post("/api/skills/suggest/dismiss")
async def skills_suggest_dismiss(body: dict = Body(...)):
    """Refuse une suggestion → ne plus la reproposer."""
    import skills
    nm = (body or {}).get("name", "").strip()
    if not nm:
        raise HTTPException(status_code=400, detail="name requis.")
    skills.dismiss_suggestion(nm)
    return {"success": True}


@app.get("/api/skills/learning_log")
async def skills_learning_log(limit: int = 50, skill: str = None):
    """📖 Journal d'apprentissage persistant : créations/upgrades/consolidations/oublis
    de compétences, avec diffs. C'est ce que la consolidation nocturne relit."""
    import skills
    return {"log": skills.get_learning_log(limit=limit, skill_name=skill)}


@app.get("/api/skills/match_log")
async def skills_match_log(limit: int = 50):
    """🎯 v2.124 — Journal des tentatives de matching (gagnant + dauphin + scores) : sert à
    juger si le seuil/la formule sont bien calibrés, et si un retrieval multi-compétences
    (façon Voyager) apporterait quelque chose — cas où le score du dauphin est proche du
    gagnant, signe d'ambiguïté réelle entre deux compétences plutôt qu'un bruit de mesure."""
    import skills
    return {"log": skills.get_match_log(limit=limit)}


@app.get("/api/skills/overlaps")
async def skills_overlaps(threshold: float = 0.85):
    """🔍 v2.124 — Scan de similarité croisée entre TOUTES les compétences (pas seulement au
    sein d'une même compétence) : repère les paires qui se chevauchent trop et pourraient
    perturber le matcher ou mériteraient une fusion. Lecture seule, ne modifie rien."""
    import skills
    pairs = await skills.find_overlapping_skills(threshold=threshold)
    return {"pairs": pairs, "threshold": threshold}


@app.post("/api/skills/consolidate")
async def skills_consolidate(body: dict = Body(default={})):
    """Déclenche manuellement une passe de consolidation (normalement automatique,
    plus fréquente la nuit — voir _skill_night_learning_worker)."""
    import skills

    async def _g(p):
        # v2.122 — model=None : routage cloud/sensibilité sur le prompt réel.
        return await tool_module._ollama_generate(p, model=None, timeout=240)

    reviewed = await skills.review_and_consolidate_learnings(_g, skill_name=(body or {}).get("skill"))
    forgotten = skills.consolidate_obsolete_skills()
    return {"reviewed": reviewed, "forgotten": forgotten}


@app.get("/api/winget/search")
async def winget_search(q: str, source: str = None, limit: int = 20):
    """📦 Emporium : recherche de logiciels installables (Winget)."""
    args = {"query": q, "limit": limit}
    if source:
        args["source"] = source
    return await tool_module.TOOLS_REGISTRY["winget_search"](args)


@app.get("/api/winget/upgrades")
async def winget_upgrades():
    """Liste des logiciels ayant une mise à jour disponible."""
    return await tool_module.TOOLS_REGISTRY["winget_list_upgrades"]({})


@app.get("/api/winget/installed")
async def winget_installed(q: str = None):
    """Liste des logiciels installés (filtrable) — pour voir/désinstaller."""
    return await tool_module.TOOLS_REGISTRY["winget_list_installed"]({"query": q} if q else {})


@app.post("/api/winget/install")
async def winget_install(body: dict = Body(...)):
    """Installe un paquet (confirmation via l'UI → confirmed=True)."""
    return await tool_module.TOOLS_REGISTRY["winget_install"]({**(body or {}), "confirmed": True})


@app.post("/api/winget/upgrade")
async def winget_upgrade(body: dict = Body(default={})):
    """Met à jour un paquet (id) ou tout (all=true)."""
    return await tool_module.TOOLS_REGISTRY["winget_upgrade"]({**(body or {}), "confirmed": True})


@app.post("/api/winget/uninstall")
async def winget_uninstall(body: dict = Body(...)):
    """Désinstalle un paquet (confirmation via l'UI → confirmed=True)."""
    return await tool_module.TOOLS_REGISTRY["winget_uninstall"]({**(body or {}), "confirmed": True})


@app.get("/api/pantheon/telemetry")
async def pantheon_telemetry_status():
    return await tool_module.TOOLS_REGISTRY["tweak_telemetry"]({"action": "status"})


@app.post("/api/pantheon/telemetry")
async def pantheon_telemetry_set(body: dict = Body(...)):
    action = (body or {}).get("action", "disable")
    return await tool_module.TOOLS_REGISTRY["tweak_telemetry"]({"action": action, "confirmed": True})


@app.get("/api/pantheon/debloat")
async def pantheon_debloat_list():
    return await tool_module.TOOLS_REGISTRY["tweak_debloat_list"]({})


@app.post("/api/pantheon/debloat/remove")
async def pantheon_debloat_remove(body: dict = Body(...)):
    pkgs = (body or {}).get("packages") or []
    return await tool_module.TOOLS_REGISTRY["tweak_debloat_remove"]({"packages": pkgs, "confirmed": True})


@app.get("/api/pantheon/network")
async def pantheon_network_status():
    return await tool_module.TOOLS_REGISTRY["tweak_network_harden"]({"action": "status"})


@app.post("/api/pantheon/network/apply")
async def pantheon_network_apply():
    return await tool_module.TOOLS_REGISTRY["tweak_network_harden"]({"action": "apply", "confirmed": True})


@app.post("/api/pantheon/restore-point")
async def pantheon_restore_point(body: dict = Body(default={})):
    desc = (body or {}).get("description", "Marvin — avant optimisation")
    return await tool_module.TOOLS_REGISTRY["system_restore_point"]({"description": desc, "confirmed": True})


@app.get("/api/catharsis/scan")
async def catharsis_scan():
    """🧹 Catharsis : analyse l'espace récupérable (ne supprime rien)."""
    return await tool_module.TOOLS_REGISTRY["catharsis_scan"]({})


@app.post("/api/catharsis/clean")
async def catharsis_clean(body: dict = Body(...)):
    """Purge les catégories choisies (confirmation via l'UI)."""
    cats = (body or {}).get("categories") or []
    return await tool_module.TOOLS_REGISTRY["catharsis_clean"]({"categories": cats, "confirmed": True})


@app.get("/api/codex/status")
async def codex_status():
    """🎛️ Codex : état agrégé des paramètres OS clés."""
    reg = tool_module.TOOLS_REGISTRY
    return {
        "power":      await reg["os_power_plan"]({"action": "get"}),
        "dark":       await reg["os_dark_mode"]({"action": "get"}),
        "firewall":   await reg["os_firewall"]({"action": "status"}),
        "hibernation": await reg["os_hibernation"]({"action": "status"}),
        "adapters":   await reg["os_network_adapters"]({"action": "list"}),
    }


@app.post("/api/codex/power")
async def codex_power(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["os_power_plan"]({"action": "set", "plan": (body or {}).get("plan"), "confirmed": True})


@app.post("/api/codex/dark")
async def codex_dark(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["os_dark_mode"]({"action": (body or {}).get("action", "toggle"), "confirmed": True})


@app.post("/api/codex/firewall")
async def codex_firewall(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["os_firewall"]({"action": (body or {}).get("action", "status"), "confirmed": True})


@app.post("/api/codex/hibernation")
async def codex_hibernation(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["os_hibernation"]({"action": (body or {}).get("action", "status"), "confirmed": True})


@app.post("/api/codex/adapter")
async def codex_adapter(body: dict = Body(...)):
    b = body or {}
    return await tool_module.TOOLS_REGISTRY["os_network_adapters"]({"action": b.get("action"), "name": b.get("name"), "confirmed": True})


@app.get("/api/router/route")
async def router_route(q: str):
    """Diagnostic du routing intelligent : montre les outils choisis (mots-clés +
    sémantique + appris) pour une demande donnée."""
    import tool_router, agent as _agent
    text = (q or "").lower()
    keyword = set(_agent._ALWAYS_INCLUDE)
    for kws, tools in _agent._KEYWORD_TOOLS.items():
        if any(k in text for k in kws):
            keyword.update(tools)
    keyword -= set(_agent._ALWAYS_INCLUDE)
    routed = await tool_router.route_tools(q)
    return {"query": q,
            "keyword": sorted(keyword),
            "semantic": sorted(routed.get("semantic", set())),
            "learned": sorted(routed.get("learned", set()))}


@app.get("/api/network")
async def network_info():
    """Retourne les adresses IP ACTUELLES du PC (recalculées à chaque appel → toujours
    à jour même si on change de lieu/réseau). Sert à l'accès mobile."""
    import socket, psutil
    hostname = socket.gethostname()
    primary = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))   # n'envoie rien, donne juste l'IP de l'interface active
        primary = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    addrs, seen = [], set()
    try:
        for ifname, iflist in psutil.net_if_addrs().items():
            for a in iflist:
                if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254.")):
                    ip = a.address
                    if ip in seen:
                        continue
                    seen.add(ip)
                    low = ifname.lower()
                    if ip.startswith("100.") or "tailscale" in low:
                        kind = "tailscale"
                    elif any(v in low for v in ("vmware", "virtualbox", "vethernet", "hyper-v", "loopback")):
                        kind = "virtuel"
                    elif ip.startswith(("192.168.", "10.", "172.")):
                        kind = "lan"
                    else:
                        kind = "autre"
                    addrs.append({"ip": ip, "interface": ifname, "kind": kind,
                                  "primary": ip == primary, "url": f"http://{ip}:3000"})
    except Exception:
        pass
    order = {"lan": 0, "tailscale": 1, "autre": 2, "virtuel": 3}
    addrs.sort(key=lambda x: (0 if x["primary"] else 1, order.get(x["kind"], 9)))
    return {"hostname": hostname, "primary_ip": primary,
            "primary_url": f"http://{primary}:3000" if primary else None,
            "addresses": addrs}


@app.get("/api/network/qr")
async def network_qr(url: str):
    """QR code (PNG) d'une URL — pour scanner depuis le téléphone."""
    import qrcode, io
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


# ── Documents (RAG : parle à tes documents) ────────────────────────────────────
@app.get("/api/documents")
async def list_documents():
    return await tool_module.TOOLS_REGISTRY["document_list"]({})


@app.get("/api/documents/templates")
async def document_templates():
    return {"templates": tool_module._doc_templates_list()}


@app.post("/api/documents/generate")
async def generate_document(body: dict = Body(...)):
    result = await tool_module.TOOLS_REGISTRY["document_generate"](body)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/documents/download")
async def download_document(path: str):
    import os as _os
    base = _os.path.abspath(_os.path.join(_os.path.dirname(tool_module.__file__), "..", "data", "documents_generes"))
    target = _os.path.abspath(path)
    if not target.startswith(base) or not _os.path.exists(target):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    from fastapi.responses import FileResponse
    return FileResponse(target, filename=_os.path.basename(target),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/api/documents/letterhead")
async def get_letterhead():
    lh = db.get_setting("doc_letterhead")
    return lh if isinstance(lh, dict) else {}


@app.post("/api/documents/letterhead")
async def save_letterhead(body: dict = Body(...)):
    db.set_setting("doc_letterhead", body)
    return {"success": True}


@app.post("/api/documents/logo")
async def upload_logo(file: UploadFile = File(...)):
    import os as _os
    docs_dir = _os.path.join(_os.path.dirname(tool_module.__file__), "..", "data", "documents_generes")
    _os.makedirs(docs_dir, exist_ok=True)
    ext = (_os.path.splitext(file.filename or "logo.png")[1] or ".png").lower()
    dest = _os.path.join(docs_dir, "letterhead_logo" + ext)
    with open(dest, "wb") as f:
        f.write(await file.read())
    lh = db.get_setting("doc_letterhead")
    lh = lh if isinstance(lh, dict) else {}
    lh["logo"] = dest
    db.set_setting("doc_letterhead", lh)
    return {"success": True, "logo": dest}


class DocIndexBody(BaseModel):
    path: str


@app.post("/api/documents/index")
async def index_document(body: DocIndexBody):
    result = await tool_module.TOOLS_REGISTRY["document_index"]({"path": body.path})
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class DocAskBody(BaseModel):
    question: str
    k: int = 6


@app.post("/api/documents/ask")
async def ask_documents(body: DocAskBody):
    result = await tool_module.TOOLS_REGISTRY["document_ask"]({"question": body.question, "k": body.k})
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class DocRefineBody(BaseModel):
    file: str
    section: str
    instruction: str = ""
    notes: str = ""


@app.post("/api/documents/refine")
async def refine_document(body: DocRefineBody):
    result = await tool_module.TOOLS_REGISTRY["document_refine_section"](body.dict())
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.delete("/api/documents/{doc_id}")
async def forget_document(doc_id: str):
    return await tool_module.TOOLS_REGISTRY["document_forget"]({"id": doc_id})


@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Reçoit un fichier, l'enregistre puis l'indexe pour le RAG."""
    import os as _os
    docs_dir = _os.path.join(_os.path.dirname(__file__), "..", "data", "documents")
    _os.makedirs(docs_dir, exist_ok=True)
    safe = _os.path.basename(file.filename or "document")
    dest = _os.path.join(docs_dir, safe)
    data = await file.read()
    with open(dest, "wb") as f:
        f.write(data)
    result = await tool_module.TOOLS_REGISTRY["document_index"]({"path": dest})
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Agenda local (événements) ─────────────────────────────────────────────────
@app.get("/api/events")
async def list_events(period: str = "", start: str = "", end: str = ""):
    args = {}
    if period: args["period"] = period
    if start: args["start"] = start
    if end: args["end"] = end
    return await tool_module.TOOLS_REGISTRY["event_list"](args)


class EventBody(BaseModel):
    title: str = ""
    natural: str = ""
    start_at: str = ""
    end_at: str = ""
    location: str = ""
    description: str = ""
    all_day: bool = False
    reminder_minutes: int | None = None


@app.post("/api/events")
async def create_event(body: EventBody):
    result = await tool_module.TOOLS_REGISTRY["event_create"](body.model_dump())
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.patch("/api/events/{event_id}")
async def update_event(event_id: str, body: dict = Body(...)):
    body["id"] = event_id
    result = await tool_module.TOOLS_REGISTRY["event_update"](body)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.delete("/api/events/{event_id}")
async def delete_event(event_id: str):
    return await tool_module.TOOLS_REGISTRY["event_delete"]({"id": event_id})


# ── Agendas connectés (abonnements iCal) ────────────────────────────────────────
@app.get("/api/calendar/subscriptions")
async def list_calendar_subs():
    return await tool_module.TOOLS_REGISTRY["calendar_subscriptions"]({})


class CalendarSubBody(BaseModel):
    url: str
    name: str = ""
    color: str = "#10b981"


@app.post("/api/calendar/subscriptions")
async def add_calendar_sub(body: CalendarSubBody):
    result = await tool_module.TOOLS_REGISTRY["calendar_subscribe"](body.model_dump())
    if result.get("error") and not result.get("subscription"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.delete("/api/calendar/subscriptions/{sub_id}")
async def remove_calendar_sub(sub_id: str):
    return await tool_module.TOOLS_REGISTRY["calendar_unsubscribe"]({"id": sub_id})


@app.post("/api/calendar/subscriptions/sync")
async def sync_calendar_subs(sub_id: str = ""):
    return await tool_module.TOOLS_REGISTRY["calendar_sync"]({"id": sub_id} if sub_id else {})


class DraftReplyRequest(BaseModel):
    uid: str = ""
    body: str = ""
    subject: str = ""
    from_: str = Field("", alias="from")
    instruction: str = ""
    tone: str = ""
    folder: str = "INBOX"
    account: str = ""
    model_config = {"populate_by_name": True}


@app.post("/api/email/draft-reply")
async def email_draft_reply(body: DraftReplyRequest):
    """Génère par IA un brouillon de réponse (ne l'envoie pas)."""
    args = {
        "uid": body.uid, "body": body.body, "subject": body.subject,
        "from": body.from_, "instruction": body.instruction, "tone": body.tone,
        "folder": body.folder, "account": body.account or None,
    }
    result = await tool_module.TOOLS_REGISTRY["email_draft_reply"](args)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


class SummarizeRequest(BaseModel):
    uid: str = ""
    body: str = ""
    subject: str = ""
    from_: str = Field("", alias="from")
    folder: str = "INBOX"
    account: str = ""
    model_config = {"populate_by_name": True}


@app.post("/api/email/summarize")
async def email_summarize(body: SummarizeRequest):
    """Résume un email par IA."""
    args = {"uid": body.uid, "body": body.body, "subject": body.subject,
            "from": body.from_, "folder": body.folder, "account": body.account or None}
    result = await tool_module.TOOLS_REGISTRY["email_summarize"](args)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/email/digest")
async def email_digest(account: str | None = None, limit: int = 15, folder: str = "INBOX"):
    """Briefing IA priorisé de la boîte (ou de toutes via account=__all__)."""
    result = await tool_module.TOOLS_REGISTRY["email_digest"](
        {"account": account, "limit": limit, "folder": folder})
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ── Assistant email automatique (3 modes) ────────────────────────────────────
class AutomationConfig(BaseModel):
    mode: str = "manuel"                 # manuel | brouillon | autonome
    accounts: list[str] = Field(default_factory=list)
    instructions: str = ""
    tone: str = "professionnel, clair et courtois"
    signature: str = ""
    only_from: list[str] = Field(default_factory=list)
    never_from: list[str] = Field(default_factory=list)
    skip_keywords: list[str] = Field(default_factory=list)
    max_per_run: int = 5


@app.get("/api/email/automation")
async def get_email_automation():
    cfg = db.get_setting("email_automation")
    if isinstance(cfg, str):
        import json as _json
        try: cfg = _json.loads(cfg)
        except Exception: cfg = None
    if not isinstance(cfg, dict):
        cfg = {"mode": "manuel"}
    return cfg


@app.post("/api/email/automation")
async def set_email_automation(body: AutomationConfig):
    db.set_setting("email_automation", body.model_dump())
    return {"success": True, "mode": body.mode}


@app.post("/api/email/automation/run")
async def run_email_automation(dry_run: bool = False, mode: str | None = None):
    """Lance le traitement maintenant (brouillons ou envoi autonome selon le mode)."""
    result = await tool_module.TOOLS_REGISTRY["email_automation_run"](
        {"dry_run": dry_run, "mode": mode})
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/email/automation/drafts")
async def get_pending_drafts():
    drafts = db.get_setting("email_pending_drafts")
    if isinstance(drafts, str):
        import json as _json
        try: drafts = _json.loads(drafts)
        except Exception: drafts = []
    return {"drafts": drafts if isinstance(drafts, list) else []}


@app.post("/api/email/automation/drafts/clear")
async def clear_pending_drafts():
    db.set_setting("email_pending_drafts", [])
    return {"success": True}


@app.post("/api/email/to-task")
async def email_to_task(body: SummarizeRequest):
    """Transforme un email en tâche actionnable (IA)."""
    args = {"uid": body.uid, "body": body.body, "subject": body.subject,
            "from": body.from_, "folder": body.folder, "account": body.account or None}
    result = await tool_module.TOOLS_REGISTRY["email_to_task"](args)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/email/attachment")
async def email_attachment(uid: str, name: str = "", account: str | None = None, folder: str = "INBOX"):
    """Télécharge une pièce jointe d'un email."""
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _f():
        return _em.fetch_attachment(cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
                                    uid=uid, name=name, folder=folder)
    att = await _asyncio.get_running_loop().run_in_executor(None, _f)
    if not att or not att.get("data"):
        raise HTTPException(status_code=404, detail="Pièce jointe introuvable")
    import urllib.parse as _up
    fn = _up.quote(att["name"] or "piece_jointe")
    return Response(content=att["data"], media_type=att.get("content_type", "application/octet-stream"),
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"})


@app.get("/api/email/attachment/summary")
async def email_attachment_summary(uid: str, name: str = "", account: str | None = None, folder: str = "INBOX"):
    """Résume par IA une pièce jointe (PDF, Word, texte)."""
    result = await tool_module.TOOLS_REGISTRY["email_attachment_summary"](
        {"uid": uid, "name": name, "account": account or None, "folder": folder})
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Multi-agents — exécution parallèle d'outils avec SSE
# ══════════════════════════════════════════════════════════════════════════════

class AgentTask(BaseModel):
    id: str
    tool_name: str
    args: dict = Field(default_factory=dict)
    label: str = ""


class AgentRunRequest(BaseModel):
    tasks: list[AgentTask]


@app.post("/api/agents/parallel")
async def agents_parallel(body: AgentRunRequest):
    """Exécute plusieurs outils en parallèle et retourne tous les résultats."""

    async def _run_one(task: AgentTask) -> dict:
        t0 = datetime.now()
        try:
            fn = tool_module.TOOLS_REGISTRY.get(task.tool_name)
            if fn is None:
                return {
                    "id": task.id, "tool_name": task.tool_name, "label": task.label,
                    "success": False, "result": {"error": f"Outil inconnu : {task.tool_name}"},
                    "duration_ms": 0,
                }
            result = await fn(task.args)
            ms = int((datetime.now() - t0).total_seconds() * 1000)
            return {
                "id": task.id, "tool_name": task.tool_name, "label": task.label,
                "success": "error" not in result,
                "result": result, "duration_ms": ms,
            }
        except Exception as e:
            ms = int((datetime.now() - t0).total_seconds() * 1000)
            return {
                "id": task.id, "tool_name": task.tool_name, "label": task.label,
                "success": False, "result": {"error": str(e)}, "duration_ms": ms,
            }

    global_t0 = datetime.now()
    results = await _asyncio.gather(*[_run_one(t) for t in body.tasks])
    total_ms = int((datetime.now() - global_t0).total_seconds() * 1000)
    return {
        "total_ms": total_ms,
        "count": len(results),
        "results": results,
    }


@app.post("/api/agents/parallel/stream")
async def agents_parallel_stream(body: AgentRunRequest):
    """
    SSE : envoie chaque résultat dès qu'il est disponible (vrai parallélisme).
    Le client reçoit des événements 'task_done' + 'all_done' en fin.
    """

    async def generate():
        t0 = datetime.now()
        pending = set()
        queue: _asyncio.Queue = _asyncio.Queue()

        async def _run_and_enqueue(task: AgentTask):
            st = datetime.now()
            try:
                fn = tool_module.TOOLS_REGISTRY.get(task.tool_name)
                if fn is None:
                    result = {"error": f"Outil inconnu : {task.tool_name}"}
                    success = False
                else:
                    result = await fn(task.args)
                    success = "error" not in result
                ms = int((datetime.now() - st).total_seconds() * 1000)
            except Exception as e:
                result = {"error": str(e)}
                success = False
                ms = int((datetime.now() - st).total_seconds() * 1000)
            await queue.put({
                "id": task.id, "tool_name": task.tool_name, "label": task.label,
                "success": success, "result": result, "duration_ms": ms,
            })

        for task in body.tasks:
            pending.add(_asyncio.create_task(_run_and_enqueue(task)))

        completed = 0
        total = len(body.tasks)

        while completed < total:
            item = await queue.get()
            completed += 1
            payload = json.dumps({
                "event": "task_done",
                "completed": completed,
                "total": total,
                **item,
            })
            yield f"data: {payload}\n\n"

        total_ms = int((datetime.now() - t0).total_seconds() * 1000)
        yield f"data: {json.dumps({'event': 'all_done', 'total_ms': total_ms, 'count': total})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Workflows — enchaînement d'outils
# ══════════════════════════════════════════════════════════════════════════════

class WorkflowStep(BaseModel):
    id: str
    tool_name: str
    args: dict = Field(default_factory=dict)
    label: str = ""
    enabled: bool = True
    when: str | None = None              # condition d'exécution (templating)
    retries: int = 0                     # tentatives en cas d'échec
    continue_on_error: bool = False      # poursuivre malgré une erreur
    save_as: str | None = None           # nomme la sortie ({{nom.path}})


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    steps: list[WorkflowStep] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[WorkflowStep] | None = None


@app.get("/api/workflows")
async def list_workflows():
    return db.list_workflows()


@app.post("/api/workflows")
async def create_workflow(body: WorkflowCreate):
    steps = [s.model_dump() for s in body.steps]
    return db.create_workflow(body.name, body.description, steps)


@app.get("/api/workflows/{wid}")
async def get_workflow(wid: str):
    wf = db.get_workflow(wid)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow introuvable")
    return wf


@app.put("/api/workflows/{wid}")
async def update_workflow(wid: str, body: WorkflowUpdate):
    updates = body.model_dump(exclude_none=True)
    if "steps" in updates:
        updates["steps"] = [s.model_dump() if hasattr(s, "model_dump") else s for s in body.steps]
    wf = db.update_workflow(wid, updates)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow introuvable")
    return wf


@app.delete("/api/workflows/{wid}")
async def delete_workflow(wid: str):
    db.delete_workflow(wid)
    return {"success": True}


@app.get("/api/workflows/{wid}/runs")
async def list_workflow_runs(wid: str, limit: int = 20):
    return db.list_workflow_runs(wid, limit=limit)


def _wf_lookup(ctx: dict, path: str):
    """Navigue un chemin pointé dans le contexte : 'step1.path', 'prev.result.size'…"""
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except Exception:
                return ""
        else:
            return ""
        if cur is None:
            return ""
    return cur


def _wf_resolve(value, ctx: dict):
    """Remplace {{...}} dans une valeur (str/dict/list) à partir du contexte."""
    import re as _re_wf
    if isinstance(value, str):
        # Valeur entièrement = un seul template → on préserve le type (objet/nombre)
        m = _re_wf.fullmatch(r"\s*\{\{([^}]+)\}\}\s*", value)
        if m:
            return _wf_lookup(ctx, m.group(1).strip())
        return _re_wf.sub(r"\{\{([^}]+)\}\}", lambda mm: str(_wf_lookup(ctx, mm.group(1).strip())), value)
    if isinstance(value, dict):
        return {k: _wf_resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_wf_resolve(v, ctx) for v in value]
    return value


def _wf_condition(expr, ctx: dict) -> bool:
    """Évalue une condition simple : truthiness ou comparaison ==, !=, >, <."""
    if expr in (None, "", True):
        return True
    if expr is False:
        return False
    resolved = _wf_resolve(expr, ctx) if isinstance(expr, str) else expr
    import re as _re_wf
    if isinstance(resolved, str):
        m = _re_wf.match(r"^(.*?)\s*(==|!=|>=|<=|>|<)\s*(.*)$", resolved.strip())
        if m:
            a, op, b = m.group(1).strip().strip('"\''), m.group(2), m.group(3).strip().strip('"\'')
            try:
                fa, fb = float(a), float(b)
                a, b = fa, fb
            except ValueError:
                a, b = a.lower(), b.lower()   # comparaison de chaînes insensible à la casse
            return {"==": a == b, "!=": a != b, ">": a > b, "<": a < b,
                    ">=": a >= b, "<=": a <= b}.get(op, True)
        low = resolved.strip().lower()
        return low not in ("", "false", "0", "none", "null", "no")
    return bool(resolved)


@app.post("/api/workflows/{wid}/run")
async def run_workflow(wid: str):
    """Exécute les étapes d'un workflow : templating multi-étapes ({{step2.path}},
    {{prev.result.key}}), conditions (when), retries, continue-on-error."""
    wf = db.get_workflow(wid)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow introuvable")

    run = db.create_workflow_run(wid)
    run_id = run["id"]
    t0 = datetime.now()
    steps_results = []
    overall_ok = True
    # Contexte accessible aux templates : prev (dernier), step1..N, et leurs résultats
    ctx = {"prev": {}, "vars": {}}

    for idx, step in enumerate(wf.get("steps", []), start=1):
        if not step.get("enabled", True):
            steps_results.append({"step_id": step["id"], "skipped": True, "tool_name": step["tool_name"]})
            continue

        # Condition d'exécution (when)
        if not _wf_condition(step.get("when"), ctx):
            steps_results.append({"step_id": step["id"], "tool_name": step["tool_name"],
                                  "skipped": True, "reason": "condition non remplie"})
            continue

        tool_name = step["tool_name"]
        args = _wf_resolve(dict(step.get("args", {})), ctx)
        retries = int(step.get("retries", 0) or 0)
        cont_on_err = bool(step.get("continue_on_error", False))

        step_t0 = datetime.now()
        result, success, last_err = None, False, None
        for attempt in range(retries + 1):
            try:
                fn = tool_module.TOOLS_REGISTRY.get(tool_name)
                if fn is None:
                    raise ValueError(f"Outil inconnu : {tool_name}")
                result = await fn(args)
                success = not (isinstance(result, dict) and result.get("error"))
                if success:
                    break
                last_err = (result or {}).get("error", "échec")
            except Exception as e:
                result, last_err = {"error": str(e)}, str(e)
            if attempt < retries:
                await _asyncio.sleep(min(2 ** attempt, 5))

        duration = int((datetime.now() - step_t0).total_seconds() * 1000)
        entry = {"step_id": step["id"], "tool_name": tool_name, "args": args,
                 "result": result, "success": success, "duration_ms": duration,
                 "attempts": attempt + 1}
        steps_results.append(entry)

        # Met à jour le contexte (résultat accessible par stepN et par nom save_as)
        ctx["prev"] = entry
        ctx[f"step{idx}"] = entry
        if step.get("save_as"):
            ctx["vars"][step["save_as"]] = result
            ctx[step["save_as"]] = entry

        if not success and not cont_on_err:
            overall_ok = False
            break  # arrêt sauf si continue_on_error

    total_ms = int((datetime.now() - t0).total_seconds() * 1000)
    status = "success" if overall_ok else "failed"
    finished_run = db.finish_workflow_run(run_id, status, steps_results, total_ms)

    # Mise à jour compteurs
    db.update_workflow(wid, {
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_status": status,
        "run_count": True,
    })

    return {
        "run_id": run_id,
        "workflow_id": wid,
        "status": status,
        "duration_ms": total_ms,
        "steps_results": steps_results,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Transcription vocale — Whisper local (faster-whisper)
# ══════════════════════════════════════════════════════════════════════════════

_whisper_model = None
_whisper_lock = _asyncio.Lock()


def _whisper_model_size() -> str:
    """Taille du modèle Whisper, configurable (réglage DB 'whisper_model' ou env
    WHISPER_MODEL). Défaut = 'small' : nettement plus précis que 'base' en
    français, tout en restant fluide sur CPU pour des commandes vocales courtes.
    Choix possibles : tiny < base < small < medium < large-v3 (plus précis = plus lent)."""
    import os as _os
    try:
        s = db.get_setting("whisper_model")
        if s and str(s).strip():
            return str(s).strip()
    except Exception:
        pass
    return _os.getenv("WHISPER_MODEL", "small")


async def _get_whisper():
    """Charge le modèle Whisper une seule fois (lazy, thread-safe)."""
    global _whisper_model
    async with _whisper_lock:
        if _whisper_model is None:
            def _load():
                from faster_whisper import WhisperModel
                import os as _os
                size = _whisper_model_size()
                # CPU int8 : compromis précision/vitesse sûr (le GPU 4 Go est
                # partagé avec Ollama → on évite d'y charger Whisper).
                threads = min(8, (_os.cpu_count() or 4))
                try:
                    return WhisperModel(size, device="cpu", compute_type="int8",
                                        cpu_threads=threads, num_workers=1)
                except Exception:
                    # Repli sur 'base' si le modèle demandé ne se télécharge pas
                    return WhisperModel("base", device="cpu", compute_type="int8",
                                        cpu_threads=threads, num_workers=1)
            _whisper_model = await _asyncio.get_running_loop().run_in_executor(None, _load)
    return _whisper_model


async def _prewarm_whisper():
    """Pré-charge Whisper au démarrage pour éviter la latence de la 1ère requête."""
    try:
        await _asyncio.sleep(2)   # laisse le démarrage se faire d'abord
        await _get_whisper()
    except Exception:
        pass


@app.post("/api/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...), language: str = Form("fr")):
    """
    Reçoit un fichier audio (webm / wav / ogg / mp3) et retourne la transcription.
    Optimisé pour la VITESSE : décodage greedy (beam=1), langue forcée (par défaut
    français → pas de détection), pas de conditionnement sur le contexte.
    """
    import tempfile, os

    # Lire l'audio
    audio_bytes = await file.read()
    if len(audio_bytes) < 1000:
        raise HTTPException(status_code=400, detail="Fichier audio trop court ou vide")

    # Détecter l'extension depuis le content-type ou le nom de fichier
    ext = ".webm"
    if file.content_type:
        ct = file.content_type.lower()
        if "wav" in ct:    ext = ".wav"
        elif "ogg" in ct:  ext = ".ogg"
        elif "mp3" in ct or "mpeg" in ct: ext = ".mp3"
        elif "mp4" in ct:  ext = ".mp4"
        elif "webm" in ct: ext = ".webm"
    elif file.filename:
        _, fe = os.path.splitext(file.filename)
        if fe: ext = fe

    # Écrire dans un fichier temporaire
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        model = await _get_whisper()

        lang_req = (language or "fr").strip().lower()
        lang_arg = None if lang_req in ("auto", "", "detect") else lang_req

        # Amorce française : oriente le modèle vers une orthographe correcte,
        # avec accents et ponctuation (améliore nettement la précision en FR).
        _fr_prompt = ("Transcription en français, avec les accents et la ponctuation. "
                      "L'utilisateur parle à son assistant Marvin.")
        def _transcribe():
            segments, info = model.transcribe(
                tmp_path,
                beam_size=5,                    # recherche par faisceau → plus précis que greedy
                best_of=5,
                language=lang_arg,              # langue forcée → pas de passe de détection
                vad_filter=True,                # coupe les silences (moins d'audio à traiter)
                condition_on_previous_text=False,  # commandes courtes : évite la dérive
                initial_prompt=(_fr_prompt if (lang_arg in (None, "fr")) else None),
                no_speech_threshold=0.6,
                temperature=0.0,                # déterministe
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text, info.language

        text, lang = await _asyncio.get_running_loop().run_in_executor(None, _transcribe)

        return {
            "success": True,
            "text": text,
            "language": lang,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription échouée : {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Génération vidéo — Text-to-Video / Image-to-Video / Slideshow local
# ══════════════════════════════════════════════════════════════════════════════

import video_manager as _vm
import os as _os


@app.get("/api/video/models")
async def video_models():
    """Retourne les modèles disponibles pour text-to-video et image-to-video."""
    return {
        "text_to_video": _vm.TEXT_TO_VIDEO_MODELS,
        "image_to_video": _vm.IMAGE_TO_VIDEO_MODELS,
    }


class VideoGenerateTextRequest(BaseModel):
    model_key: str
    prompt: str
    extra_params: dict = Field(default_factory=dict)


@app.post("/api/video/generate/text")
async def video_generate_text(body: VideoGenerateTextRequest):
    """Lance une génération text-to-video sur Replicate et retourne le prediction_id."""
    import credentials_manager as cm

    model = _vm.TEXT_TO_VIDEO_MODELS.get(body.model_key)
    if not model:
        raise HTTPException(status_code=404, detail=f"Modèle inconnu : {body.model_key}")

    if model["provider"] == "replicate":
        api_token = cm.get_credential("replicate_api_token")
        if not api_token:
            raise HTTPException(
                status_code=400,
                detail="Token Replicate non configuré (Paramètres > Connexions)",
            )
        params = {**model["params"], "prompt": body.prompt, **body.extra_params}
        try:
            data = await _vm._replicate_start(model["model_id"], params, api_token)
            return {
                "success": True,
                "prediction_id": data["id"],
                "status": data.get("status", "starting"),
                "provider": "replicate",
                "model_name": model["name"],
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail=f"Provider non supporté : {model['provider']}")


@app.post("/api/video/generate/image")
async def video_generate_image(
    model_key: str = Form(...),
    prompt: str = Form(""),
    image: UploadFile = File(...),
):
    """Lance une génération image-to-video depuis un fichier image uploadé."""
    import credentials_manager as cm
    import tempfile

    model = _vm.IMAGE_TO_VIDEO_MODELS.get(model_key)
    if not model:
        raise HTTPException(status_code=404, detail=f"Modèle inconnu : {model_key}")

    # Déduire l'extension
    ext = ".jpg"
    if image.content_type:
        if "png"  in image.content_type: ext = ".png"
        elif "webp" in image.content_type: ext = ".webp"
        elif "gif"  in image.content_type: ext = ".gif"

    img_bytes = await image.read()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        img_uri = _vm.image_to_data_uri(tmp_path)

        if model["provider"] == "replicate":
            api_token = cm.get_credential("replicate_api_token")
            if not api_token:
                raise HTTPException(status_code=400, detail="Token Replicate non configuré")

            params = dict(model["params"])
            # Injecter l'image dans le champ attendu par le modèle
            for field in ("input_image", "image", "first_frame_image"):
                if field in params:
                    params[field] = img_uri
                    break
            if "prompt" in params:
                params["prompt"] = prompt

            data = await _vm._replicate_start(model["model_id"], params, api_token)
            return {
                "success": True,
                "prediction_id": data["id"],
                "status": data.get("status", "starting"),
                "provider": "replicate",
                "model_name": model["name"],
            }
        else:
            raise HTTPException(status_code=400, detail=f"Provider non supporté : {model['provider']}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass


@app.get("/api/video/status/{prediction_id}")
async def video_status_stream(prediction_id: str):
    """SSE : stream l'état d'une prédiction Replicate jusqu'à la fin."""
    import credentials_manager as cm

    api_token = cm.get_credential("replicate_api_token")
    if not api_token:
        raise HTTPException(status_code=400, detail="Token Replicate non configuré")

    async def generate():
        async for event in _vm.poll_replicate_sse(prediction_id, api_token):
            yield event

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/video/cancel/{prediction_id}")
async def video_cancel(prediction_id: str):
    """Annule une prédiction Replicate en cours."""
    import credentials_manager as cm
    api_token = cm.get_credential("replicate_api_token")
    if not api_token:
        raise HTTPException(status_code=400, detail="Token Replicate non configuré")
    await _vm._replicate_cancel(prediction_id, api_token)
    return {"success": True}


@app.post("/api/video/download")
async def video_download_url(request: Request):
    """Télécharge et sauvegarde une vidéo générée depuis une URL externe."""
    body = await request.json()
    url = body.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL requise")
    try:
        path = await _vm.download_video(url)
        filename = _os.path.basename(path)
        size = _os.path.getsize(path)
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "size_human": _vm._fmt_size(size),
            "url": f"/api/video/files/{filename}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/video/slideshow")
async def video_slideshow(
    images: list[UploadFile] = File(...),
    format: str = Form("gif"),
    duration: float = Form(2.0),
    transition_frames: int = Form(8),
    fps: int = Form(24),
    fade_duration: float = Form(0.5),
    width: int = Form(640),
    height: int = Form(480),
):
    """Crée un diaporama GIF ou MP4 depuis des images uploadées (100% local, sans API)."""
    import tempfile

    if not images:
        raise HTTPException(status_code=400, detail="Au moins une image requise")

    tmp_paths = []
    try:
        for img in images:
            img_bytes = await img.read()
            ext = ".jpg"
            if img.content_type:
                if "png"  in img.content_type: ext = ".png"
                elif "webp" in img.content_type: ext = ".webp"
                elif "gif"  in img.content_type: ext = ".gif"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_paths.append(tmp.name)

        resize_to = (width, height)

        if format.lower() == "mp4":
            out_path = await _asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _vm.create_slideshow_mp4(
                    tmp_paths,
                    duration_per_image=duration,
                    fps=fps,
                    resize_to=resize_to,
                    fade_duration=fade_duration,
                ),
            )
        else:
            out_path = await _asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _vm.create_slideshow_gif(
                    tmp_paths,
                    duration_per_frame=duration,
                    resize_to=resize_to,
                    transition_frames=transition_frames,
                ),
            )

        filename = _os.path.basename(out_path)
        size = _os.path.getsize(out_path)
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "size_human": _vm._fmt_size(size),
            "format": format.upper(),
            "url": f"/api/video/files/{filename}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p in tmp_paths:
            try:
                _os.unlink(p)
            except Exception:
                pass


class VideoTextAnimRequest(BaseModel):
    text: str
    style: str = "typewriter"     # typewriter | fade | scroll | title
    duration: float = 5.0
    fps: int = 24
    width: int = 854
    height: int = 480
    output_format: str = "mp4"    # mp4 | gif
    font_size: int = 40


@app.post("/api/video/text-animation")
async def video_text_animation(body: VideoTextAnimRequest):
    """Génère une vidéo animée depuis un texte (100% local, sans GPU ni API)."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Texte requis")
    try:
        out_path = await _asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _vm.create_text_animation_video(
                text=body.text,
                style=body.style,
                fps=body.fps,
                duration=body.duration,
                width=body.width,
                height=body.height,
                font_size=body.font_size,
                output_format=body.output_format,
            ),
        )
        filename = _os.path.basename(out_path)
        size = _os.path.getsize(out_path)
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "size_human": _vm._fmt_size(size),
            "format": _os.path.splitext(filename)[1].lstrip(".").upper(),
            "url": f"/api/video/files/{filename}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/video/files")
async def list_video_files():
    """Liste toutes les vidéos générées (MP4, GIF, WebM)."""
    files = _vm.list_generated_videos()
    return {"files": files, "count": len(files)}


@app.get("/api/video/files/{filename}")
async def serve_video_file(filename: str):
    """Sert un fichier vidéo généré (streaming HTTP)."""
    path = _vm.get_video_dir() / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    ext = path.suffix.lower()
    media_types = {
        ".mp4": "video/mp4",
        ".gif": "image/gif",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
    }
    return FileResponse(
        str(path),
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=filename,
    )


@app.delete("/api/video/files/{filename}")
async def delete_video_file(filename: str):
    """Supprime un fichier vidéo généré."""
    path = _vm.get_video_dir() / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    path.unlink()
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# v2.32 — Édition / Conversion vidéo & GIF (ffmpeg local, sans GPU ni API)
# ══════════════════════════════════════════════════════════════════════════════

def _video_edit_result(res: dict) -> dict:
    """Normalise un retour de video_manager → ajoute filename + url servable."""
    if not res or res.get("error"):
        raise HTTPException(status_code=500, detail=(res or {}).get("error", "Échec du traitement"))
    out = dict(res)
    path = res.get("path")
    if path:
        fn = _os.path.basename(path)
        out["filename"] = fn
        out["url"] = f"/api/video/files/{fn}"
    return out


@app.post("/api/video/edit")
async def video_edit(
    operation: str = Form(...),
    file: UploadFile = File(None),
    fps: float = Form(None),
    width: int = Form(None),
    height: int = Form(None),
    start: float = Form(None),
    end: float = Form(None),
    duration: float = Form(None),
    crf: int = Form(None),
    scale_width: int = Form(None),
    factor: float = Form(None),
    colors: int = Form(None),
    text: str = Form(None),
    position: str = Form("bottom-right"),
    font_size: int = Form(24),
    region: str = Form(None),       # "x,y,w,h"
    max_frames: int = Form(30),
):
    """
    Édition vidéo/GIF locale via ffmpeg (sans GPU ni API).
    operation ∈ {info, to_gif, gif_to_video, trim, compress, resize,
                 extract_frames, speed, watermark, optimize_gif, screen_record}
    Pour screen_record aucun fichier n'est requis.
    """
    import tempfile

    op = (operation or "").strip().lower()
    needs_file = op != "screen_record"
    tmp_path = None
    loop = _asyncio.get_running_loop()

    try:
        if needs_file:
            if file is None:
                raise HTTPException(status_code=400, detail="Fichier requis pour cette opération")
            data = await file.read()
            suffix = _os.path.splitext(file.filename or "")[1] or ".mp4"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

        if op == "info":
            res = await loop.run_in_executor(None, lambda: _vm.get_media_info(tmp_path))
            if res.get("error"):
                raise HTTPException(status_code=500, detail=res["error"])
            return {"success": True, **res}

        elif op == "to_gif":
            res = await loop.run_in_executor(None, lambda: _vm.video_to_gif(
                tmp_path, fps=int(fps) if fps else 12, width=width or 480,
                start=start, duration=duration))

        elif op == "gif_to_video":
            res = await loop.run_in_executor(None, lambda: _vm.gif_to_video(
                tmp_path, fps=int(fps) if fps else None))

        elif op == "trim":
            res = await loop.run_in_executor(None, lambda: _vm.video_trim(
                tmp_path, start=start or 0, end=end, duration=duration))

        elif op == "compress":
            res = await loop.run_in_executor(None, lambda: _vm.video_compress(
                tmp_path, crf=crf or 28, scale_width=scale_width))

        elif op == "resize":
            res = await loop.run_in_executor(None, lambda: _vm.video_resize(
                tmp_path, width=width, height=height))

        elif op == "extract_frames":
            res = await loop.run_in_executor(None, lambda: _vm.video_extract_frames(
                tmp_path, fps=fps or 1, max_frames=max_frames or 30))
            if res.get("error"):
                raise HTTPException(status_code=500, detail=res["error"])
            return {"success": True, **res}

        elif op == "speed":
            res = await loop.run_in_executor(None, lambda: _vm.video_speed(
                tmp_path, factor=factor or 2.0))

        elif op == "watermark":
            if not text:
                raise HTTPException(status_code=400, detail="Paramètre 'text' requis pour le filigrane")
            res = await loop.run_in_executor(None, lambda: _vm.video_add_watermark(
                tmp_path, text, position=position or "bottom-right", font_size=font_size or 24))

        elif op == "optimize_gif":
            res = await loop.run_in_executor(None, lambda: _vm.gif_optimize(
                tmp_path, fps=int(fps) if fps else 10, width=width, colors=colors or 128))

        elif op == "screen_record":
            reg = None
            if region:
                try:
                    reg = [int(x) for x in region.split(",")]
                except Exception:
                    reg = None
            res = await loop.run_in_executor(None, lambda: _vm.screen_record_gif(
                duration=min(duration or 5, 20), fps=int(fps) if fps else 10, region=reg))

        else:
            raise HTTPException(status_code=400, detail=f"Opération inconnue : {operation}")

        return _video_edit_result(res)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Génération vidéo LOCALE — CogVideoX / Wan 2.1 (HuggingFace Diffusers)
# ══════════════════════════════════════════════════════════════════════════════

import local_video as _lv


def _video_gen_allowed() -> bool:
    """La génération vidéo locale est-elle autorisée ? Pilotée par le MODE de performance
    (setting video_gen_enabled, calculé selon GPU). Par défaut : suit le support matériel."""
    v = db.get_setting("video_gen_enabled")
    if v is None:
        try:
            return bool(_lv.get_device_info().get("video_gen_supported"))
        except Exception:
            return False
    return bool(v)


def _video_gen_reason() -> str:
    try:
        info = _lv.get_device_info()
    except Exception:
        info = {}
    if not info.get("video_gen_supported"):
        return ("Génération vidéo locale indisponible sur ce matériel "
                f"({info.get('gpu') or info.get('vendor') or 'pas de GPU CUDA'}). "
                "Elle nécessite une carte NVIDIA/CUDA.")
    return ("Génération vidéo locale désactivée dans le mode de performance actuel. "
            "Passe en mode « Performance » ou « Maximum » (Mon jour → Auto-config) pour l'activer.")


@app.get("/api/video/local/models")
async def local_video_models():
    """Retourne les modèles locaux disponibles + infos device (CUDA/CPU/VRAM)."""
    status = _lv.get_models_status()
    if isinstance(status, dict):
        status["video_gen_enabled"] = _video_gen_allowed()
    return status


class LocalVideoTextRequest(BaseModel):
    model_key: str
    prompt: str
    num_steps: int | None = None   # None → défaut du modèle
    num_frames: int | None = None
    fps: int | None = None
    guidance: float | None = None
    duration: float | None = None   # durée cible en secondes (retime + interpolation)
    resolution: int | None = None   # 256 / 384 / 512 (qualité ↔ vitesse)
    seed: int | None = None         # graine (reproductibilité) ; None/-1 = aléatoire
    negative_prompt: str | None = None  # éléments à éviter


@app.post("/api/video/local/generate")
async def local_video_generate_text(body: LocalVideoTextRequest):
    """
    SSE : télécharge le modèle si absent, le charge en mémoire, génère et exporte en MP4.
    Progression : downloading → loading → processing (step N/N) → succeeded/error.
    """
    async def generate():
        import json as _j
        if not _video_gen_allowed():
            yield f"data: {_j.dumps({'status': 'error', 'error': _video_gen_reason()})}\n\n"
            return
        async for event in _lv.generate_video_local_sse(
            model_key=body.model_key,
            prompt=body.prompt,
            num_steps=body.num_steps,
            num_frames=body.num_frames,
            fps=body.fps,
            guidance=body.guidance,
            duration=body.duration,
            resolution=body.resolution,
            seed=body.seed,
            negative_prompt=body.negative_prompt,
        ):
            yield event

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/video/local/cancel")
async def local_video_cancel():
    """Demande l'annulation de la génération locale en cours (entre deux étapes)."""
    _lv.request_cancel()
    return {"success": True, "message": "Annulation demandée — arrêt à la prochaine étape."}


class PromptEnhanceRequest(BaseModel):
    prompt: str


@app.post("/api/video/enhance-prompt")
async def enhance_video_prompt(body: PromptEnhanceRequest):
    """
    ✨ Améliore un prompt vidéo via le LLM local (Ollama) :
    traduit en anglais (SD1.5 comprend mieux l'anglais) et l'enrichit en
    description cinématographique détaillée → bien meilleure adhérence au texte.
    """
    import httpx as _httpx
    from config import OLLAMA_URL
    raw = (body.prompt or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Prompt vide")

    sys_prompt = (
        "You are a prompt engineer for an AI text-to-video model (Stable Diffusion 1.5 based). "
        "Rewrite the user's idea into ONE single rich English prompt, optimized for video generation. "
        "Rules: translate to English; keep the user's subject and intent EXACTLY; add concrete visual "
        "details (lighting, camera angle, environment, mood, colors, style like 'cinematic, 4k, detailed'); "
        "describe motion suitable for a short clip; NO preamble, NO quotes, NO explanations, NO line breaks. "
        "Output ONLY the final prompt, under 60 words."
    )
    # Modèle rapide pour cette tâche courte
    candidates = ["qwen2.5:3b", "llama3.2:3b", "qwen2.5:7b", "hermes3:8b"]
    model = None
    try:
        async with _httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            avail = [m["name"] for m in r.json().get("models", [])] if r.status_code == 200 else []
        model = next((m for m in candidates if m in avail), (avail[0] if avail else None))
    except Exception:
        pass
    if not model:
        raise HTTPException(status_code=503, detail="Ollama indisponible pour l'amélioration du prompt")

    try:
        async with _httpx.AsyncClient(timeout=40.0) as c:
            resp = await c.post(f"{OLLAMA_URL}/api/chat", json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": raw},
                ],
                "stream": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.7, "num_predict": 160},
            })
        data = resp.json()
        enhanced = (data.get("message", {}) or {}).get("content", "").strip()
        # Nettoyage : retire guillemets/sauts de ligne éventuels
        enhanced = enhanced.strip().strip('"').strip("'").replace("\n", " ").strip()
        if not enhanced:
            raise ValueError("réponse vide")
        return {"success": True, "original": raw, "enhanced": enhanced, "model": model}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Échec de l'amélioration : {e}")


@app.post("/api/video/local/generate/image")
async def local_video_generate_image(
    model_key: str = Form(...),
    prompt: str = Form(""),
    num_steps: int | None = Form(None),   # None → défaut du modèle
    image: UploadFile = File(...),
):
    """SSE : génération image-to-video locale (CogVideoX-5B-I2V)."""
    import tempfile

    img_bytes = await image.read()
    ext = ".jpg"
    if image.content_type:
        if "png"  in image.content_type: ext = ".png"
        elif "webp" in image.content_type: ext = ".webp"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(img_bytes)
        tmp_path = tmp.name

    async def generate():
        import json as _j
        if not _video_gen_allowed():
            yield f"data: {_j.dumps({'status': 'error', 'error': _video_gen_reason()})}\n\n"
            return
        try:
            async for event in _lv.generate_video_local_sse(
                model_key=model_key,
                prompt=prompt,
                num_steps=num_steps,
                image_path=tmp_path,
            ):
                yield event
        finally:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Voix — Text-to-Speech (Edge-TTS neural voices, gratuit, sans clé API)
# ══════════════════════════════════════════════════════════════════════════════

# Voix françaises recommandées (toutes neurales, gratuites)
DEFAULT_TTS_VOICES = {
    "henri":    {"id": "fr-FR-HenriNeural",    "gender": "Male",   "label": "Henri (homme, voix professionnelle)"},
    "denise":   {"id": "fr-FR-DeniseNeural",   "gender": "Female", "label": "Denise (femme, voix naturelle)"},
    "eloise":   {"id": "fr-FR-EloiseNeural",   "gender": "Female", "label": "Eloïse (femme, voix douce)"},
    "vivienne": {"id": "fr-FR-VivienneMultilingualNeural", "gender": "Female", "label": "Vivienne (multilingue)"},
    "remy":     {"id": "fr-FR-RemyMultilingualNeural",    "gender": "Male",   "label": "Rémy (multilingue)"},
    "thierry":  {"id": "fr-CA-ThierryNeural",  "gender": "Male",   "label": "Thierry (Québec)"},
    "sylvie":   {"id": "fr-CA-SylvieNeural",   "gender": "Female", "label": "Sylvie (Québec)"},
}


class TTSRequest(BaseModel):
    text: str
    voice: str = "henri"
    rate: str = "+0%"
    pitch: str = "+0Hz"


@app.get("/api/voice/voices")
async def voice_list_voices():
    """Liste les voix françaises disponibles."""
    return {
        "voices": [{"key": k, **v} for k, v in DEFAULT_TTS_VOICES.items()],
        "default": "henri",
    }


@app.post("/api/voice/speak")
async def voice_speak(req: TTSRequest):
    """Génère un audio MP3 à partir d'un texte avec une voix française neurale (edge-tts)."""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Texte requis")

    voice_id = req.voice
    if voice_id in DEFAULT_TTS_VOICES:
        voice_id = DEFAULT_TTS_VOICES[voice_id]["id"]
    elif not voice_id.startswith(("fr-", "en-", "es-", "de-", "it-")):
        voice_id = DEFAULT_TTS_VOICES["henri"]["id"]

    text = req.text.strip()
    # Strip markdown bold/italic/code markers for cleaner speech
    import re as _re_tts
    text = _re_tts.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = _re_tts.sub(r"\*(.+?)\*", r"\1", text)
    text = _re_tts.sub(r"`([^`]+)`", r"\1", text)
    text = _re_tts.sub(r"#{1,6}\s+", "", text)
    text = _re_tts.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    if len(text) > 3000:
        text = text[:3000] + "…"

    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice_id, rate=req.rate, pitch=req.pitch)
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        audio_data = b"".join(audio_chunks)

        if not audio_data:
            raise HTTPException(status_code=500, detail="Aucun audio généré")

        return Response(
            content=audio_data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=marvin_voice.mp3",
                "Cache-Control": "no-cache",
                "X-Voice-Used": voice_id,
                "X-Audio-Size": str(len(audio_data)),
            },
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="edge-tts non installé. pip install edge-tts")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)[:200]}")


# ══════════════════════════════════════════════════════════════════════════════
# Devis / Facturation IT
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/billing/clients")
async def billing_clients_list(client_type: str = None):
    return {"clients": db.billing_client_list(client_type)}


@app.post("/api/billing/clients")
async def billing_clients_create(body: dict):
    if not body.get("name"):
        raise HTTPException(status_code=400, detail="Nom requis")
    return db.billing_client_create(body)


@app.get("/api/billing/clients/{cid}")
async def billing_clients_get(cid: str):
    client = db.billing_client_get(cid)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return client


@app.patch("/api/billing/clients/{cid}")
async def billing_clients_update(cid: str, body: dict):
    client = db.billing_client_update(cid, body)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return client


@app.delete("/api/billing/clients/{cid}")
async def billing_clients_delete(cid: str):
    db.billing_client_delete(cid)
    return {"success": True}


@app.get("/api/billing/quotes")
async def billing_quotes_list(client_id: str = None, status: str = None):
    return {"quotes": db.billing_quote_list(client_id, status)}


@app.post("/api/billing/quotes")
async def billing_quotes_create(body: dict):
    if not body.get("client_id"):
        raise HTTPException(status_code=400, detail="client_id requis")
    return db.billing_quote_create(body)


@app.get("/api/billing/quotes/{qid}")
async def billing_quotes_get(qid: str):
    quote = db.billing_quote_get(qid)
    if not quote:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    return quote


@app.patch("/api/billing/quotes/{qid}")
async def billing_quotes_update(qid: str, body: dict):
    quote = db.billing_quote_update(qid, body)
    if not quote:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    return quote


@app.delete("/api/billing/quotes/{qid}")
async def billing_quotes_delete(qid: str):
    db.billing_quote_delete(qid)
    return {"success": True}


@app.get("/api/billing/catalog")
async def billing_catalog_get(category: str = None):
    return {"services": db.billing_catalog_list(category)}


@app.post("/api/billing/catalog")
async def billing_catalog_add(body: dict):
    if not body.get("name"):
        raise HTTPException(status_code=400, detail="Nom requis")
    return db.billing_catalog_create(body)


@app.delete("/api/billing/catalog/{sid}")
async def billing_catalog_remove(sid: str):
    db.billing_catalog_delete(sid)
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# Agent IA Documentation Technique
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/docs/interventions")
async def docs_interventions_list(client_id: str = None, status: str = None, limit: int = 100):
    return {"interventions": db.doc_intervention_list(client_id, status, limit)}


@app.post("/api/docs/interventions")
async def docs_interventions_create(body: dict):
    if not body.get("title"):
        raise HTTPException(status_code=400, detail="Titre requis")
    return db.doc_intervention_create(body)


@app.get("/api/docs/interventions/{iid}")
async def docs_interventions_get(iid: str):
    interv = db.doc_intervention_get(iid)
    if not interv:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    return interv


@app.patch("/api/docs/interventions/{iid}")
async def docs_interventions_update(iid: str, body: dict):
    interv = db.doc_intervention_update(iid, body)
    if not interv:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    return interv


@app.delete("/api/docs/interventions/{iid}")
async def docs_interventions_delete(iid: str):
    db.doc_intervention_delete(iid)
    return {"success": True}


@app.get("/api/docs/documents")
async def docs_documents_list(intervention_id: str = None, client_id: str = None, doc_type: str = None):
    return {"documents": db.doc_document_list(intervention_id, client_id, doc_type)}


@app.delete("/api/docs/documents/{did}")
async def docs_documents_delete(did: str):
    db.doc_document_delete(did)
    return {"success": True}


@app.get("/api/docs/templates")
async def docs_templates_list(doc_type: str = None):
    return {"templates": db.doc_template_list(doc_type)}


@app.get("/api/docs/assets")
async def docs_assets_list(client_id: str = None):
    return {"assets": db.doc_asset_list(client_id)}


@app.post("/api/docs/assets")
async def docs_assets_create(body: dict):
    if not body.get("name"):
        raise HTTPException(status_code=400, detail="Nom requis")
    return db.doc_asset_create(body)


@app.delete("/api/docs/assets/{aid}")
async def docs_assets_delete(aid: str):
    db.doc_asset_delete(aid)
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# v2.30.0 — Operations Safety : routes REST
# ══════════════════════════════════════════════════════════════════════════════

# ── Pre/Post-Check ──
@app.get("/api/ops/checks")
async def ops_checks_list(intervention_id: str = None, check_type: str = None):
    return {"checks": db.ops_check_list(intervention_id, check_type)}


@app.get("/api/ops/checks/{cid}")
async def ops_checks_get(cid: str):
    check = db.ops_check_get(cid)
    if not check:
        raise HTTPException(status_code=404, detail="Checklist introuvable")
    return check


@app.delete("/api/ops/checks/{cid}")
async def ops_checks_delete(cid: str):
    db.ops_check_delete(cid)
    return {"success": True}


@app.get("/api/ops/evidence")
async def ops_evidence_list_route(intervention_id: str = None, check_id: str = None):
    return {"evidence": db.ops_evidence_list(intervention_id, check_id)}


# ── Command Safety ──
@app.get("/api/cmd/reviews")
async def cmd_reviews_list(intervention_id: str = None, risk_level: str = None, limit: int = 100):
    return {"reviews": db.cmd_review_list(intervention_id, risk_level, limit)}


@app.get("/api/cmd/rules")
async def cmd_rules_list_route():
    return {"rules": db.cmd_rules_list()}


@app.get("/api/cmd/approvals")
async def cmd_approvals_list(status: str = None):
    return {"approvals": db.approval_list(status)}


@app.post("/api/cmd/approvals/{aid}/decide")
async def cmd_approval_decide(aid: str, body: dict):
    decision = body.get("status", "approved")
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="status doit être 'approved' ou 'rejected'")
    res = db.approval_decide(aid, decision, body.get("approver", ""), body.get("reason", ""))
    if not res:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    return res


# ── Client Health Score ── (NB: /api/client-health pour éviter collision avec /api/health système)
@app.get("/api/client-health/{client_id}")
async def client_health_get_route(client_id: str):
    score = db.health_score_latest(client_id)
    return {"score": score}


@app.get("/api/client-health/{client_id}/history")
async def client_health_history_route(client_id: str, limit: int = 12):
    return {"history": db.health_score_history(client_id, limit)}


@app.get("/api/client-health/{client_id}/recommendations")
async def client_health_recos_route(client_id: str, status: str = None):
    return {"recommendations": db.health_recommendations_list(client_id, status)}


# ══════════════════════════════════════════════════════════════════════════════
# Santé
# ══════════════════════════════════════════════════════════════════════════════

_health_cache: dict = {}
_health_cache_lock = _asyncio.Lock()
_HEALTH_CACHE_TTL = 15.0   # refresh Ollama status every 15s

@app.get("/api/health")
async def health():
    import httpx as _httpx
    import time as _time
    from config import OLLAMA_URL

    global _health_cache

    now = _time.monotonic()
    # Return cached result if fresh enough (avoids 500ms+ on every status poll)
    if _health_cache and (now - _health_cache.get("_ts", 0)) < _HEALTH_CACHE_TTL:
        cached = dict(_health_cache)
        cached.pop("_ts", None)
        return cached

    async with _health_cache_lock:
        # Double-check after acquiring lock
        if _health_cache and (now - _health_cache.get("_ts", 0)) < _HEALTH_CACHE_TTL:
            cached = dict(_health_cache)
            cached.pop("_ts", None)
            return cached

        ollama_ok = False
        ollama_models = []
        try:
            async with _httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{OLLAMA_URL}/api/tags")
                if r.status_code == 200:
                    ollama_ok = True
                    data = r.json()
                    ollama_models = [m["name"] for m in data.get("models", [])]
        except Exception:
            # Repli : si le port d'Ollama répond, il est bien lancé (juste occupé/lent,
            # ex. inférence sur CPU ou chargement d'un modèle) -> on ne dit pas "offline" à tort.
            try:
                import socket as _socket
                _host = OLLAMA_URL.split("//")[-1].split("/")[0].split(":")[0] or "127.0.0.1"
                _port = int(OLLAMA_URL.rsplit(":", 1)[-1].split("/")[0])
                with _socket.create_connection((_host, _port), timeout=1.5):
                    ollama_ok = True
            except Exception:
                pass

        result = {
            "status":          "ok",
            "ollama":          ollama_ok,
            "ollama_models":   ollama_models,
            "backend":         "python-fastapi",
            "version":         "2.150.0",
            "tools_count":     len(tool_module.TOOLS_REGISTRY),
            "tools_spec_count": len(tool_module.TOOLS_SPEC),
        }
        _health_cache = {**result, "_ts": now}
        return result
