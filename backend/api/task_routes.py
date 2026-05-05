"""BackendTestForge API routes — task management."""

import json
import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models import AgentRun, LoadTestResult, Task, async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ── Request/Response Models ──

class TaskCreateRequest(BaseModel):
    name: str
    project_path: str
    startup_mode: str = "direct"
    startup_config: str = ""
    feature_name: str = ""


class TaskResponse(BaseModel):
    id: int
    name: str
    project_path: str
    startup_mode: str
    startup_config: str | None
    feature_name: str | None
    status: str
    error_message: str | None
    created_at: str
    updated_at: str
    agent_runs: list[dict] = []


# ── Routes ──

@router.post("", response_model=TaskResponse)
async def create_task(req: TaskCreateRequest):
    """Create a new test task."""
    # Validate project path
    if not req.project_path:
        raise HTTPException(status_code=400, detail="项目路径不能为空")
    
    if not os.path.isdir(req.project_path):
        raise HTTPException(
            status_code=400, 
            detail=f"项目路径不存在或不是目录: {req.project_path}"
        )
    
    # Validate startup config if in direct mode
    if req.startup_mode == "direct" and not req.startup_config:
        raise HTTPException(
            status_code=400, 
            detail="direct 模式下必须提供目标 URL (startup_config)"
        )
    
    async with async_session() as session:
        task = Task(
            name=req.name,
            project_path=req.project_path,
            startup_mode=req.startup_mode,
            startup_config=req.startup_config,
            feature_name=req.feature_name or None,
            status="pending",
            cancel_requested=0,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return _task_to_response(task)


@router.get("", response_model=list[TaskResponse])
async def list_tasks(limit: int = 20, offset: int = 0):
    """List all tasks, most recent first."""
    from sqlalchemy import desc, select
    async with async_session() as session:
        result = await session.execute(
            select(Task).order_by(desc(Task.created_at)).offset(offset).limit(limit)
        )
        tasks = result.scalars().all()
        return [_task_to_response(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int):
    """Get a single task with its agent runs."""
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        runs_result = await session.execute(
            select(AgentRun).where(AgentRun.task_id == task_id).order_by(AgentRun.id)
        )
        agent_runs = runs_result.scalars().all()
        return _task_to_response(task, list(agent_runs))


@router.post("/{task_id}/run")
async def run_task(task_id: int):
    """Trigger task execution. Returns immediately; task runs async."""
    from backend.agents.orchestrator import run_orchestrator
    import asyncio
    
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        if task.status not in ["pending", "completed", "failed", "cancelled"]:
            raise HTTPException(status_code=400, detail="Task is already running")
    
    asyncio.create_task(run_orchestrator(task_id))
    return {"message": "Task started", "task_id": task_id}


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: int):
    """Request cancellation of a running task."""
    from backend.agents.orchestrator import _set_cancel_requested
    
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        if task.status != "running":
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot cancel task with status: {task.status}"
            )
    
    await _set_cancel_requested(task_id, True)
    return {"message": "Task cancellation requested", "task_id": task_id}


@router.get("/{task_id}/load-results")
async def get_load_test_results(task_id: int):
    """Get load test results for a task."""
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(
            select(LoadTestResult)
            .where(LoadTestResult.task_id == task_id)
            .order_by(LoadTestResult.created_at.desc())
            .limit(1)
        )
        ltr = result.scalar_one_or_none()
        if not ltr:
            return {"task_id": task_id, "has_results": False}
        return {
            "task_id": task_id,
            "has_results": True,
            "max_concurrency": ltr.max_concurrency,
            "qps_avg": ltr.qps_avg,
            "latency_p50": ltr.latency_p50,
            "latency_p95": ltr.latency_p95,
            "latency_p99": ltr.latency_p99,
            "error_rate": ltr.error_rate,
            "curve_data": json.loads(ltr.curve_data_json) if ltr.curve_data_json else [],
            "bottleneck": ltr.bottleneck,
        }


@router.put("/{task_id}/endpoints")
async def update_task_endpoints(task_id: int, endpoints: list[dict]):
    """
    Manually set API endpoints for a task (code parsing degradation fallback).
    Body: [{"method": "GET", "path": "/users"}, ...]
    """
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(
            select(AgentRun)
            .where(AgentRun.task_id == task_id)
            .where(AgentRun.agent_name == "code_parser")
            .order_by(AgentRun.id.desc())
            .limit(1)
        )
        run = result.scalar_one_or_none()
        if not run:
            placeholder = {
                "tech_stack": {"language": "Manual", "framework": "Manual", "confidence": "low"},
                "routes_from_grep": endpoints,
                "key_files_count": 0,
                "key_files": [],
            }
            new_run = AgentRun(
                task_id=task_id,
                agent_name="code_parser",
                status="completed",
                result_json=json.dumps(placeholder),
            )
            session.add(new_run)
        else:
            existing = json.loads(run.result_json) if run.result_json else {}
            existing["routes_from_grep"] = endpoints
            existing["tech_stack"] = existing.get("tech_stack", {})
            existing["tech_stack"]["confidence"] = "manual"
            run.result_json = json.dumps(existing)
        await session.commit()
    return {"message": f"Updated {len(endpoints)} endpoints for task {task_id}"}


# ── Helpers ──

def _task_to_response(task: Task, agent_runs: list | None = None) -> TaskResponse:
    runs_data = []
    if agent_runs is not None:
        for ar in agent_runs:
            runs_data.append({
                "id": ar.id,
                "agent_name": ar.agent_name,
                "status": ar.status,
                "result_json": ar.result_json,
                "error_message": ar.error_message,
                "started_at": ar.started_at.isoformat() if ar.started_at else None,
                "ended_at": ar.ended_at.isoformat() if ar.ended_at else None,
            })
    return TaskResponse(
        id=task.id,
        name=task.name,
        project_path=task.project_path,
        startup_mode=task.startup_mode,
        startup_config=task.startup_config,
        feature_name=task.feature_name,
        status=task.status,
        error_message=task.error_message,
        created_at=task.created_at.isoformat() if task.created_at else "",
        updated_at=task.updated_at.isoformat() if task.updated_at else "",
        agent_runs=runs_data,
    )
