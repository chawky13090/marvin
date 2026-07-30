"""Workers de maintenance du processus Marvin.

Ce module contient uniquement les boucles de fond transverses qui n'appartiennent
pas a une route HTTP. Les temporisations et comportements historiques sont
conserves; le cycle de vie est gere par :mod:`runtime_supervisor`.
"""

from __future__ import annotations

import asyncio
import time

import database as db
import tools as tool_module


async def prewarm_default_models() -> None:
    """Precharge les profils agent et chat sans bloquer le demarrage FastAPI."""
    import httpx

    import cloud_routing
    from config import MODEL_PROFILES, OLLAMA_URL

    cloud_enabled, _cloud_overrides = cloud_routing.get_cloud_config()
    if cloud_enabled and not cloud_routing.is_local_only_lockdown():
        print(
            "[Marvin] Ollama Cloud actif : modèles locaux disponibles à la demande, "
            "sans préchargement RAM."
        )
        return

    models_to_warm = [
        MODEL_PROFILES.get("agent", {}).get("model", "qwen2.5:7b"),
        MODEL_PROFILES.get("chat", {}).get("model", "qwen2.5:3b"),
    ]
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=120.0) as client:
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
                        "keep_alive": "30m",
                        "options": {"num_predict": 1},
                    },
                )
                print(f"[Marvin] Modele '{model}' precharge en memoire")
            except Exception as exc:
                print(f"[Marvin] Prechargement '{model}' echoue : {exc}")


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
