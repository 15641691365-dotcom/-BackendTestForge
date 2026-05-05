"""
DocBuilder Agent — 汇总测试结果，生成可视化报告 + AI 可读修复文档。

工作流：
1. 接收 CodeParser 和 LoadTester 的输出
2. 整理数据指标
3. 调用 LLM 生成修复文档（问题描述 + 修复方案 + 预期效果）
4. 输出结构化报告和 Markdown 文档
"""

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


async def build_report(
    code_parse_result: dict,
    load_test_result: dict,
    task_info: dict,
    llm_client=None,
) -> dict:
    """
    Build a comprehensive report from all agent results.

    Args:
        code_parse_result: Output from CodeParser
        load_test_result: Output from LoadTester
        task_info: {name, project_path, created_at}
        llm_client: Optional LLM client for generating fix document

    Returns:
        Dict with report data and fix document
    """
    tech_stack = code_parse_result.get("tech_stack") or {}
    routes = code_parse_result.get("routes_from_grep", [])
    analysis = load_test_result.get("analysis") or {}
    step_results = load_test_result.get("step_results", [])
    bottleneck_analysis = load_test_result.get("bottleneck_analysis")

    # Build summary metrics
    metrics = _build_metrics(step_results, analysis)

    # Build overview
    overview = _build_overview(task_info, tech_stack, routes, metrics)

    # Generate fix document via LLM (or fallback template)
    if llm_client and step_results:
        try:
            fix_document = await _generate_fix_document(
                llm_client, metrics, tech_stack, routes, step_results, bottleneck_analysis
            )
        except Exception as e:
            logger.warning(f"LLM fix document generation failed: {e}")
            fix_document = _build_fallback_fix_document(metrics, tech_stack, bottleneck_analysis)
    else:
        fix_document = _build_fallback_fix_document(metrics, tech_stack, bottleneck_analysis)

    return {
        "overview": overview,
        "metrics": metrics,
        "step_results": step_results,
        "bottleneck_analysis": bottleneck_analysis,
        "fix_document": fix_document,
        "generated_at": datetime.now().isoformat(),
    }


def _build_metrics(step_results: list[dict], analysis: dict) -> dict:
    """Extract key metrics from step results."""
    if not step_results:
        return {
            "max_concurrency": 0,
            "qps_avg": 0,
            "latency_p50": 0,
            "latency_p95": 0,
            "latency_p99": 0,
            "error_rate": 0,
            "max_safe_concurrency": 0,
            "recommended_concurrency": 0,
            "bottleneck_summary": analysis.get("summary", "No data"),
        }

    # Use the last successful step's metrics
    last = step_results[-1] if step_results else {}
    safe = analysis.get("max_safe_concurrency", 0)

    return {
        "max_concurrency": last.get("vus", 0),
        "qps_avg": round(last.get("qps", 0), 1),
        "latency_p50": round(last.get("p50", 0), 1),
        "latency_p95": round(last.get("p95", 0), 1),
        "latency_p99": round(last.get("p99", 0), 1),
        "error_rate": round(last.get("error_rate", 0) * 100, 2),
        "max_safe_concurrency": safe,
        "recommended_concurrency": analysis.get("recommended_concurrency", 0),
        "bottleneck_summary": analysis.get("summary", "All steps passed"),
    }


def _build_overview(task_info: dict, tech_stack: dict, routes: list, metrics: dict) -> dict:
    """Build the overview section of the report."""
    return {
        "task_name": task_info.get("name", "Untitled"),
        "project_path": task_info.get("project_path", ""),
        "created_at": task_info.get("created_at", ""),
        "language": tech_stack.get("language", "Unknown"),
        "framework": tech_stack.get("framework", "Unknown"),
        "web_server": tech_stack.get("web_server", "Unknown"),
        "entry_point": tech_stack.get("entry_point", "Unknown"),
        "routes_count": len(routes),
        "overall_grade": _calculate_grade(metrics),
    }


def _calculate_grade(metrics: dict) -> str:
    """Calculate overall grade (A/B/C/D) based on metrics."""
    score = 100

    # Deduct for high latency
    p99 = metrics.get("latency_p99", 0)
    if p99 > 1000:
        score -= 30
    elif p99 > 500:
        score -= 15
    elif p99 > 200:
        score -= 5

    # Deduct for low concurrency
    safe = metrics.get("max_safe_concurrency", 0)
    if safe < 50:
        score -= 20
    elif safe < 100:
        score -= 10
    elif safe < 200:
        score -= 5

    # Deduct for errors
    error_rate = metrics.get("error_rate", 0)
    if error_rate > 5:
        score -= 25
    elif error_rate > 1:
        score -= 10

    if score >= 85:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 50:
        return "C"
    return "D"


async def _generate_fix_document(
    llm_client,
    metrics: dict,
    tech_stack: dict,
    routes: list,
    step_results: list,
    bottleneck_analysis: Optional[list],
) -> str:
    """Call LLM to generate the fix document."""
    metrics_json = json.dumps(metrics, indent=2)
    step_json = json.dumps(step_results, indent=2, default=str)
    bottleneck_json = json.dumps(bottleneck_analysis, indent=2, default=str) if bottleneck_analysis else "None"

    routes_summary = "\n".join([
        f"- {r.get('method', 'GET')} {r.get('path', '/')}" for r in routes[:15]
    ])

    prompt = f"""你是一名资深后端工程师，正在审查一份压测报告。请生成一份中文的修复文档。

## 项目信息
- 语言: {tech_stack.get('language', 'Unknown')}
- 框架: {tech_stack.get('framework', 'Unknown')}
- Web 服务器: {tech_stack.get('web_server', 'Unknown')}

## 关键指标
{metrics_json}

## API 路由（前 15 条）
{routes_summary}

## 阶梯压测结果
{step_json}

## 瓶颈分析
{bottleneck_json}

## 任务
请生成一份结构化的 Markdown 修复文档，包含以下章节：

1. **执行摘要** — 2-3 句话描述整体健康状况
2. **发现的问题** — 表格，列：严重程度（严重/高/中/低）、问题、位置、根因、修复方案、预期效果
3. **详细修复方案** — 对每个问题提供：
   - 问题描述
   - 位置（文件、行号）
   - 具体代码修复（修改前/修改后）
   - 修复后的预期提升
4. **性能总结** — 当前指标与目标指标的对比表格

请使用以下格式：
### [严重程度] 问题名称
- **位置**: file.py:行号
- **问题**: 描述
- **根因**: 分析
- **修复**:
```python
# 修改前
old_code

# 修改后
new_code
```
- **预期效果**: 具体提升

只输出 Markdown 内容，不要额外说明。"""

    result = await llm_client.chat(
        messages=[
            {"role": "system", "content": "你是一名资深后端工程师。只输出 Markdown 修复文档，不要额外说明。全部用中文。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
    )

    return result


def _build_fallback_fix_document(metrics: dict, tech_stack: dict, bottleneck_analysis) -> str:
    """Generate a template-based fix document when LLM is unavailable."""
    lines = []
    lines.append("# BackendTestForge 修复报告")
    lines.append("")
    lines.append("## 执行摘要")
    lines.append("")
    grade = _calculate_grade(metrics)
    lines.append(f"综合评分: **{grade}**")
    lines.append(f"最大安全并发: **{metrics.get('max_safe_concurrency', 0)}** VUs")
    lines.append(f"P99 延迟: **{metrics.get('latency_p99', 0)}ms**")
    lines.append(f"错误率: **{metrics.get('error_rate', 0)}%**")
    lines.append("")

    if metrics.get("latency_p99", 0) > 500:
        lines.append("## [严重] P99 延迟过高")
        lines.append("")
        lines.append(f"- **问题**: P99 延迟为 {metrics.get('latency_p99', 0)}ms")
        lines.append("- **目标**: P99 < 500ms")
        lines.append("- **常见原因**: 数据库查询效率低、缺少缓存、连接池限制")
        lines.append("- **建议措施**:")
        lines.append("  1. 分析数据库慢查询")
        lines.append("  2. 实现缓存层（Redis）")
        lines.append("  3. 优化 N+1 查询")
        lines.append("")

    safe = metrics.get("max_safe_concurrency", 0)
    if safe < 100:
        lines.append("## [高] 并发能力不足")
        lines.append("")
        lines.append(f"- **问题**: 最大安全并发仅为 {safe} VUs")
        lines.append("- **目标**: > 200 VUs")
        lines.append("- **常见原因**: 连接池太小、阻塞 I/O、缺少异步支持")
        lines.append("- **建议措施**:")
        if "fastapi" in str(tech_stack).lower():
            lines.append("  1. 增加数据库连接池大小（pool_size、max_overflow）")
            lines.append("  2. 确保所有 I/O 操作使用 async/await")
            lines.append("  3. 为外部服务添加连接池")
        lines.append("")

    if bottleneck_analysis:
        lines.append("## [中] 瓶颈分析")
        lines.append("")
        lines.append("识别到以下瓶颈：")
        for item in bottleneck_analysis if isinstance(bottleneck_analysis, list) else [bottleneck_analysis]:
            if isinstance(item, dict):
                lines.append(f"- **{item.get('location', '未知')}**: {item.get('issue', '')}")
                if item.get('fix'):
                    lines.append(f"  - 修复方案: {item['fix']}")
            else:
                lines.append(f"- {item}")
        lines.append("")

    lines.append("## 性能总结")
    lines.append("")
    lines.append("| 指标 | 当前值 | 目标值 |")
    lines.append("|------|--------|--------|")
    lines.append(f"| 最大安全并发 | {metrics.get('max_safe_concurrency', 0)} | ≥ 200 |")
    lines.append(f"| P50 延迟 | {metrics.get('latency_p50', 0)}ms | < 100ms |")
    lines.append(f"| P95 延迟 | {metrics.get('latency_p95', 0)}ms | < 300ms |")
    lines.append(f"| P99 延迟 | {metrics.get('latency_p99', 0)}ms | < 500ms |")
    lines.append(f"| QPS | {metrics.get('qps_avg', 0)} | 待基准测试 |")
    lines.append(f"| 错误率 | {metrics.get('error_rate', 0)}% | < 1% |")
    lines.append("")
    lines.append("---")
    lines.append("*由 BackendTestForge 自动生成 — 多 Agent 后端质量检测系统*")

    return "\n".join(lines)


async def run_doc_builder(
    task_id: int,
    code_parse_result: dict,
    load_test_result: dict,
    task_info: dict,
    llm_client=None,
) -> dict:
    """
    Entry point for the DocBuilder pipeline.
    Called from the orchestrator.
    """
    logger.info(f"DocBuilder building report for task {task_id}")

    result = await build_report(
        code_parse_result=code_parse_result,
        load_test_result=load_test_result,
        task_info=task_info,
        llm_client=llm_client,
    )

    return result
