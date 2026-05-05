"""
LoadTester Agent — 阶梯压测 + 拐点检测 + 瓶颈分析。

工作流：
1. 接收 CodeParser 的输出（API routes + tech stack）
2. 通过 ProjectManager 启动被测服务
3. 使用 K6Runner 执行阶梯压测
4. 检测拐点（错误率 > 1% 或 P99 > 1000ms）
5. 调用 LLM 分析瓶颈
6. 停止被测服务
"""

import json
import logging
from typing import Optional

from backend.services.k6_runner import K6Runner
from backend.services.project_manager import ProjectManager

logger = logging.getLogger(__name__)


# Thresholds
MAX_ERROR_RATE = 0.01   # 1%
MAX_P99_MS = 500        # 500ms for P99 (warning level)
CRITICAL_P99_MS = 1000  # 1000ms for P99 (critical, stop)


async def run_load_test(
    endpoints: list[dict],
    tech_stack: dict,
    target_url: str,
    llm_client=None,
) -> dict:
    """
    Execute the full load test pipeline against an already-running service.

    Args:
        endpoints: List of {method, path, sample_body} dicts
        tech_stack: Dict with language, framework, entry_point, etc.
        target_url: Base URL of the already-running service (e.g. http://localhost:8001)
        llm_client: Optional LLM client for bottleneck analysis

    Returns:
        Dict with load test results
    """
    handle = None

    try:
        # Step 1: Verify the target service is reachable
        base_url = target_url.rstrip("/")
        if not base_url:
            return _error_result("No target URL provided")

        logger.info(f"Testing against {base_url}")
        healthy = await ProjectManager.health_check_only(base_url, timeout=10)
        if not healthy:
            return _error_result(f"Service at {base_url} is not responding")

        logger.info(f"Service running at {base_url}")

        # Step 2: Run step load test
        from backend.services.k6_runner import DEFAULT_STEPS
        runner = K6Runner()
        steps = DEFAULT_STEPS

        # Filter endpoints to only include safe (GET) endpoints for load testing
        # POST/PUT/DELETE might have side effects on real databases
        safe_endpoints = _prepare_endpoints(endpoints)

        if not safe_endpoints:
            # Use health check as fallback
            safe_endpoints = [{"method": "GET", "path": "/health", "sample_body": {}}]

        logger.info(f"Starting step load test with {len(safe_endpoints)} endpoints")

        step_results = await runner.run_step_load(
            base_url=base_url,
            endpoints=safe_endpoints,
            framework=tech_stack.get("framework", ""),
            steps=steps,
        )

        # Step 3: Analyze results
        analysis = _analyze_load_results(step_results)

        # Step 4: LLM bottleneck analysis (if client provided)
        bottleneck_analysis = None
        if llm_client and analysis.get("bottleneck_detected"):
            try:
                bottleneck_analysis = await _call_bottleneck_llm(
                    llm_client, step_results, analysis, base_url
                )
            except Exception as e:
                logger.warning(f"Bottleneck LLM analysis failed: {e}")
                bottleneck_analysis = {"error": str(e)}

        return {
            "status": "completed",
            "base_url": base_url,
            "step_results": step_results,
            "analysis": analysis,
            "bottleneck_analysis": bottleneck_analysis,
            "endpoints_tested": len(safe_endpoints),
        }

    except Exception as e:
        logger.exception(f"Load test failed: {e}")
        return _error_result(str(e))

    finally:
        logger.info(f"Test completed against {base_url}")


def _prepare_endpoints(endpoints: list[dict]) -> list[dict]:
    """
    Prepare endpoints for load testing.
    All HTTP methods participate equally — no GET bias.
    POST/PUT/DELETE endpoints are included at full weight,
    since this system is designed for testing environments.
    """
    if not endpoints:
        return []

    return list(endpoints)


def _analyze_load_results(step_results: list[dict]) -> dict:
    """Analyze step load test results to find bottlenecks."""
    if not step_results:
        return {
            "max_safe_concurrency": 0,
            "recommended_concurrency": 0,
            "bottleneck_detected": False,
            "bottleneck_at_step": None,
            "summary": "No results",
        }

    max_safe = 0
    recommended = 0
    bottleneck_detected = False
    bottleneck_at_step = None
    bottleneck_reason = ""

    for i, step in enumerate(step_results):
        vus = step.get("vus", 0)
        error_rate = step.get("error_rate", 0)
        p99 = step.get("p99", 0)
        qps = step.get("qps", 0)

        is_bottleneck = (
            error_rate > MAX_ERROR_RATE or p99 > CRITICAL_P99_MS
        )

        if not is_bottleneck:
            max_safe = vus
        elif not bottleneck_detected:
            bottleneck_detected = True
            bottleneck_at_step = i
            reasons = []
            if error_rate > MAX_ERROR_RATE:
                reasons.append(f"error_rate={error_rate:.2%}")
            if p99 > CRITICAL_P99_MS:
                reasons.append(f"p99={p99:.0f}ms")
            bottleneck_reason = "; ".join(reasons)

    recommended = max_safe  # In MVP, recommended = max safe

    # Build summary
    if len(step_results) == 1:
        summary = f"Single step: {step_results[0].get('vus', 0)} VUs, QPS={step_results[0].get('qps', 0):.0f}"
    elif bottleneck_detected:
        summary = (
            f"Bottleneck at {step_results[bottleneck_at_step].get('vus', 0)} VUs: "
            f"{bottleneck_reason}. "
            f"Max safe concurrency: {max_safe} VUs"
        )
    else:
        last = step_results[-1]
        summary = (
            f"All {len(step_results)} steps passed. "
            f"Max tested: {last.get('vus', 0)} VUs, "
            f"QPS={last.get('qps', 0):.0f}, "
            f"P99={last.get('p99', 0):.0f}ms"
        )

    return {
        "max_safe_concurrency": max_safe,
        "recommended_concurrency": recommended,
        "bottleneck_detected": bottleneck_detected,
        "bottleneck_at_step": bottleneck_at_step,
        "bottleneck_reason": bottleneck_reason,
        "summary": summary,
    }


async def _call_bottleneck_llm(
    llm_client, step_results: list[dict], analysis: dict, base_url: str
) -> list[dict]:
    """Call LLM to analyze bottleneck causes."""
    steps_json = json.dumps(step_results, indent=2, default=str)

    prompt = f"""Analyze these load test results and identify the most likely bottleneck causes.

## Load Test Results
{steps_json}

## Analysis
- Max safe concurrency: {analysis.get('max_safe_concurrency')} VUs
- Bottleneck detected: {analysis.get('bottleneck_detected')}
- Bottleneck reason: {analysis.get('bottleneck_reason', 'N/A')}

Based on the latency and error rate patterns, identify:
1. What is the most likely bottleneck (database, CPU, memory, network, connection pool, etc.)?
2. What specific changes would you recommend to fix it?
3. What is the expected improvement after each fix?

Output as a JSON array of {{location, issue, severity, fix, expected_improvement}} objects.
Sort by severity (critical first).
"""

    result_json = await llm_client.chat_json([
        {"role": "system", "content": "You are a performance engineering expert. Output only valid JSON."},
        {"role": "user", "content": prompt},
    ])

    if isinstance(result_json, list):
        return result_json
    return [result_json]


def _error_result(error: str) -> dict:
    """Build a failed result."""
    return {
        "status": "failed",
        "error": error,
        "step_results": [],
        "analysis": {
            "max_safe_concurrency": 0,
            "recommended_concurrency": 0,
            "bottleneck_detected": False,
            "bottleneck_at_step": None,
            "summary": f"Failed: {error}",
        },
        "bottleneck_analysis": None,
    }
