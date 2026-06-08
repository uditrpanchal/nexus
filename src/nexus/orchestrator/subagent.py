"""
Concurrent Subagent Delegation for NEXUS.

Enables the core agent to spawn isolated subagents for:
  - Multi-ticker research (parallel analysis of several stocks)
  - Deep-dive tasks (DCF, memo, filings extraction)

Each subagent runs with a tightly sandboxed toolset and returns
a single synthesized response to the main thread.

Uses asyncio for concurrent execution.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class SubagentTask:
    """A task to be delegated to a subagent."""
    id: str
    goal: str
    context: str = ""
    tools: list[str] = field(default_factory=list)  # allowed tool names
    max_iterations: int = 5
    model: str = "openrouter/openai/gpt-4o-mini"  # lightweight default
    timeout_seconds: int = 120

    def to_prompt(self) -> str:
        """Build the prompt for the subagent."""
        prompt = f"""You are a focused research subagent. Complete this task and return your findings.

## Task
{self.goal}

## Context
{self.context}

## Instructions
- Work autonomously — do not ask questions
- Use only the tools available to you
- Return a single, concise answer with specific data points
- If a tool fails, note it and try an alternative approach
- Keep your response under 2000 words
"""
        return prompt


@dataclass
class SubagentResult:
    """Result returned by a subagent."""
    task_id: str
    success: bool
    output: str
    tool_calls: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None


class SubagentPool:
    """
    Manages concurrent subagent execution.

    Usage:
        pool = SubagentPool(agent_factory)
        results = await pool.run_parallel([
            SubagentTask("aapl", "Analyze AAPL"),
            SubagentTask("msft", "Analyze MSFT"),
        ])
    """

    def __init__(
        self,
        agent_factory: Callable[[], Any],
        max_concurrency: int = 3,
    ):
        self.agent_factory = agent_factory
        self.max_concurrency = max_concurrency

    async def run_single(self, task: SubagentTask) -> SubagentResult:
        """Run a single subagent task."""
        start = time.time()

        try:
            agent = self.agent_factory()
            output = ""
            tool_count = 0

            async for event in agent.run(task.to_prompt()):
                if hasattr(event, "type"):
                    if event.type == "done":
                        output = event.data.get("answer", "")
                        tool_count = len(event.data.get("tool_calls", []))
                        break
                    elif event.type in ("tool_start",):
                        tool_count += 1

            duration = time.time() - start
            return SubagentResult(
                task_id=task.id,
                success=True,
                output=output[:4000],  # Cap for main thread
                tool_calls=tool_count,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.time() - start
            return SubagentResult(
                task_id=task.id,
                success=False,
                output="",
                error=str(e),
                duration_seconds=duration,
            )

    async def run_parallel(
        self,
        tasks: list[SubagentTask],
    ) -> list[SubagentResult]:
        """
        Run multiple subagent tasks in parallel with concurrency control.
        """
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _bounded_run(task: SubagentTask) -> SubagentResult:
            async with semaphore:
                return await self.run_single(task)

        results = await asyncio.gather(
            *[_bounded_run(t) for t in tasks],
            return_exceptions=True,
        )

        # Unwrap exceptions
        final = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final.append(SubagentResult(
                    task_id=tasks[i].id,
                    success=False,
                    output="",
                    error=str(r),
                ))
            else:
                final.append(r)

        return final

    async def run_sequential(
        self,
        tasks: list[SubagentTask],
    ) -> list[SubagentResult]:
        """Run subagent tasks one at a time (for ordered dependencies)."""
        results = []
        for task in tasks:
            results.append(await self.run_single(task))
        return results

    def format_results_summary(self, results: list[SubagentResult]) -> str:
        """Format subagent results for injection into main agent context."""
        lines = ["## Subagent Results", ""]

        for r in results:
            status = "SUCCESS" if r.success else "FAILED"
            lines.append(f"### {r.task_id} [{status}] ({r.duration_seconds:.1f}s)")
            if r.error:
                lines.append(f"Error: {r.error}")
            else:
                # Truncate very long outputs
                output = r.output[:1500]
                if len(r.output) > 1500:
                    output += f"\n... [truncated, {len(r.output)} total chars]"
                lines.append(output)
            lines.append("")

        return "\n".join(lines)


def create_ticker_tasks(
    tickers: list[str],
    analysis_type: str = "full",
) -> list[SubagentTask]:
    """
    Create SubagentTasks for parallel multi-ticker analysis.
    """
    tasks = []
    for ticker in tickers:
        ticker = ticker.upper()
        if analysis_type == "full":
            goal = f"Run a complete financial analysis of {ticker} using the run_full_analysis pipeline. Extract price, key metrics, red flags, pillar scores, and final verdict."
        elif analysis_type == "dcf":
            goal = f"Run a DCF valuation for {ticker}. Calculate FCF growth, estimate WACC, project 5-year cash flows, compute intrinsic value and sensitivity matrix."
        elif analysis_type == "memo":
            goal = f"Draft a buyside investment memo for {ticker}. Frame the variant view, build bear/base/bull scenarios, and identify catalysts and tripwires."
        else:
            goal = f"Analyze {ticker} for {analysis_type}."

        tasks.append(SubagentTask(
            id=f"{ticker.lower()}-{analysis_type}",
            goal=goal,
            context=f"Ticker: {ticker}, Analysis type: {analysis_type}",
        ))

    return tasks
