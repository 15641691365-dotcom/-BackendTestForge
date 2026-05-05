"""
LangGraph orchestrator for BackendTestForge.

Flow: parse_code → run_load_test → build_report
"""

import json
import logging
from datetime import datetime
from typing import Optional

from backend.api.ws_manager import ws_manager
from backend.models import AgentRun, Task, async_session
from backend.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


# ── State ──

class AgentState(dict):
    """Shared state passed between pipeline nodes."""
    task_id: int = 0
    project_path: str = ""
    startup_mode: str = "direct"
    startup_config: str = ""
    feature_name: str = ""
    code_parse_result: Optional[dict] = None
    load_test_result: Optional[dict] = None
    report_result: Optional[dict] = None
    error: Optional[str] = None
    status: str = "running"


# ── Helpers ──

async def _start_agent_run(task_id: int, agent_name: str) -> int:
    async with async_session() as session:
        run = AgentRun(
            task_id=task_id,
            agent_name=agent_name,
            status="running",
            started_at=datetime.now(),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


async def _finish_agent_run(run_id: int, result: dict = None, error: str = None):
    async with async_session() as session:
        from sqlalchemy import select
        obj = await session.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = obj.scalar_one_or_none()
        if run:
            run.status = "failed" if error else "completed"
            run.ended_at = datetime.now()
            if result:
                run.result_json = json.dumps(result, default=str)
            if error:
                run.error_message = error
            await session.commit()


async def _update_task_status(task_id: int, status: str, error: str = None):
    async with async_session() as session:
        from sqlalchemy import select
        obj = await session.execute(select(Task).where(Task.id == task_id))
        task = obj.scalar_one_or_none()
        if task:
            task.status = status
            if error:
                task.error_message = error
            task.updated_at = datetime.now()
            await session.commit()


async def _check_cancel_requested(task_id: int) -> bool:
    """Check if task cancellation has been requested."""
    async with async_session() as session:
        from sqlalchemy import select
        obj = await session.execute(select(Task).where(Task.id == task_id))
        task = obj.scalar_one_or_none()
        return task and bool(task.cancel_requested)


async def _set_cancel_requested(task_id: int, value: bool = True):
    """Set task cancellation flag."""
    async with async_session() as session:
        from sqlalchemy import select
        obj = await session.execute(select(Task).where(Task.id == task_id))
        task = obj.scalar_one_or_none()
        if task:
            task.cancel_requested = 1 if value else 0
            await session.commit()


# ── Nodes ──

async def parse_code_node(state: AgentState) -> AgentState:
    """Run the CodeParser agent."""
    task_id = state["task_id"]
    project_path = state["project_path"]
    feature_name = state.get("feature_name", "")

    # ── Skip parsing if a completed code_parser run already exists ──
    async with async_session() as session:
        from sqlalchemy import select as sel
        existing = await session.execute(
            sel(AgentRun).where(
                AgentRun.task_id == task_id,
                AgentRun.agent_name == "code_parser",
                AgentRun.status == "completed",
            ).order_by(AgentRun.id.desc()).limit(1)
        )
        existing_run = existing.scalar_one_or_none()
        if existing_run and existing_run.result_json:
            parsed = json.loads(existing_run.result_json)
            routes = parsed.get("routes_from_grep", [])
            state["code_parse_result"] = parsed
            await ws_manager.send_agent_event(
                task_id, "code_parser", "agent_done",
                result={
                    "tech_stack": parsed.get("tech_stack"),
                    "routes_count": len(routes),
                    "files_analyzed": parsed.get("key_files_count", 0),
                    "note": "Reused existing code_parser result",
                }
            )
            logger.info(f"Task {task_id}: reused existing code_parser result ({len(routes)} routes)")
            return state

    await ws_manager.send_agent_event(task_id, "code_parser", "agent_start")
    run_id = await _start_agent_run(task_id, "code_parser")

    try:
        from backend.agents.code_parser import parse_project
        from backend.config import config

        llm_client = None
        if config.LLM_API_KEY:
            llm_client = LLMClient(
                provider=config.LLM_PROVIDER,
                api_key=config.LLM_API_KEY,
                base_url=config.LLM_BASE_URL,
                model=config.LLM_MODEL,
            )

        await ws_manager.send_agent_event(
            task_id, "code_parser", "agent_progress",
            message="Scanning project directory..."
        )

        # Check for cancellation before starting
        if await _check_cancel_requested(task_id):
            await _finish_agent_run(run_id, error="Task cancelled")
            await ws_manager.send_agent_event(task_id, "code_parser", "agent_failed", error="Task cancelled")
            state["error"] = "Task cancelled"
            state["status"] = "cancelled"
            return state

        result = await parse_project(project_path, llm_client)

        # Filter routes by feature name if specified
        if feature_name:
            from backend.agents.code_parser import llm_filter_routes
            original_count = len(result.get("routes_from_grep", []))
            result["routes_from_grep"] = await llm_filter_routes(
                result.get("routes_from_grep", []),
                feature_name=feature_name,
                tech_stack=result.get("tech_stack", {}),
                llm_client=llm_client,
            )
            filtered_count = len(result.get("routes_from_grep", []))
        else:
            original_count = len(result.get("routes_from_grep", []))
            filtered_count = original_count

        await ws_manager.send_agent_event(
            task_id, "code_parser", "agent_progress",
            message=f"Found {original_count} routes"
                    + (f", filtered to {filtered_count} for feature '{feature_name}'" if feature_name else "")
                    + f", stack: {result.get('tech_stack', {}).get('language', 'unknown')}"
        )

        await _finish_agent_run(run_id, result=result)
        await ws_manager.send_agent_event(
            task_id, "code_parser", "agent_done",
            result={
                "tech_stack": result.get("tech_stack"),
                "routes_count": len(result.get("routes_from_grep", [])),
                "files_analyzed": result.get("key_files_count", 0),
            }
        )

        state["code_parse_result"] = result
        return state

    except Exception as e:
        logger.exception(f"CodeParser failed for task {task_id}")
        await _finish_agent_run(run_id, error=str(e))
        await ws_manager.send_agent_event(task_id, "code_parser", "agent_failed", error=str(e))
        state["error"] = str(e)
        state["status"] = "failed"
        return state


async def run_load_test_node(state: AgentState) -> AgentState:
    """Run the LoadTester agent: k6 load test against the provided URL."""
    task_id = state["task_id"]
    code_result = state.get("code_parse_result") or {}
    tech_stack = code_result.get("tech_stack") or {}
    endpoints = code_result.get("routes_from_grep", [])
    target_url = state.get("startup_config", "")

    await ws_manager.send_agent_event(task_id, "load_tester", "agent_start")
    run_id = await _start_agent_run(task_id, "load_tester")

    try:
        from backend.agents.load_tester import run_load_test
        from backend.config import config

        llm_client = None
        if config.LLM_API_KEY:
            llm_client = LLMClient(
                provider=config.LLM_PROVIDER,
                api_key=config.LLM_API_KEY,
                base_url=config.LLM_BASE_URL,
                model=config.LLM_MODEL,
            )

        await ws_manager.send_agent_event(
            task_id, "load_tester", "agent_progress",
            message=f"Testing {len(endpoints)} endpoints at {target_url}..."
        )

        # Check for cancellation before starting
        if await _check_cancel_requested(task_id):
            await _finish_agent_run(run_id, error="Task cancelled")
            await ws_manager.send_agent_event(task_id, "load_tester", "agent_failed", error="Task cancelled")
            state["error"] = "Task cancelled"
            state["status"] = "cancelled"
            return state

        result = await run_load_test(
            endpoints=endpoints,
            tech_stack=tech_stack,
            target_url=target_url,
            llm_client=llm_client,
        )

        await _finish_agent_run(run_id, result=result)

        analysis = result.get("analysis", {})
        await ws_manager.send_agent_event(
            task_id, "load_tester", "agent_done",
            result={
                "max_safe_concurrency": analysis.get("max_safe_concurrency", 0),
                "bottleneck_detected": analysis.get("bottleneck_detected", False),
                "summary": analysis.get("summary", ""),
                "steps_completed": len(result.get("step_results", [])),
            }
        )

        state["load_test_result"] = result

        if result.get("status") == "failed":
            state["error"] = result.get("error", "Load test failed")
            state["status"] = "failed"
            return state

        return state

    except Exception as e:
        logger.exception(f"LoadTester failed for task {task_id}")
        await _finish_agent_run(run_id, error=str(e))
        await ws_manager.send_agent_event(task_id, "load_tester", "agent_failed", error=str(e))
        state["error"] = str(e)
        state["status"] = "failed"
        return state


async def build_report_node(state: AgentState) -> AgentState:
    """Run the DocBuilder agent: generate report and fix document."""
    task_id = state["task_id"]

    await ws_manager.send_agent_event(task_id, "doc_builder", "agent_start")
    run_id = await _start_agent_run(task_id, "doc_builder")

    try:
        from backend.agents.doc_builder import run_doc_builder
        from backend.config import config

        llm_client = None
        if config.LLM_API_KEY:
            llm_client = LLMClient(
                provider=config.LLM_PROVIDER,
                api_key=config.LLM_API_KEY,
                base_url=config.LLM_BASE_URL,
                model=config.LLM_MODEL,
            )

        await ws_manager.send_agent_event(
            task_id, "doc_builder", "agent_progress",
            message="Generating report and fix document..."
        )

        code_result = state.get("code_parse_result") or {}
        load_result = state.get("load_test_result") or {}

        result = await run_doc_builder(
            task_id=task_id,
            code_parse_result=code_result,
            load_test_result=load_result,
            task_info={
                "name": f"Task #{task_id}",
                "project_path": state.get("project_path", ""),
                "created_at": datetime.now().isoformat(),
            },
            llm_client=llm_client,
        )

        await _finish_agent_run(run_id, result={
            "overview": result.get("overview"),
            "metrics": result.get("metrics"),
            "fix_document_preview": result.get("fix_document", "")[:500],
        })

        await ws_manager.send_agent_event(
            task_id, "doc_builder", "agent_done",
            result={
                "overall_grade": result.get("overview", {}).get("overall_grade", "N/A"),
                "issues_count": result.get("fix_document", "").count("### ["),
            }
        )

        state["report_result"] = result
        return state

    except Exception as e:
        logger.exception(f"DocBuilder failed for task {task_id}")
        await _finish_agent_run(run_id, error=str(e))
        await ws_manager.send_agent_event(task_id, "doc_builder", "agent_failed", error=str(e))
        # Report failure is non-critical; task can still complete
        state["report_result"] = {"error": str(e)}
        return state


# ── Runner ──

async def run_orchestrator(task_id: int):
    """
    Execute the full orchestration pipeline.
    parse_code → run_load_test → build_report → completed
    """
    logger.info(f"Orchestrator starting: task={task_id}")

    async with async_session() as session:
        from sqlalchemy import select
        obj = await session.execute(select(Task).where(Task.id == task_id))
        task = obj.scalar_one_or_none()
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        state = AgentState(
            task_id=task_id,
            project_path=task.project_path,
            startup_mode=task.startup_mode,
            startup_config=task.startup_config or "",
            feature_name=task.feature_name or "",
            status="running",
        )

    await _update_task_status(task_id, "running")

    try:
        # Step 1: Parse code
        state = await parse_code_node(state)
        if state.get("error"):
            if state.get("status") == "cancelled":
                await _update_task_status(task_id, "cancelled", "Task cancelled by user")
                await ws_manager.send_task_done(task_id, "cancelled")
            else:
                await _update_task_status(task_id, "failed", state["error"])
                await ws_manager.send_task_done(task_id, "failed")
            return

        # Step 2: Run load test
        state = await run_load_test_node(state)
        if state.get("error"):
            if state.get("status") == "cancelled":
                await _update_task_status(task_id, "cancelled", "Task cancelled by user")
                await ws_manager.send_task_done(task_id, "cancelled")
            else:
                await _update_task_status(task_id, "failed", state["error"])
                await ws_manager.send_task_done(task_id, "failed")
            return

        # Step 3: Build report and fix document
        state = await build_report_node(state)

        # Done
        await _update_task_status(task_id, "completed")
        await ws_manager.send_task_done(task_id, "completed")
        logger.info(f"Task {task_id} completed successfully")

        # Save load test results to separate table
        from backend.models import LoadTestResult
        load_result = state.get("load_test_result") or {}
        analysis = load_result.get("analysis") or {}
        step_results = load_result.get("step_results", [])

        if analysis:
            async with async_session() as session:
                ltr = LoadTestResult(
                    task_id=task_id,
                    max_concurrency=analysis.get("max_safe_concurrency", 0),
                    qps_avg=step_results[-1].get("qps", 0) if step_results else 0,
                    latency_p50=step_results[-1].get("p50", 0) if step_results else 0,
                    latency_p95=step_results[-1].get("p95", 0) if step_results else 0,
                    latency_p99=step_results[-1].get("p99", 0) if step_results else 0,
                    error_rate=step_results[-1].get("error_rate", 0) if step_results else 0,
                    curve_data_json=json.dumps(step_results, default=str),
                    bottleneck=analysis.get("summary", ""),
                )
                session.add(ltr)
                await session.commit()

    except Exception as e:
        logger.exception(f"Orchestrator error for task {task_id}")
        await _update_task_status(task_id, "failed", str(e))
        await ws_manager.send_task_done(task_id, "failed")
