"""
Multi-provider LLM abstraction — mirrors dexter's src/model/llm.ts

Supports: OpenAI, Anthropic, OpenRouter, Ollama (local)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import httpx


@dataclass
class LLMMessage:
    role: str
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[dict[str, Any]]
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider:
    """Multi-provider LLM client with tool calling."""

    def __init__(self, config):
        self.config = config
        self._client = httpx.AsyncClient(timeout=120.0)

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def api_key(self) -> str:
        """Get the API key for the configured provider."""
        provider = self._resolve_provider()
        if provider == "openai":
            return self.config.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        elif provider == "anthropic":
            return self.config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        elif provider == "openrouter":
            return self.config.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")
        return ""

    @property
    def base_url(self) -> str | None:
        provider = self._resolve_provider()
        if provider == "ollama":
            return self.config.ollama_base_url
        elif provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        return None

    def _resolve_provider(self) -> str:
        """Detect provider from model name or explicit config."""
        if self.config.provider != "auto":
            return self.config.provider
        model = self.model.lower()
        if model.startswith("openrouter/"):
            return "openrouter"
        if model.startswith("claude"):
            return "anthropic"
        if model.startswith("gemini"):
            return "google"
        if model.startswith("grok"):
            return "xai"
        if "ollama" in model or model.startswith("llama") or model.startswith("mistral"):
            return "ollama"
        return "openai"

    async def call_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        """Call LLM with tool schemas — returns response with tool_calls."""
        provider = self._resolve_provider()

        if provider == "anthropic":
            return await self._call_anthropic(messages, tools)
        elif provider == "ollama":
            return await self._call_ollama(messages, tools)
        else:
            return await self._call_openai(messages, tools)

    async def _call_openai(
        self, messages: list[LLMMessage], tools: list[dict]
    ) -> LLMResponse:
        """OpenAI-compatible API call (works for OpenAI, OpenRouter)."""
        api_key = self.api_key
        if not api_key:
            raise ValueError("No API key configured. Set OPENAI_API_KEY or OPENROUTER_API_KEY env var.")

        msgs = []
        for m in messages:
            msg = {"role": m.role, "content": m.content}
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            if m.name:
                msg["name"] = m.name
            msgs.append(msg)

        payload = {
            "model": self.model,
            "messages": msgs,
            "temperature": self.config.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.base_url}/chat/completions" if self.base_url else "https://api.openai.com/v1/chat/completions"

        resp = await self._client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"LLM API error: {resp.status_code} — {resp.text}")

        data = resp.json()
        choice = data["choices"][0]["message"]

        tool_calls = []
        if "tool_calls" in choice:
            for tc in choice["tool_calls"]:
                tool_calls.append({
                    "id": tc["id"],
                    "type": tc.get("type", "function"),
                    "function": tc["function"],
                })

        usage = data.get("usage", {})

        return LLMResponse(
            content=choice.get("content"),
            tool_calls=tool_calls,
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        )

    async def _call_anthropic(
        self, messages: list[LLMMessage], tools: list[dict]
    ) -> LLMResponse:
        """Anthropic API call with tool use."""
        api_key = self.api_key
        if not api_key:
            raise ValueError("No Anthropic API key configured.")

        # Convert messages to Anthropic format
        system_msg = ""
        anthropic_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
                continue
            elif m.role == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}],
                })
            elif m.role == "assistant":
                content = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"]),
                    })
                anthropic_messages.append({
                    "role": "assistant",
                    "content": content,
                })
            else:
                anthropic_messages.append({"role": m.role, "content": m.content})

        # Convert tools to Anthropic format
        anthropic_tools = []
        for t in tools:
            anthropic_tools.append({
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            })

        payload = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": 4096,
            "temperature": self.config.temperature,
        }
        if system_msg:
            payload["system"] = system_msg
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "tools-2024-04-04",
        }

        resp = await self._client.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers=headers,
        )

        if resp.status_code != 200:
            raise ValueError(f"Anthropic API error: {resp.status_code} — {resp.text}")

        data = resp.json()

        content = ""
        tool_calls = []
        for block in data.get("content", []):
            if block["type"] == "text":
                content += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block["input"]),
                    },
                })

        usage = data.get("usage", {})

        return LLMResponse(
            content=content or None,
            tool_calls=tool_calls,
            usage={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        )

    async def _call_ollama(
        self, messages: list[LLMMessage], tools: list[dict]
    ) -> LLMResponse:
        """Ollama local API call."""
        ollama_messages = []
        for m in messages:
            msg = {"role": m.role, "content": m.content}
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            ollama_messages.append(msg)

        payload = {
            "model": self.model.replace("ollama/", ""),
            "messages": ollama_messages,
            "stream": False,
            "options": {"temperature": self.config.temperature},
        }
        if tools:
            payload["tools"] = tools

        base = self.base_url or "http://127.0.0.1:11434"
        url = f"{base}/api/chat"

        resp = await self._client.post(url, json=payload)
        if resp.status_code != 200:
            raise ValueError(f"Ollama error: {resp.status_code} — {resp.text}")

        data = resp.json()
        msg = data.get("message", {})

        tool_calls = []
        if "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                tool_calls.append({
                    "id": tc.get("id", f"tc_{len(tool_calls)}"),
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": json.dumps(tc["function"]["arguments"]),
                    },
                })

        return LLMResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
        )
