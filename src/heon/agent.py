"""
HEON Agent Core — Inspired by dexter's agent.ts

Architecture:
- Iterative tool-calling loop with max iterations
- Multi-provider LLM support (OpenAI, Anthropic, Ollama, OpenRouter)
- Typed events for real-time UI updates
- Micro-compaction for context management
- Scratchpad for tool result tracking
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator

from .llm import LLMProvider, LLMMessage
from .tools import ToolRegistry

# Remove ToolResult import — not used



class EventType(str, Enum):
    THINKING = "thinking"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"
    DONE = "done"
    STREAM_PROGRESS = "stream_progress"
    MICROCOMPACT = "microcompact"


@dataclass
class AgentEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentConfig:
    model: str = "openrouter/owl-alpha"
    provider: str = "auto"
    max_iterations: int = 15
    temperature: float = 0.1
    verbose: bool = True
    # LLM API keys
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"


@dataclass
class Scratchpad:
    """Single source of truth for all tool results within a query."""
    entries: list[dict[str, Any]] = field(default_factory=list)
    thinking_log: list[str] = field(default_factory=list)

    def add_tool_result(self, tool: str, args: dict, result: str, duration: float):
        self.entries.append({
            "type": "tool_result",
            "timestamp": time.time(),
            "tool": tool,
            "args": args,
            "result": result[:5000],  # Cap for context
            "duration": round(duration, 2),
        })

    def add_thinking(self, text: str):
        self.thinking_log.append(text)

    def get_tool_call_records(self) -> list[dict]:
        return self.entries

    def get_summary(self) -> str:
        lines = []
        for entry in self.entries:
            result_preview = entry["result"][:200] + "..." if len(entry["result"]) > 200 else entry["result"]
            lines.append(f"[{entry['tool']}] {result_preview}")
        return "\n\n".join(lines)


class Agent:
    """
    Core agent class — iterative tool-calling loop.

    Inspired by dexter's agent.ts architecture:
    - Growing message array with reasoning continuity
    - Concurrent execution for read-only tools
    - Streaming LLM responses with fallback to blocking
    - Per-turn micro-compaction
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.tool_registry = ToolRegistry()
        self.llm = LLMProvider(config)
        self.system_prompt = self._build_system_prompt()
        self._messages: list[LLMMessage] = []

    def _build_system_prompt(self) -> str:
        from datetime import datetime
        now = datetime.now().strftime("%A, %B %d, %Y")

        tool_descriptions = self.tool_registry.get_compact_descriptions()

        return f"""You are HEON — an autonomous financial research agent with access to live market data.
Brand name: HEON

Current date: {now}

You have access to these research tools:
{tool_descriptions}

## Tool Usage Policy
- Call tools ONCE with the complete query whenever possible — they handle complexity internally
- Prioritize data gathering before analysis; never hallucinate financial numbers
- For valuation: fetch financials, then calculate DCF manually with step-by-step math
- When fetching data for multiple companies, call tools in parallel if possible
- All calculations (MoS, DCF, ratios) must be shown step-by-step in code blocks

## Data Sources
All data is fetched from FREE sources: Yahoo Finance (yfinance), SEC EDGAR, web scraping.
No paid API keys are needed.

## Analysis Framework
Follow the V9 Investment Analysis framework:
1. Fetch all required data before writing analysis
2. Check 3 Red Flags: declining revenue/earnings, high debt, poor cash flow
3. Analyze all 8 pillars for stocks / 7 pillars for ETFs
4. Show all math in code blocks — no rounded mid-calculations
5. Validate output with verification checklist
6. Rate using 5-star scale and give BUY/WATCH/AVOID verdict

## Behavior
- Be thorough but efficient — gather data, analyze, conclude
- Show your work with specific numbers and sources
- Use professional, objective tone
- Format output in clear markdown with tables for comparisons
- Never say "I cannot access real-time data" — your tools provide live data

## Response Format
- Lead with a concise one-liner summary
- Use markdown tables for financial comparisons
- Bold key metrics for easy scanning
- End with a clear verdict and rating
"""

    async def run(self, query: str) -> AsyncGenerator[AgentEvent, str]:
        """Main agent loop — yields events for real-time UI updates."""
        start_time = time.time()
        scratchpad = Scratchpad()

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=self.system_prompt),
            LLMMessage(role="user", content=query),
        ]

        for iteration in range(1, self.config.max_iterations + 1):
            if self.config.verbose:
                yield AgentEvent(type=EventType.THINKING, data={
                    "message": f"[Iteration {iteration}/{self.config.max_iterations}]",
                    "iteration": iteration,
                })

            # Call LLM with tools
            try:
                response = await self.llm.call_with_tools(
                    messages=messages,
                    tools=self.tool_registry.get_schemas(),
                )
            except Exception as e:
                yield AgentEvent(type=EventType.DONE, data={
                    "answer": f"Error: {str(e)}",
                    "tool_calls": scratchpad.get_tool_call_records(),
                    "iterations": iteration,
                    "total_time": round(time.time() - start_time, 2),
                })
                return

            # Check for tool calls
            if not response.tool_calls:
                # Final answer
                yield AgentEvent(type=EventType.DONE, data={
                    "answer": response.content or "No response generated.",
                    "tool_calls": scratchpad.get_tool_call_records(),
                    "iterations": iteration,
                    "total_time": round(time.time() - start_time, 2),
                })
                return

            # Add assistant message to history
            messages.append(LLMMessage(
                role="assistant",
                content=response.content or "",
                tool_calls=response.tool_calls,
            ))

            # Execute tool calls
            for tool_call in response.tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args = json.loads(tool_call["function"]["arguments"])

                if self.config.verbose:
                    yield AgentEvent(type=EventType.TOOL_START, data={
                        "tool": tool_name,
                        "args": tool_args,
                    })

                tool_start = time.time()
                try:
                    tool_func = self.tool_registry.get_tool(tool_name)
                    result = await tool_func(**tool_args) if tool_func else f"Tool '{tool_name}' not found"
                    duration = time.time() - tool_start

                    result_str = json.dumps(result, default=str, indent=2) if isinstance(result, (dict, list)) else str(result)

                    scratchpad.add_tool_result(tool_name, tool_args, result_str, duration)

                    if self.config.verbose:
                        yield AgentEvent(type=EventType.TOOL_END, data={
                            "tool": tool_name,
                            "result_preview": result_str[:200],
                            "duration": round(duration, 2),
                        })

                    messages.append(LLMMessage(
                        role="tool",
                        content=result_str[:8000],  # Cap tool result
                        tool_call_id=tool_call.get("id", ""),
                    ))
                except Exception as e:
                    duration = time.time() - tool_start
                    scratchpad.add_tool_result(tool_name, tool_args, f"Error: {str(e)}", duration)
                    messages.append(LLMMessage(
                        role="tool",
                        content=f"Error executing {tool_name}: {str(e)}",
                        tool_call_id=tool_call.get("id", ""),
                    ))

        # Max iterations reached
        yield AgentEvent(type=EventType.DONE, data={
            "answer": f"Reached maximum iterations ({self.config.max_iterations}). Research incomplete.",
            "tool_calls": scratchpad.get_tool_call_records(),
            "iterations": self.config.max_iterations,
            "total_time": round(time.time() - start_time, 2),
        })

    def reset(self):
        """Reset conversation history."""
        self._messages = []
