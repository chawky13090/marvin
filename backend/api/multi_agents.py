"""Exécution parallèle d'outils, avec réponse groupée ou streaming SSE."""

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import tools as tool_module
import api_errors


router = APIRouter(tags=["multi-agents"])


class AgentTask(BaseModel):
    id: str
    tool_name: str
    args: dict = Field(default_factory=dict)
    label: str = ""


class AgentRunRequest(BaseModel):
    tasks: list[AgentTask]


async def _run_one(task: AgentTask) -> dict:
    started = datetime.now()
    try:
        function = tool_module.TOOLS_REGISTRY.get(task.tool_name)
        if function is None:
            return {
                "id": task.id,
                "tool_name": task.tool_name,
                "label": task.label,
                "success": False,
                "result": {"error": f"Outil inconnu : {task.tool_name}"},
                "duration_ms": 0,
            }
        result = await function(task.args)
        duration = int((datetime.now() - started).total_seconds() * 1000)
        return {
            "id": task.id,
            "tool_name": task.tool_name,
            "label": task.label,
            "success": "error" not in result,
            "result": result,
            "duration_ms": duration,
        }
    except Exception as error:
        duration = int((datetime.now() - started).total_seconds() * 1000)
        return {
            "id": task.id,
            "tool_name": task.tool_name,
            "label": task.label,
            "success": False,
            "result": api_errors.safe_failure(
                "multi_agent_tool",
                error,
                "Exécution de l'outil impossible.",
            ),
            "duration_ms": duration,
        }


@router.post("/api/agents/parallel")
async def agents_parallel(body: AgentRunRequest):
    started = datetime.now()
    results = await asyncio.gather(*[_run_one(task) for task in body.tasks])
    return {
        "total_ms": int((datetime.now() - started).total_seconds() * 1000),
        "count": len(results),
        "results": results,
    }


@router.post("/api/agents/parallel/stream")
async def agents_parallel_stream(body: AgentRunRequest):
    async def generate():
        started = datetime.now()
        queue: asyncio.Queue = asyncio.Queue()

        async def run_and_enqueue(task: AgentTask):
            await queue.put(await _run_one(task))

        pending = {
            asyncio.create_task(run_and_enqueue(task))
            for task in body.tasks
        }
        completed = 0
        total = len(body.tasks)
        while completed < total:
            item = await queue.get()
            completed += 1
            payload = json.dumps(
                {
                    "event": "task_done",
                    "completed": completed,
                    "total": total,
                    **item,
                }
            )
            yield f"data: {payload}\n\n"
        await asyncio.gather(*pending)
        total_ms = int((datetime.now() - started).total_seconds() * 1000)
        yield f"data: {json.dumps({'event': 'all_done', 'total_ms': total_ms, 'count': total})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
