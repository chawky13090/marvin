"""Finalisation idempotente d'une compétence utilisée par le Runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class SkillOutcomeRecorder:
    """Enregistre une seule issue par tour et programme l'amélioration si nécessaire."""

    recorded: bool = False

    def finalize(
        self,
        *,
        skill: dict[str, Any] | None,
        runner_state: Any,
        user_query: str,
        final_content: str,
        tools_spec: list[dict[str, Any]],
        background_tasks: set[asyncio.Task],
        encode_sse: Callable[[dict[str, Any]], str],
        skills_module: Any | None = None,
        tools_module: Any | None = None,
    ) -> str | None:
        if self.recorded or not (skill and skill.get("tools")):
            return None
        self.recorded = True

        try:
            if skills_module is None:
                import skills as skills_module
            if tools_module is None:
                import tools as tools_module

            executed = runner_state.tool_count
            succeeded = runner_state.succeeded
            detail = (
                f"{runner_state.failed_tools} erreur(s) d'outil "
                f"sur {executed} appel(s)."
            )
            trace = (
                "Demande: "
                + (user_query or "")[:300]
                + "\n"
                + "\n".join(runner_state.trace[-14:])
                + "\nRéponse finale: "
                + (final_content or "")[:400]
            )
            skill_name = skill["name"]
            skills_module.record_outcome(
                skill_name,
                succeeded,
                detail,
                transcript=trace,
            )

            if (
                succeeded
                and runner_state.successful_tools > 0
                and runner_state.successful_calls
            ):
                try:
                    skills_module.record_success_trace(
                        skill_name,
                        runner_state.successful_calls,
                        user_query,
                    )
                except Exception:
                    pass

            if not succeeded:
                tool_names = [
                    item.get("function", {}).get("name")
                    for item in tools_spec
                    if item.get("function", {}).get("name")
                ]

                async def auto_upgrade() -> None:
                    async def generate(prompt: str) -> str:
                        return await tools_module._ollama_generate(
                            prompt,
                            model=None,
                            timeout=240,
                        )

                    await skills_module.upgrade_skill(
                        skill_name,
                        generate,
                        reason=detail,
                        transcript=trace,
                        tool_names=tool_names,
                    )

                task = asyncio.create_task(auto_upgrade())
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                return encode_sse(
                    {
                        "type": "skill_upgrade",
                        "skill": skill_name,
                        "message": (
                            f"🔧 Compétence « {skill_name} » : un outil a échoué — "
                            "auto-amélioration en arrière-plan."
                        ),
                    }
                )
        except Exception:
            pass
        return None
