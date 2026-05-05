"""
Unified LLM API client.
Supports OpenAI-compatible APIs (OpenAI, Anthropic via proxy, ccswitch/MiniMax, etc.).
Provider is selected via config.py.
"""

import json
import logging
from typing import Optional

import httpx

from backend.config import config

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Lightweight async LLM client for OpenAI-compatible chat completion APIs.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.provider = provider or config.LLM_PROVIDER
        self.api_key = api_key or config.LLM_API_KEY
        self.base_url = (base_url or config.LLM_BASE_URL).rstrip("/")
        self.model = model or config.LLM_MODEL

        # Build the actual API endpoint
        if self.base_url:
            self.endpoint = f"{self.base_url}/chat/completions"
        else:
            self.endpoint = "https://api.openai.com/v1/chat/completions"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
    ) -> str:
        """
        Send a chat completion request and return the response text.

        Args:
            messages: List of {"role": "...", "content": "..."} dicts
            temperature: Sampling temperature (0.0-2.0)
            max_tokens: Maximum tokens in response
            response_format: Optional {"type": "json_object"} for structured output

        Returns:
            The response content text

        Raises:
            httpx.HTTPError: On API communication failure
            ValueError: On unexpected response format
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            body["response_format"] = response_format

        logger.info(
            "LLM request: model=%s messages=%d max_tokens=%d",
            self.model,
            len(messages),
            max_tokens,
        )

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(self.endpoint, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        logger.info(
            "LLM response: input_tokens=%d output_tokens=%d",
            data.get("usage", {}).get("prompt_tokens", 0),
            data.get("usage", {}).get("completion_tokens", 0),
        )

        return content

    async def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Send a chat completion request expecting a JSON response.
        Returns the parsed JSON dict.
        """
        content = await self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return json.loads(content)
