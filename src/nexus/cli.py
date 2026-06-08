"""
NEXUS CLI — Rich terminal interface for the financial research agent.

Inspired by dexter's Ink/React CLI but built with Rich + Click for Python.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from .agent import Agent, AgentConfig, AgentEvent, EventType
from .tools.formatting import format_full_analysis


# Auto-load .env file from project root
load_dotenv()

# Fix Windows encoding for Rich emoji/unicode output
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

console = Console()


BANNER = r"""
╔══════════════════════════════════════════════════════╗
║                                                      ║
║   ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗     ║
║   ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝     ║
║   ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗     ║
║   ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║     ║
║   ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║     ║
║   ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝     ║
║                                                      ║
║   Autonomous Financial Research Agent               ║
║   Free Data · Zero API Keys · V9 Framework          ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
"""


def get_config() -> AgentConfig:
    """Load configuration from environment."""
    return AgentConfig(
        model=os.environ.get("NEXUS_MODEL", "openrouter/owl-alpha"),
        provider=os.environ.get("NEXUS_PROVIDER", "auto"),
        max_iterations=int(os.environ.get("NEXUS_MAX_ITERATIONS", "15")),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
    )


async def run_agent_query(agent: Agent, query: str) -> str:
    """Run a query through the agent and display results."""
    full_answer = []
    tool_calls_made = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Initializing...", total=None)

        async for event in agent.run(query):
            if event.type == EventType.THINKING:
                msg = event.data.get("message", "")
                iteration = event.data.get("iteration", "?")
                progress.update(task, description=f"[dim]{msg}[/dim]")

            elif event.type == EventType.TOOL_START:
                tool = event.data.get("tool", "?")
                progress.update(task, description=f"[cyan]▸ {tool}[/cyan]")

            elif event.type == EventType.TOOL_END:
                tool = event.data.get("tool", "?")
                duration = event.data.get("duration", 0)
                progress.update(task, description=f"[green]✓ {tool}[/green] ({duration}s)")

            elif event.type == EventType.TOOL_ERROR:
                tool = event.data.get("tool", "?")
                progress.update(task, description=f"[red]✗ {tool}[/red]")

            elif event.type == EventType.DONE:
                answer = event.data.get("answer", "")
                iterations = event.data.get("iterations", 0)
                total_time = event.data.get("total_time", 0)
                tool_calls_made = event.data.get("tool_calls", [])
                if answer:
                    full_answer.append(answer)
                progress.update(
                    task,
                    description=f"[bold green]Done[/bold green] — {iterations} iterations, {total_time}s",
                )

    return "\n\n".join(full_answer), tool_calls_made


@click.command()
@click.argument("query", required=False)
@click.option("--model", "-m", default=None, help="LLM model to use")
@click.option("--provider", "-p", default=None, help="LLM provider (openai, anthropic, ollama, openrouter)")
@click.option("--verbose", "-v", is_flag=True, default=True, help="Show tool calls")
def main(query: str | None, model: str | None, provider: str | None, verbose: bool):
    """NEXUS — Autonomous Financial Research Agent"""

    config = get_config()
    if model:
        config.model = model
    if provider:
        config.provider = provider
    config.verbose = verbose

    # Auto-route to OpenRouter when no OpenAI key is present.
    openai_key = config.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    openrouter_key = config.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if config.provider == "auto" and openrouter_key and not openai_key:
        config.provider = "openrouter"
        if "/" not in config.model:
            config.model = f"openai/{config.model}"

    # Check for API key
    has_key = (
        openai_key
        or config.anthropic_api_key
        or openrouter_key
        or config.provider == "ollama"
    )

    if not has_key:
        console.print(Panel(
            "[bold red]No API key configured.[/bold red]\n\n"
            "Set one of these environment variables:\n"
            "  • OPENAI_API_KEY\n"
            "  • ANTHROPIC_API_KEY\n"
            "  • OPENROUTER_API_KEY\n"
            "  • Or use --provider ollama for local LLMs\n\n"
            "Example:\n"
            "  export OPENAI_API_KEY=sk-...\n"
            "  nexus \"Analyze AAPL\"",
            title="⚠ Configuration",
            border_style="red",
        ))
        sys.exit(1)

    if query:
        # Single query mode
        agent = Agent(config)

        console.print(BANNER)
        console.print(f"[dim]Model: {config.model} | Provider: {config.provider}[/dim]\n")

        answer, tool_calls = asyncio.run(run_agent_query(agent, query))

        if answer:
            console.print(Panel(
                Markdown(answer),
                title=f"[bold]Analysis: {query}[/bold]",
                border_style="green",
                padding=(1, 2),
            ))
        return

    # Interactive mode
    console.print(BANNER)
    console.print(f"[dim]Model: {config.model} | Provider: {config.provider}[/dim]")
    console.print("[dim]Type 'quit' or 'exit' to stop. Type 'help' for commands.[/dim]\n")

    agent = Agent(config)

    while True:
        try:
            query = Prompt.ask("\n[bold cyan]NEXUS[/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not query.strip():
            continue

        if query.lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        if query.lower() == "help":
            console.print(Panel(
                "[bold]NEXUS Commands:[/bold]\n\n"
                "• Type any financial question or ticker symbol\n"
                "• 'Analyze AAPL' — full stock analysis\n"
                "• 'Compare AAPL vs MSFT' — comparison\n"
                "• 'Screen for value stocks' — stock screening\n"
                "• 'News on TSLA' — recent news\n"
                "• 'quit' — exit\n\n"
                "[dim]Data sources: Yahoo Finance, SEC EDGAR, web scraping (all free)[/dim]",
                title="Help",
                border_style="blue",
            ))
            continue

        if query.lower() == "clear":
            console.clear()
            continue

        answer, tool_calls = asyncio.run(run_agent_query(agent, query))

        if answer:
            console.print(Panel(
                Markdown(answer),
                title=f"[bold]Analysis[/bold]",
                border_style="green",
                padding=(1, 2),
            ))


if __name__ == "__main__":
    main()
