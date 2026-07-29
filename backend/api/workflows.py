"""CRUD et moteur d'exécution des workflows d'outils Marvin."""

import asyncio
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import database as db
import api_errors
import tool_runtime


router = APIRouter(tags=["workflows"])


class WorkflowStep(BaseModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    tool_name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_]+$")
    args: dict = Field(default_factory=dict)
    label: str = Field(default="", max_length=300)
    enabled: bool = True
    when: str | None = Field(default=None, max_length=1_000)
    retries: int = Field(default=0, ge=0, le=3)
    continue_on_error: bool = False
    save_as: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    steps: list[WorkflowStep] = Field(default_factory=list, max_length=50)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    steps: list[WorkflowStep] | None = Field(default=None, max_length=50)


@router.get("/api/workflows")
async def list_workflows():
    return db.list_workflows()


@router.post("/api/workflows")
async def create_workflow(body: WorkflowCreate):
    return db.create_workflow(
        body.name,
        body.description,
        [step.model_dump() for step in body.steps],
    )


@router.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    workflow = db.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow introuvable")
    return workflow


@router.put("/api/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, body: WorkflowUpdate):
    updates = body.model_dump(exclude_none=True)
    if "steps" in updates:
        updates["steps"] = [step.model_dump() for step in body.steps or []]
    workflow = db.update_workflow(workflow_id, updates)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow introuvable")
    return workflow


@router.delete("/api/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    db.delete_workflow(workflow_id)
    return {"success": True}


@router.get("/api/workflows/{workflow_id}/runs")
async def list_workflow_runs(workflow_id: str, limit: int = 20):
    return db.list_workflow_runs(workflow_id, limit=limit)


def _lookup(context: dict, path: str):
    current = context
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except Exception:
                return ""
        else:
            return ""
        if current is None:
            return ""
    return current


def _resolve(value, context: dict):
    if isinstance(value, str):
        full_match = re.fullmatch(r"\s*\{\{([^}]+)\}\}\s*", value)
        if full_match:
            return _lookup(context, full_match.group(1).strip())
        return re.sub(
            r"\{\{([^}]+)\}\}",
            lambda match: str(_lookup(context, match.group(1).strip())),
            value,
        )
    if isinstance(value, dict):
        return {key: _resolve(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, context) for item in value]
    return value


def _condition(expression, context: dict) -> bool:
    if expression in (None, "", True):
        return True
    if expression is False:
        return False
    resolved = _resolve(expression, context) if isinstance(expression, str) else expression
    if isinstance(resolved, str):
        match = re.match(r"^(.*?)\s*(==|!=|>=|<=|>|<)\s*(.*)$", resolved.strip())
        if match:
            left = match.group(1).strip().strip('"\'')
            operator = match.group(2)
            right = match.group(3).strip().strip('"\'')
            try:
                left, right = float(left), float(right)
            except ValueError:
                left, right = left.lower(), right.lower()
            return {
                "==": left == right,
                "!=": left != right,
                ">": left > right,
                "<": left < right,
                ">=": left >= right,
                "<=": left <= right,
            }.get(operator, True)
        return resolved.strip().lower() not in ("", "false", "0", "none", "null", "no")
    return bool(resolved)


@router.post("/api/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str):
    workflow = db.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow introuvable")

    run_id = db.create_workflow_run(workflow_id)["id"]
    started = datetime.now()
    step_results = []
    overall_success = True
    context = {"prev": {}, "vars": {}}

    for index, step in enumerate(workflow.get("steps", []), start=1):
        if not step.get("enabled", True):
            step_results.append(
                {"step_id": step["id"], "skipped": True, "tool_name": step["tool_name"]}
            )
            continue
        if not _condition(step.get("when"), context):
            step_results.append(
                {
                    "step_id": step["id"],
                    "tool_name": step["tool_name"],
                    "skipped": True,
                    "reason": "condition non remplie",
                }
            )
            continue

        tool_name = step["tool_name"]
        args = _resolve(dict(step.get("args", {})), context)
        retries = min(max(int(step.get("retries", 0) or 0), 0), 3)
        continue_on_error = bool(step.get("continue_on_error", False))
        step_started = datetime.now()
        result = None
        success = False

        for attempt in range(retries + 1):
            try:
                outcome = await tool_runtime.execute(
                    tool_name,
                    args,
                    source="workflow",
                    conversation_id=f"workflow:{run_id}",
                    request_id=f"workflow:{run_id}:{step['id']}:{attempt + 1}",
                )
                result = outcome.result
                success = outcome.executed and not (
                    isinstance(result, dict) and result.get("error")
                )
                if success:
                    break
            except Exception as error:
                result = api_errors.safe_failure(
                    "workflow_tool",
                    error,
                    "Exécution de l'étape impossible.",
                )
            if attempt < retries:
                await asyncio.sleep(min(2 ** attempt, 5))

        entry = {
            "step_id": step["id"],
            "tool_name": tool_name,
            "args": args,
            "result": result,
            "success": success,
            "duration_ms": int((datetime.now() - step_started).total_seconds() * 1000),
            "attempts": attempt + 1,
        }
        step_results.append(entry)
        context["prev"] = entry
        context[f"step{index}"] = entry
        if step.get("save_as"):
            context["vars"][step["save_as"]] = result
            context[step["save_as"]] = entry
        if not success and not continue_on_error:
            overall_success = False
            break

    total_ms = int((datetime.now() - started).total_seconds() * 1000)
    status = "success" if overall_success else "failed"
    db.finish_workflow_run(run_id, status, step_results, total_ms)
    db.update_workflow(
        workflow_id,
        {
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_status": status,
            "run_count": True,
        },
    )
    return {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "status": status,
        "duration_ms": total_ms,
        "steps_results": step_results,
    }
