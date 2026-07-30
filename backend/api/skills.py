"""API des compétences Markdown apprenantes de Marvin."""

from fastapi import APIRouter, Body, File, HTTPException, UploadFile

import database as db
import api_errors
import skills
import tools as tool_module


router = APIRouter(tags=["skills"])


def _tool_names() -> list[str]:
    return [tool["function"]["name"] for tool in tool_module.TOOLS_SPEC]


async def _generate(prompt: str) -> str:
    return await tool_module._ollama_generate(prompt, model=None, timeout=240)


@router.get("/api/skills")
async def get_skills():
    return {"skills": skills.list_skills()}


@router.post("/api/skills")
async def save_skill_endpoint(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nom de la skill requis.")
    filename = skills.save_skill(
        name,
        (body.get("description") or "").strip(),
        body.get("body") or "",
        body.get("tools") or [],
        bool(body.get("enabled", True)),
        triggers=body.get("triggers") or [],
        related=body.get("related") or [],
    )
    skills.log_learning_event(
        "create",
        name,
        "Créée manuellement par l'utilisateur",
        after=body.get("body"),
    )
    return {"success": True, "file": filename}


@router.delete("/api/skills/{name}")
async def delete_skill_endpoint(name: str):
    return {"success": skills.delete_skill(name)}


@router.post("/api/skills/generate")
async def generate_skill_endpoint(body: dict = Body(...)):
    description = (body.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="Décris ce que la skill doit faire.")
    tool_names = _tool_names()
    prompt = (
        "Tu crées une COMPÉTENCE (skill) AGENTIQUE pour l'assistant Marvin. Une skill = une MÉTHODE "
        "robuste en langage naturel que Marvin suivra avec ses outils existants (PAS de code).\n"
        "RÉDIGE TOUT EN FRANÇAIS (seuls les noms d'outils restent en anglais).\n"
        f"Besoin de l'utilisateur : « {description} »\n\n"
        f"Outils disponibles (choisis-en quelques-uns de pertinents) : {', '.join(tool_names[:120])}\n\n"
        "RÈGLE CLÉ : les étapes décrivent ce que MARVIN fait avec SES OUTILS (entre backticks), "
        "JAMAIS des manipulations manuelles de l'utilisateur. Choisis toujours au moins un outil "
        "pertinent dans 'tools'.\n"
        "Le body Markdown contient : ## Objectif · ## Prérequis · ## Étapes · ## Vérification · "
        "## Pièges à éviter.\n\n"
        "Réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni balises de code :\n"
        '{"name":"nom-court-kebab","description":"quand utiliser cette skill",'
        '"triggers":["expressions déclencheuses"],"tools":["outil1"],'
        '"body":"## Objectif\\n...\\n## Prérequis\\n...\\n## Étapes\\n1. ...\\n'
        '## Vérification\\n...\\n## Pièges à éviter\\n- ..."}'
    )
    try:
        raw = await _generate(prompt)
    except Exception as error:
        return api_errors.safe_failure(
            "skill_generate",
            error,
            "Génération de la compétence impossible.",
            success=False,
        )
    data = skills.parse_skill_json(raw)
    if not data.get("name"):
        return {
            "success": False,
            "error": "Génération impossible, reformule la description.",
            "raw": raw[:300],
        }
    filename = skills.save_skill(
        data["name"],
        data.get("description", description),
        data.get("body", ""),
        [name for name in data.get("tools") or [] if name in tool_names],
        True,
        triggers=[str(trigger)[:40] for trigger in data.get("triggers") or []][:8],
    )
    skills.log_learning_event(
        "auto_create",
        data["name"],
        f"Générée depuis une description : « {description[:150]} »",
        after=data.get("body"),
    )
    return {"success": True, "file": filename, "skill": skills.get_skill(data["name"])}


@router.post("/api/skills/from-conversation")
async def skill_from_conversation(body: dict = Body(...)):
    lines = []
    for message in (body.get("messages") or [])[-30:]:
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if content and role in ("user", "assistant"):
            lines.append(
                f"{'Utilisateur' if role == 'user' else 'Marvin'}: {str(content)[:800]}"
            )
    transcript = "\n".join(lines)
    if len(transcript) < 40:
        return {
            "success": False,
            "error": "Conversation trop courte pour en tirer une compétence.",
        }
    tool_names = _tool_names()
    prompt = (
        "À partir de la CONVERSATION ci-dessous, crée une COMPÉTENCE RÉUTILISABLE pour Marvin : "
        "la méthode généralisée qui a permis d'accomplir la tâche. RÉDIGE EN FRANÇAIS. "
        "Les étapes décrivent ce que MARVIN fait avec SES OUTILS, jamais des manipulations "
        "manuelles de l'utilisateur. Ignore les étapes ratées et garde ce qui fonctionne.\n\n"
        f"CONVERSATION :\n{transcript}\n\n"
        f"Outils disponibles : {', '.join(tool_names[:120])}\n\n"
        "Réponds UNIQUEMENT en JSON valide, sans balises de code :\n"
        '{"name":"nom-court-kebab","description":"quand utiliser cette compétence",'
        '"triggers":["expressions déclencheuses"],"tools":["outil1"],'
        '"body":"## Objectif\\n...\\n## Étapes\\n1. ...\\n## Vérification\\n..."}'
    )
    try:
        raw = await _generate(prompt)
    except Exception as error:
        return api_errors.safe_failure(
            "skill_generate_conversation",
            error,
            "Génération de la compétence impossible.",
            success=False,
        )
    data = skills.parse_skill_json(raw)
    if not data.get("name"):
        return {
            "success": False,
            "error": "Impossible d'extraire une compétence de cette conversation.",
        }
    filename = skills.save_skill(
        data["name"],
        data.get("description", ""),
        data.get("body", ""),
        [name for name in data.get("tools") or [] if name in tool_names],
        True,
        triggers=[str(trigger)[:40] for trigger in data.get("triggers") or []][:8],
    )
    skills.log_learning_event(
        "auto_create",
        data["name"],
        "Extraite d'une conversation réussie",
        after=data.get("body"),
    )
    return {"success": True, "file": filename, "skill": skills.get_skill(data["name"])}


@router.get("/api/skills/stats")
async def skills_stats():
    return {"stats": skills.get_stats()}


@router.post("/api/skills/{name}/upgrade")
async def skill_upgrade(name: str, body: dict = Body(default={})):
    reason = (body or {}).get(
        "reason",
        "Amélioration manuelle demandée par l'utilisateur.",
    )
    transcript = (body or {}).get("transcript", "")

    async def generate(prompt: str):
        return await _generate(prompt)

    return await skills.upgrade_skill(
        name,
        generate,
        reason=reason,
        transcript=transcript,
        tool_names=_tool_names(),
    )


@router.get("/api/skills/{name}/versions")
async def skill_versions(name: str):
    return {"versions": skills.list_versions(name), "stats": skills.get_stats(name)}


@router.post("/api/skills/{name}/rollback")
async def skill_rollback(name: str, body: dict = Body(...)):
    version_file = (body or {}).get("version_file")
    if not version_file:
        raise HTTPException(status_code=400, detail="version_file requis.")
    success = skills.rollback_skill(name, version_file)
    return {"success": success, "skill": skills.get_skill(name) if success else None}


@router.get("/api/skills/{name}/resources")
async def skill_resources_list(name: str):
    return {"resources": skills.list_resources(name)}


@router.post("/api/skills/{name}/resources")
async def skill_resource_save(name: str, body: dict = Body(...)):
    if not skills.get_skill(name):
        raise HTTPException(status_code=404, detail="Compétence introuvable.")
    filename = (body or {}).get("filename", "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="filename requis.")
    if "." not in filename:
        filename += ".md"
    return skills.save_resource(name, filename, (body or {}).get("content", ""))


@router.post("/api/skills/{name}/resources/upload")
async def skill_resource_upload(name: str, file: UploadFile = File(...)):
    if not skills.get_skill(name):
        raise HTTPException(status_code=404, detail="Compétence introuvable.")
    return skills.save_resource(
        name,
        file.filename or "ressource",
        await file.read(),
    )


@router.get("/api/skills/{name}/resources/{filename}")
async def skill_resource_get(name: str, filename: str):
    return {
        "name": filename,
        "content": skills.read_resource(name, filename, max_chars=20000),
        "path": skills.resource_path(name, filename),
    }


@router.delete("/api/skills/{name}/resources/{filename}")
async def skill_resource_delete(name: str, filename: str):
    return {"success": skills.delete_resource(name, filename)}


@router.post("/api/skills/suggest")
async def skills_suggest(body: dict = Body(default={})):
    limit = int((body or {}).get("limit", 120))
    messages = db.get_recent_user_messages(limit=limit)

    async def generate(prompt: str):
        return await _generate(prompt)

    suggestions = await skills.suggest_skills(
        generate,
        messages,
        tool_names=_tool_names(),
    )
    return {"suggestions": suggestions, "analyzed": len(messages)}


@router.post("/api/skills/suggest/dismiss")
async def skills_suggest_dismiss(body: dict = Body(...)):
    name = (body or {}).get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name requis.")
    skills.dismiss_suggestion(name)
    return {"success": True}


@router.get("/api/skills/learning_log")
async def skills_learning_log(limit: int = 50, skill: str | None = None):
    return {"log": skills.get_learning_log(limit=limit, skill_name=skill)}


@router.get("/api/skills/match_log")
async def skills_match_log(limit: int = 50):
    return {"log": skills.get_match_log(limit=limit)}


@router.get("/api/skills/overlaps")
async def skills_overlaps(threshold: float = 0.85):
    return {
        "pairs": await skills.find_overlapping_skills(threshold=threshold),
        "threshold": threshold,
    }


@router.post("/api/skills/consolidate")
async def skills_consolidate(body: dict = Body(default={})):
    async def generate(prompt: str):
        return await _generate(prompt)

    reviewed = await skills.review_and_consolidate_learnings(
        generate,
        skill_name=(body or {}).get("skill"),
        tool_names=_tool_names(),
    )
    return {
        "reviewed": reviewed,
        "forgotten": skills.consolidate_obsolete_skills(),
    }
