"""
ProjectManager — 被测服务健康检查。

不再负责服务启动/停止。用户自行启动被测服务，系统只做健康检查。
"""

import logging
import httpx

logger = logging.getLogger(__name__)


class ProjectManager:
    """Lightweight health-check wrapper for the target service."""

    @classmethod
    async def health_check_only(cls, base_url: str, timeout: int = 10) -> bool:
        """Check if the target service is reachable via /health or / ."""
        paths = ["/health", "/ready", "/"]
        for path in paths:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(f"{base_url.rstrip('/')}{path}")
                    if resp.status_code < 500:
                        return True
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError):
                continue
        return False
