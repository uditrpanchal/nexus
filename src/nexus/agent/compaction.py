"""
Two-Tier Context Compaction for NEXUS Agent.

Implements:
  1. MICRO-COMPACTION (per-turn): Scrubs stale reasoning and old tool logs.
     Keeps last 4 compactable tool results; replaces older ones with a cleared marker.
  2. MACRO-COMPACTION (threshold-based): When tokens reach 50% of context limit,
     calls an auxiliary LLM to condense history into a 9-section checkpoint summary.

9-Section Checkpoint Summary:
  1. Primary Request — what the user asked
  2. Key Concepts — tickers, companies, metrics involved
  3. Files & Code Status — what was created/modified
  4. Errors & Fixes — what broke and how it was resolved
  5. Problem Solving — analysis progress, conclusions
  6. Direct User Quotes — exact user instructions
  7. Pending Tasks — what still needs to be done
  8. Current Work — what was being worked on
  9. Next Steps — recommended next actions
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Micro-compaction constants
MC_CLEARED_MARKER = "[Old tool result content cleared]"
COUNT_TRIGGER_THRESHOLD = 8   # Compact when >8 compactable ToolMessages
COUNT_KEEP_RECENT = 4         # Keep 4 most recent
TOKEN_TRIGGER_THRESHOLD = 80_000  # or when total tokens > 80K

# Macro-compaction constants
MACRO_COMPACT_TRIGGER_RATIO = 0.5  # trigger at 50% of context limit
DEFAULT_CONTEXT_LIMIT = 128_000    # default token context limit
MIN_TOOL_RESULTS_FOR_COMPACTION = 3  # skip if fewer than 3 results

# Tool names whose results can be safely micro-compacted (read-only)
COMPACTABLE_TOOLS = {
    "get_financials", "get_market_data", "read_filings", "stock_screener",
    "web_search", "web_fetch", "read_file", "get_price_snapshot",
    "get_income_statements", "get_balance_sheets", "get_cash_flow_statements",
    "get_key_metrics", "get_earnings", "get_news", "get_company_info",
    "get_insider_trades", "get_institutional_holders", "get_major_holders",
    "get_analyst_data", "get_sec_filings", "get_etf_data",
    "screen_stocks", "memory_search",
}


@dataclass
class MicrocompactResult:
    """Result of micro-compaction."""
    cleared: int = 0
    estimated_tokens_saved: int = 0
    trigger: Optional[str] = None  # "count", "token", or None


@dataclass
class MacrocompactResult:
    """Result of macro-compaction."""
    performed: bool = False
    summary: str = ""
    tokens_before: int = 0
    tokens_after: int = 0
    error: Optional[str] = None


def estimate_tokens(text: str) -> int:
    """Quick token estimate: characters ÷ 3.5 (rough heuristic)."""
    return max(1, len(text) // 3)


def microcompact_tool_results(
    messages: list[dict],
    trigger_count: int = COUNT_TRIGGER_THRESHOLD,
    keep_recent: int = COUNT_KEEP_RECENT,
    trigger_tokens: int = TOKEN_TRIGGER_THRESHOLD,
) -> tuple[list[dict], MicrocompactResult]:
    """
    Per-turn lightweight trimming of old tool result content.

    Returns (messages, result) where messages is a new list if changes were made.
    """
    # Collect indices of compactable tool results
    compactable = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        name = msg.get("name", "")
        if name not in COMPACTABLE_TOOLS:
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content != MC_CLEARED_MARKER:
            compactable.append(i)

    result = MicrocompactResult()

    # Check count trigger
    count_triggered = len(compactable) > trigger_count

    # Check token trigger
    total_tokens = 0
    if not count_triggered:
        for idx in compactable:
            content = messages[idx].get("content", "")
            text = content if isinstance(content, str) else str(content)
            total_tokens += estimate_tokens(text)
    token_triggered = not count_triggered and total_tokens > trigger_tokens

    if not count_triggered and not token_triggered:
        return messages, result

    # Keep last K, clear the rest
    keep_set = set(compactable[-keep_recent:])
    clear_indices = [i for i in compactable if i not in keep_set]
    if not clear_indices:
        return messages, result

    tokens_saved = 0
    clear_set = set(clear_indices)
    new_messages = []
    for i, msg in enumerate(messages):
        if i in clear_set:
            old_text = msg.get("content", "")
            if isinstance(old_text, str):
                tokens_saved += estimate_tokens(old_text)
            new_msg = dict(msg)
            new_msg["content"] = MC_CLEARED_MARKER
            new_messages.append(new_msg)
        else:
            new_messages.append(msg)

    result.cleared = len(clear_indices)
    result.estimated_tokens_saved = tokens_saved
    result.trigger = "count" if count_triggered else "token"

    return new_messages, result


def build_macro_compact_prompt(query: str, tool_results: str) -> str:
    """Build the macro-compaction prompt for the auxiliary LLM."""
    return f"""CRITICAL: Respond with TEXT ONLY. Do NOT call any tools. Your entire response must be plain text.

Your task is to create a detailed summary of the research session below. This summary must preserve all important data, findings, and numerical results so that work can continue without losing context.

## Summary Structure

Produce a summary with these 9 sections:

1. **Primary Request:** The user's exact request and what they are trying to learn.
2. **Key Concepts:** Important tickers, companies, sectors, financial metrics involved.
3. **Files & Code Status:** What files were created or modified, and their current state.
4. **Errors & Fixes:** Any tool failures, empty results, or retried calls and their outcomes.
5. **Problem Solving:** What has been analyzed, conclusions reached, comparisons made.
6. **Direct User Quotes:** Verbatim quotes of user instructions (if any).
7. **Pending Tasks:** What data has NOT yet been retrieved that would be needed.
8. **Current Work:** What was being worked on when this summary was requested.
9. **Next Steps:** What should happen next to complete the answer.

Original query: {query}

Data retrieved from tool calls:
{tool_results}

REMINDER: Do NOT call any tools. Respond with plain text only — the 9 numbered sections above. Tool calls will be rejected."""


def format_compact_summary(raw_summary: str) -> str:
    """Clean and format the LLM's compaction summary."""
    return raw_summary.strip()


def build_compact_resume_message(summary: str) -> str:
    """Build the message that frames the compaction summary for the main LLM."""
    return f"""This session is being continued from a previous research session that ran out of context. The summary below covers the data retrieved and analysis performed so far.

{summary}

Continue working toward answering the query without asking the user any further questions. Resume directly — do not acknowledge the summary, do not recap what was happening. Pick up the research as if the break never happened."""


def should_macro_compact(
    total_tokens: int,
    context_limit: int = DEFAULT_CONTEXT_LIMIT,
    trigger_ratio: float = MACRO_COMPACT_TRIGGER_RATIO,
    tool_result_count: int = 0,
) -> bool:
    """Check if macro-compaction threshold is reached."""
    if tool_result_count < MIN_TOOL_RESULTS_FOR_COMPACTION:
        return False
    return total_tokens >= context_limit * trigger_ratio


def compute_9_section_checkpoint(
    query: str,
    messages: list[dict],
    tool_results: list[dict],
) -> str:
    """
    Build a 9-section checkpoint summary from raw message data.
    This is the programmatic version used when no LLM is available for compaction.
    """
    lines = []
    lines.append("1. Primary Request:")
    lines.append(f"   {query}")
    lines.append("")

    # Key concepts: extract tickers and metrics mentioned
    concepts = set()
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            import re
            tickers = re.findall(r'\b[A-Z]{1,5}\b', content)
            concepts.update(tickers)

    metric_keywords = [
        "revenue", "net income", "EPS", "P/E", "P/E ratio", "PEG",
        "debt", "equity", "D/E", "FCF", "free cash flow", "margin",
        "ROE", "ROA", "beta", "market cap", "enterprise value",
        "dividend", "yield", "P/B", "price to book", "sector",
    ]
    for kw in metric_keywords:
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and kw.lower() in content.lower():
                concepts.add(kw)
                break

    lines.append("2. Key Concepts:")
    for c in sorted(concepts):
        lines.append(f"   - {c}")
    lines.append("")

    # Errors & Fixes
    errors = []
    for tr in tool_results:
        if "error" in str(tr.get("result", "")).lower():
            errors.append(f"   - {tr.get('tool', 'unknown')}: {str(tr.get('result', ''))[:200]}")

    lines.append("4. Errors & Fixes:")
    if errors:
        lines.extend(errors)
    else:
        lines.append("   - None")
    lines.append("")

    # Data retrieved summary
    lines.append("5. Problem Solving:")
    for tr in tool_results:
        tool = tr.get("tool", "")
        if "error" not in str(tr.get("result", "")).lower():
            lines.append(f"   - [{tool}]: Data retrieved successfully")
    lines.append("")

    lines.append("9. Next Steps:")
    lines.append("   - Continue analysis from the checkpoint above")
    lines.append("   - Re-query any data that was truncated or missing")

    return "\n".join(lines)
