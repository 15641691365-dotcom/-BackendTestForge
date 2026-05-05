"""
K6Runner — k6 压测脚本生成、执行、结果解析。

工作流：
1. 根据技术栈选择模板文件
2. 填充模板变量（BASE_URL, ENDPOINTS, DURATION）
3. 写入临时文件 → 执行 k6 → 解析 JSON 输出
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "k6"

# Step load profile: (vus, duration_seconds)
DEFAULT_STEPS = [
    (10, 30),
    (50, 30),
    (100, 30),
    (200, 30),
    (500, 30),
]

# Thresholds for detecting bottleneck / stopping
MAX_ERROR_RATE = 0.01     # 1% error rate = stop
MAX_P99_LATENCY = 1000     # 1000ms P99 = stop


class K6Runner:
    """Generate, execute, and parse k6 load tests."""

    def __init__(self, templates_dir: Path = TEMPLATES_DIR):
        self.templates_dir = templates_dir

    def get_template_path(self, framework: str = None) -> Path:
        """Select the appropriate k6 template for the detected framework."""
        template_map = {
            "fastapi": "fastapi_template.js",
            "flask": "generic_template.js",
            "express": "generic_template.js",
            "gin": "generic_template.js",
            "echo": "generic_template.js",
        }
        template_name = template_map.get((framework or "").lower(), "generic_template.js")
        template_path = self.templates_dir / template_name

        if not template_path.exists():
            template_path = self.templates_dir / "generic_template.js"

        if not template_path.exists():
            raise FileNotFoundError(f"No k6 template found in {self.templates_dir}")

        return template_path

    def generate_script(
        self,
        base_url: str,
        endpoints: list[dict],
        template_path: Path,
        duration: int = 30,
        vus: int = 10,
    ) -> str:
        """
        Fill a k6 template with the given variables.
        Returns the path to the generated script.
        """
        # Validate endpoints
        clean_endpoints = []
        for ep in endpoints:
            clean_endpoints.append({
                "method": ep.get("method", "GET"),
                "path": ep.get("path", "/"),
                "sample_body": ep.get("sample_body", {}),
            })

        endpoints_json = json.dumps(clean_endpoints)

        # Read template
        with open(template_path) as f:
            script = f.read()

        # The template reads from __ENV, so we pass variables as environment
        # This is handled at execution time

        return script

    async def run_step(
        self,
        script_content: str,
        base_url: str,
        endpoints: list[dict],
        vus: int,
        duration: int,
        workdir: str = None,
    ) -> dict:
        """
        Execute a single step of the load test.
        Returns parsed k6 JSON output.
        """
        # Use project's k6-scripts/ dir (snap k6 can't access /tmp)
        project_k6_dir = Path(__file__).resolve().parent.parent.parent / "k6-scripts"
        project_k6_dir.mkdir(parents=True, exist_ok=True)

        # Write script to project k6-scripts dir
        import uuid
        script_path = str(project_k6_dir / f"k6_step_{vus}vus_{uuid.uuid4().hex[:8]}.js")

        # Write script content to file
        with open(script_path, "w") as f:
            f.write(script_content)

        # Build environment for k6
        env = os.environ.copy()
        env["BASE_URL"] = base_url
        env["ENDPOINTS"] = json.dumps(endpoints)
        env["DURATION"] = str(duration)
        env["MAX_VUS"] = str(vus)

        # Build k6 command
        cmd = [
            "k6", "run",
            "--vus", str(vus),
            "--duration", f"{duration}s",
            "--summary-export", script_path.replace(".js", "_summary.json"),
            "--summary-trend-stats", "avg,min,med,max,p(90),p(95),p(99)",
            "--quiet",
            script_path,
        ]

        logger.info(f"k6 step: {vus} VUs, {duration}s duration")

        try:
            start = time.time()
            # 使用异步方式执行 k6，避免阻塞事件循环
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=duration + 30,  # Allow some overhead
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise asyncio.TimeoutError("k6 process timed out")

            elapsed = time.time() - start

            # k6 outputs results to stderr; combine both for parsing
            combined_output = stderr.decode("utf-8", errors="replace") + "\n" + stdout.decode("utf-8", errors="replace")
            logger.info(f"k6 step completed in {elapsed:.1f}s (exit: {process.returncode})")

            # Try to parse summary export
            summary_path = script_path.replace(".js", "_summary.json")
            parsed = self._parse_k6_output(summary_path, combined_output, "")
            parsed["vus"] = vus
            parsed["duration"] = duration
            parsed["elapsed_seconds"] = round(elapsed, 1)

            return parsed

        except asyncio.TimeoutError:
            logger.warning(f"k6 step timed out ({vus} VUs, {duration}s)")
            return {
                "vus": vus,
                "duration": duration,
                "error": "timeout",
                "qps": 0,
                "p50": 0,
                "p95": 0,
                "p99": 0,
                "error_rate": 1.0,
            }
        finally:
            # Cleanup temp files
            try:
                os.unlink(script_path)
                summary_path = script_path.replace(".js", "_summary.json")
                if os.path.exists(summary_path):
                    os.unlink(summary_path)
            except OSError:
                pass

    def _parse_k6_output(
        self, summary_path: str, stdout: str, stderr: str
    ) -> dict:
        """Parse k6 output into structured metrics."""
        result = {
            "qps": 0,
            "p50": 0,
            "p95": 0,
            "p99": 0,
            "avg": 0,
            "error_rate": 0,
            "max": 0,
            "min": 0,
            "median": 0,
            "iterations": 0,
            "data_received": 0,
            "data_sent": 0,
        }

        # Try to parse summary JSON export first
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    summary = json.load(f)

                metrics = summary.get("metrics", {})

                # HTTP request duration — k6 uses p(50), p(95), p(99) with --summary-trend-stats
                # Fallback to 'med' if p(50) isn't available (older k6 versions)
                duration = metrics.get("http_req_duration", {})
                result["avg"] = self._get_metric_value(duration, "avg")
                p50 = self._get_metric_value(duration, "p(50)")
                result["p50"] = p50 if p50 else self._get_metric_value(duration, "med")
                result["p95"] = self._get_metric_value(duration, "p(95)")
                p99 = self._get_metric_value(duration, "p(99)")
                result["p99"] = p99 if p99 else self._get_metric_value(duration, "p(99.9)")
                result["max"] = self._get_metric_value(duration, "max")
                result["min"] = self._get_metric_value(duration, "min")
                result["median"] = result["p50"]

                # Iterations (requests per second)
                iters = metrics.get("iterations", {})
                result["iterations"] = self._get_metric_value(iters, "count", 0) or 0

                # HTTP request rate (QPS)
                http_reqs = metrics.get("http_reqs", {})
                result["qps"] = round(self._get_metric_value(http_reqs, "rate", 0), 1)

                # Error rate
                failed = metrics.get("http_req_failed", {})
                result["error_rate"] = round(self._get_metric_value(failed, "rate", 0), 4)

                # Data
                data_received = metrics.get("data_received", {})
                result["data_received"] = self._get_metric_value(data_received, "count", 0)
                data_sent = metrics.get("data_sent", {})
                result["data_sent"] = self._get_metric_value(data_sent, "count", 0)

                return result

            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.warning(f"Failed to parse k6 summary: {e}")

        # Fallback: try to parse stdout/stderr
        if "http_req_duration" in stdout or "http_req_duration" in stderr:
            text = stdout + "\n" + stderr
            import re
            # Parse http_req_duration line: avg=2.59ms min=... med=... p(90)=... p(95)=3.13ms
            dur_match = re.search(r'http_req_duration[^:]*:\s*avg=([.\d]+)(µs|ms|s).*?p\(95\)=([.\d]+)(µs|ms|s)', text)
            if dur_match:
                def to_ms(val, unit):
                    if unit == 's': return float(val) * 1000
                    if unit == 'µs': return float(val) / 1000
                    return float(val)
                result["avg"] = to_ms(dur_match.group(1), dur_match.group(2))
                result["p95"] = to_ms(dur_match.group(3), dur_match.group(4))

            # Parse p(99) separately
            p99_match = re.search(r'p\(99\)=([.\d]+)(µs|ms|s)', text)
            if p99_match:
                result["p99"] = to_ms(p99_match.group(1), p99_match.group(2))

            # Parse http_reqs rate
            reqs_match = re.search(r'http_reqs[^:]*:\s+(\d+)\s+([\d.]+)/s', text)
            if reqs_match:
                result["iterations"] = int(reqs_match.group(1))
                result["qps"] = round(float(reqs_match.group(2)), 1)

            # Parse min/max
            min_match = re.search(r'min=([\d.]+)(µs|ms|s)', text)
            if min_match:
                result["min"] = to_ms(min_match.group(1), min_match.group(2))
            max_match = re.search(r'max=([\d.]+)(µs|ms|s)', text)
            if max_match:
                result["max"] = to_ms(max_match.group(1), max_match.group(2))

            # Parse error rate from http_req_failed
            fail_match = re.search(r'http_req_failed[^:]*:\s*([\d.]+)%', text)
            if fail_match:
                result["error_rate"] = round(float(fail_match.group(1)) / 100, 4)

        return result

    def _get_metric_value(self, metric: dict, key: str, default: float = 0) -> float:
        """Safely extract a value from a metric dict."""
        if not metric or key not in metric:
            return default
        val = metric[key]
        if isinstance(val, (int, float)):
            return float(val)
        return default

    async def run_step_load(
        self,
        base_url: str,
        endpoints: list[dict],
        framework: str = None,
        steps: list[tuple] = None,
        workdir: str = None,
    ) -> list[dict]:
        """
        Run a full step-load test with increasing concurrency levels.
        Returns a list of step results.
        """
        if steps is None:
            steps = DEFAULT_STEPS

        # Get template
        template_path = self.get_template_path(framework)
        script_content = self.generate_script(
            base_url, endpoints, template_path
        )

        results = []

        for vus, duration in steps:
            logger.info(f"Step load: {vus} VUs for {duration}s")

            step_result = await self.run_step(
                script_content=script_content,
                base_url=base_url,
                endpoints=endpoints,
                vus=vus,
                duration=duration,
                workdir=workdir,
            )

            results.append(step_result)

            # Check if we should stop (bottleneck detected)
            # Stop if error rate exceeds threshold
            if step_result.get("error_rate", 0) > MAX_ERROR_RATE:
                logger.info(f"Stopping: error rate {step_result['error_rate']:.2%} > {MAX_ERROR_RATE:.0%} at {vus} VUs")
                break

            # Stop if P99 too high
            if step_result.get("p99", 0) > MAX_P99_LATENCY:
                logger.info(f"Stopping: P99 {step_result['p99']:.0f}ms > {MAX_P99_LATENCY}ms at {vus} VUs")
                break

        return results
