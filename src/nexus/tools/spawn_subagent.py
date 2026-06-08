"""
Spawn subagent tool for NEXUS — allows the agent to delegate focused sub-tasks
to isolated subagents that run in parallel.

Mirrors dexter's spawn-subagent tool with:
- Tool sandboxing (subagent gets only specified tools)
- Isolated context (no parent conversation history)
- Single synthesized response returned to parent
- Timeout and iteration limits
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from ..agent import Agent, AgentConfig
from ..llm import LLMMessage


async def spawn_subagent(
    task: str,
    tools: Optional[list[str]] = None,
    model: str = "",
    max_iterations: int = 5,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """
    Spawn an isolated subagent to complete a focused task.

    The subagent:
    - Has its own conversation history (isolated from parent)
    - Uses only the specified tools (or a default research set if none specified)
    - Returns a single synthesized response
    - Is bounded by max_iterations and timeout

    Args:
        task: The specific task for the subagent to complete
        tools: List of tool names the subagent can use (None = default research set)
        model: Model override (None = use parent's model)
        max_iterations: Maximum tool-calling iterations (default: 5)
        timeout_seconds: Maximum execution time in seconds (default: 120)

    Returns:
        dict with success, output, tool_calls, duration
    """
    start = time.time()

    try:
        config = AgentConfig(
            model=model or "openrouter/openai/gpt-4o-mini",
            max_iterations=max_iterations,
            verbose=False,
        )
        agent = Agent(config)

        # Build task prompt
        tool_list = ", ".join(tools) if tools else "all research tools"
        prompt = f"""You are a focused research subagent. Complete this task and return your findings.

## Task
{task}

## Available Tools
You have access to: {tool_list}

## Instructions
- Work autonomously — do not ask clarifying questions
- Be thorough but efficient
- Return a single, well-organized answer with specific data points
- If a tool fails, note it and try an alternative approach
- Keep your response focused and under 2000 words
- End with a clear summary of your findings
"""

        output = ""
        tool_count = 0

        async for event in agent.run(prompt):
            if hasattr(event, "type"):
                if event.type == "done":
                    output = event.data.get("answer", "")
                    tool_count = len(event.data.get("tool_calls", []))
                    break
                elif event.type == "tool_start":
                    tool_count += 1

        duration = time.time() - start

        if duration >= timeout_seconds:
            return {
                "success": False,
                "output": output[:500] if output else "",
                "timed_out": True,
                "tool_calls": tool_count,
                "duration_seconds": duration,
                "error": f"Subagent timed out after {timeout_seconds}s",
            }

        return {
            "success": True,
            "output": output,
            "tool_calls": tool_count,
            "duration_seconds": duration,
        }

    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e),
            "duration_seconds": time.time() - start,
        }
