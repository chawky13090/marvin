"""Workers de maintenance du processus Marvin.

Ce module contient uniquement les boucles de fond transverses qui n'appartiennent
pas a une route HTTP. Les temporisations et comportements historiques sont
conserves; le cycle de vie est gere par :mod:`runtime_supervisor`.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

import database as db
import tools as tool_module


async def prewarm_default_models() -> None:
    """Precharge les profils agent et chat sans bloquer le demarrage FastAPI."""
    import httpx

    import cloud_routing
    import ollama_context_admission
    from config import MODEL_PROFILES, OLLAMA_URL

    cloud_enabled, _cloud_overrides = cloud_routing.get_cloud_config()
    if cloud_enabled and not cloud_routing.is_local_only_lockdown():
        print(
            "[Marvin] Ollama Cloud actif : modèles locaux disponibles à la demande, "
            "sans préchargement RAM."
        )
        return

    models_to_warm = [
        MODEL_PROFILES.get("agent", {}).get("model", ""),
        MODEL_PROFILES.get("chat", {}).get("model", ""),
    ]
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=120.0) as client:
        for model in models_to_warm:
            if not model or model in seen:
                continue
            seen.add(model)
            try:
                admission = await ollama_context_admission.admit_local_context(
                    model,
                    mission_id=f"prewarm-{model}",
                    ollama_url=OLLAMA_URL,
                )
                if admission.status == "blocked":
                    print(f"[Marvin] Prechargement '{model}' bloque par Forge")
                    continue
                await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "."}],
                        "stream": False,
                        "keep_alive": "30m",
                        "options": {
                            "num_predict": 1,
                            **admission.request_options(),
                        },
                    },
                )
                print(f"[Marvin] Modele '{model}' precharge en memoire")
            except Exception as exc:
                print(f"[Marvin] Prechargement '{model}' echoue : {exc}")


def context_recalibration_eligibility(
    reason: str,
    *,
    loaded_model_count: int,
    available_ram_bytes: int,
    projected_resident_bytes: int,
) -> tuple[bool, str]:
    """Décision pure : la calibration ne doit jamais concurrencer un usage réel."""

    recalibratable = {
        "verified_profile_missing",
        "profile_schema_stale",
        "machine_or_driver_drift",
        "model_tag_drift",
        "model_digest_drift",
        "ollama_version_drift",
        "profile_not_verified",
        "profile_selection_missing",
        "profile_below_objective",
    }
    if reason not in recalibratable:
        return False, "profile_not_recalibratable"
    if loaded_model_count:
        return False, "ollama_models_are_resident"
    required = max(int(projected_resident_bytes * 1.15), projected_resident_bytes) + 1024**3
    if available_ram_bytes < required:
        return False, "host_memory_headroom_insufficient"
    return True, "idle_resources_available"


async def ollama_context_recalibration_worker() -> None:
    """Répare en arrière-plan un profil périmé, uniquement lorsque le poste est idle."""

    await asyncio.sleep(300)
    import httpx

    import ollama_context_admission
    from config import DATA_DIR, MODEL_PROFILES, OLLAMA_URL, PROJECT_DIR
    from structured_logging import StructuredJsonlStore

    store = StructuredJsonlStore.from_environment(
        DATA_DIR / "logs" / "ollama-context-recalibration.jsonl",
        component="ollama_context_recalibration",
        prefix="OLLAMA_RECALIBRATION",
        default_retention_days=30,
    )
    profile_path = DATA_DIR / "install" / "ollama-context-profile.json"
    lock_path = DATA_DIR / "install" / ".ollama-context-calibration.lock"
    while True:
        outcome = "deferred"
        reason = "unknown"
        started = time.monotonic()
        try:
            if os.getenv("MARVIN_FORGE_RUNTIME_LOCK"):
                reason = "forge_campaign_active"
            else:
                model = str(MODEL_PROFILES.get("agent", {}).get("model") or "")
                decision = await ollama_context_admission.admit_local_context(
                    model,
                    mission_id=f"background-calibration-{time.monotonic_ns()}",
                    ollama_url=OLLAMA_URL,
                )
                profile: dict = {}
                try:
                    profile = json.loads(profile_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
                selected_context = int((profile.get("selected") or {}).get("context_tokens") or 0)
                objective_context = auto_config.context_objective_tokens(auto_config.detect_hardware())
                if decision.status == "admitted" and selected_context >= objective_context:
                    outcome, reason = "success", "profile_current"
                elif decision.status == "admitted":
                    reason = "profile_below_objective"
                elif decision.reason in {"runtime_inspection_unavailable", "runtime_memory_pressure"}:
                    reason = decision.reason
                else:
                    reason = decision.reason
                if outcome != "success" and reason not in {
                    "runtime_inspection_unavailable",
                    "runtime_memory_pressure",
                }:
                    async with httpx.AsyncClient(timeout=8.0) as client:
                        ps_response = await client.get(f"{OLLAMA_URL.rstrip('/')}/api/ps")
                        ps_response.raise_for_status()
                        loaded = ps_response.json().get("models") or []
                    hardware = auto_config.detect_hardware()
                    available = int(float(hardware.get("ram_available_gb") or 0) * 1024**3)
                    projected = 6 * 1024**3
                    projected = int((profile.get("selected") or {}).get("projected_resident_bytes") or projected)
                    eligible, reason = context_recalibration_eligibility(
                        reason,
                        loaded_model_count=len(loaded),
                        available_ram_bytes=available,
                        projected_resident_bytes=projected,
                    )
                    if eligible:
                        lock_path.parent.mkdir(parents=True, exist_ok=True)
                        if (
                            lock_path.exists()
                            and time.time() - lock_path.stat().st_mtime > 7200
                        ):
                            lock_path.unlink(missing_ok=True)
                        try:
                            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        except FileExistsError:
                            reason = "calibration_already_running"
                        else:
                            os.close(descriptor)
                            try:
                                command = [
                                    sys.executable,
                                    str(PROJECT_DIR / "scripts" / "calibrate-ollama-context.py"),
                                    "--model",
                                    model,
                                    "--ollama-url",
                                    OLLAMA_URL,
                                    "--verify",
                                    "--install-profile",
                                    "--repetitions",
                                    "5",
                                ]
                                completed = await asyncio.to_thread(
                                    subprocess.run,
                                    command,
                                    capture_output=True,
                                    text=True,
                                    errors="replace",
                                    timeout=1200,
                                    creationflags=0x08000000 if os.name == "nt" else 0,
                                    check=False,
                                )
                                outcome = "success" if completed.returncode == 0 else "failure"
                                reason = "profile_recalibrated" if completed.returncode == 0 else "calibrator_failed"
                            finally:
                                lock_path.unlink(missing_ok=True)
        except Exception as exc:
            outcome, reason = "failure", type(exc).__name__
        store.write(
            "ollama.context.recalibration",
            severity="ERROR" if outcome == "failure" else "INFO",
            outcome=outcome,
            attributes={
                "reason": reason,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
        await asyncio.sleep(3600)


async def build_tool_index() -> None:
    """Construit une fois l'index semantique des descriptions d'outils."""
    await asyncio.sleep(8)
    try:
        import tool_router

        ready = await tool_router.ensure_tool_index(tool_module.TOOLS_SPEC)
        message = "Index semantique des outils pret" if ready else "Index outils indisponible"
        print(f"[Marvin] {message}")
    except Exception as exc:
        print(f"[Marvin] Index outils echoue : {exc}")


async def skill_night_learning_worker() -> None:
    """Consolide le journal d'apprentissage des competences a intervalle borne."""
    await asyncio.sleep(45)
    last_run = 0.0
    while True:
        try:
            now_hour = time.localtime().tm_hour
            interval = 900 if now_hour >= 22 or now_hour <= 6 else 1500
            if time.time() - last_run >= interval:
                last_run = time.time()
                import skills

                async def generate(prompt: str) -> str:
                    return await tool_module._ollama_generate(prompt, model=None, timeout=180)

                # v2.517 — la liste réelle des outils borne ce que le LLM peut citer ;
                # sans elle, la consolidation inventait des noms d'outils inexistants.
                real_tool_names = [
                    spec.get("function", {}).get("name")
                    for spec in tool_module.TOOLS_SPEC
                    if spec.get("function", {}).get("name")
                ]
                consolidated = 0
                for skill in skills.list_skills():
                    if len(skills.get_learning_log(8, skill["name"])) < 2:
                        continue
                    if await skills.review_and_consolidate_learnings(
                        generate, skill["name"], tool_names=real_tool_names
                    ):
                        consolidated += 1
                if consolidated:
                    print(f"[Marvin] Consolidation nocturne : {consolidated} competence(s).")
                forgotten = skills.consolidate_obsolete_skills()
                if forgotten:
                    print(f"[Marvin] Competences archivees (inactives) : {forgotten}")
        except Exception as exc:
            print(f"[Marvin] Consolidation nocturne echouee : {exc}")
        await asyncio.sleep(60)


async def database_backup_worker() -> None:
    """Cree une sauvegarde SQLite au demarrage puis toutes les vingt-quatre heures."""
    await asyncio.sleep(20)
    import backup

    while True:
        try:
            result = backup.create_backup()
            if result.get("success"):
                print(
                    "[Marvin] Sauvegarde DB valide "
                    f"({result['size_kb']} Ko)"
                )
            else:
                print(
                    "[Marvin] Sauvegarde DB echouee "
                    f"({result.get('error_code', 'unknown')})"
                )
        except Exception as exc:
            print(
                "[Marvin] Sauvegarde DB echouee "
                f"({type(exc).__name__})"
            )
        await asyncio.sleep(86400)


async def memory_consolidation_worker() -> None:
    """Fusionne quotidiennement les doublons de memoire par regles deterministes."""
    await asyncio.sleep(40)
    import memory_consolidation
    import memory_lifecycle

    while True:
        try:
            lifecycle = await memory_lifecycle.prune_expired()
            result = await memory_consolidation.consolidate_memories()
            if lifecycle.get("forgotten_count"):
                print(
                    "[Marvin] Rétention mémoire appliquée : "
                    f"{lifecycle['forgotten_count']} souvenir(s) expiré(s)."
                )
            if result.get("merged_count"):
                print(f"[Marvin] Memoire consolidee : {result['merged_count']} doublon(s).")
        except Exception as exc:
            print(f"[Marvin] Consolidation memoire echouee : {exc}")
        await asyncio.sleep(86400)


async def health_trend_worker() -> None:
    """Enregistre quotidiennement un instantane de sante du poste."""
    await asyncio.sleep(60)
    while True:
        try:
            result = await tool_module.capture_system_snapshot()
            print(f"[Marvin] Instantane de sante enregistre ({result.get('id', '?')[:8]}).")
        except Exception as exc:
            print(f"[Marvin] Instantane de sante echoue : {exc}")
        await asyncio.sleep(86400)
