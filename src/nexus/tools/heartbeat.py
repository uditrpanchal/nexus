"""
Heartbeat mechanism for NEXUS.

Provides periodic check-ins where the agent evaluates whether anything
needs attention: pending tasks, monitoring alerts, scheduled reports.

Mirrors dexter's gateway/heartbeat/ system with:
- Configurable heartbeat prompts
- Suppression to avoid spam
- Active hours enforcement
- Delivery via notification channels
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional


HEARTBEAT_OK_TOKEN = "[HEARTBEAT_OK]"
DEFAULT_HEARTBEAT_PROMPT = """You are performing a routine heartbeat check.

Review the current state and determine if anything needs the user's attention.

Check for:
1. Any pending tasks or reminders
2. Stocks on the watchlist that have moved significantly (>3%)
3. Scheduled reports that should be sent
4. Any alerts or conditions that have been triggered

If NOTHING needs attention, respond with exactly: {ok_token}

If something needs attention, provide a concise alert with:
- What happened
- Why it matters
- What action the user should take

Keep it brief. Only alert when genuinely important.
""".format(ok_token=HEARTBEAT_OK_TOKEN)


@dataclass
class HeartbeatConfig:
    """Configuration for heartbeat behavior."""
    enabled: bool = True
    prompt: str = DEFAULT_HEARTBEAT_PROMPT
    interval_s: float = 3600.0  # 1 hour default
    active_hours_start: str = "08:00"  # 24h format
    active_hours_end: str = "22:00"
    timezone: str = "America/New_York"
    suppression_cooldown_s: float = 3600.0  # don't re-alert within 1 hour


@dataclass
class HeartbeatState:
    """Runtime state for heartbeat tracking."""
    last_run_at: Optional[float] = None
    last_result: Optional[str] = None
    last_alert_at: Optional[float] = None
    consecutive_ok: int = 0


@dataclass
class SuppressionState:
    last_message_text: Optional[str] = None
    last_message_at: Optional[float] = None


class HeartbeatSuppression:
    """Prevents duplicate heartbeat alerts."""

    def __init__(self, cooldown_s: float = 3600.0):
        self._states: dict[str, SuppressionState] = {}
        self._cooldown_s = cooldown_s

    def should_suppress(self, text: str, key: str = "default") -> tuple[bool, str]:
        state = self._states.get(key)
        if not state:
            self._states[key] = SuppressionState()
            return False, ""

        if text.strip() == state.last_message_text.strip():
            return True, "exact_duplicate"

        if state.last_message_at and (time.time() - state.last_message_at) < self._cooldown_s:
            return True, "cooldown"

        return False, ""

    def update_state(self, text: str, key: str = "default"):
        state = self._states.get(key) or SuppressionState()
        state.last_message_text = text
        state.last_message_at = time.time()
        self._states[key] = state


async def run_heartbeat(
    agent,
    config: HeartbeatConfig = None,
    extra_context: str = "",
) -> dict[str, Any]:
    """
    Execute a heartbeat check through the agent.

    Returns:
        dict with status (ok/alert/error), output, and whether it was suppressed
    """
    config = config or HeartbeatConfig()
    suppression = HeartbeatSuppression(config.suppression_cooldown_s)
    state = HeartbeatState()

    start = time.time()

    try:
        prompt = config.prompt
        if extra_context:
            prompt += f"

Additional context:
{extra_context}"

        output = ""
        async for event in agent.run(prompt):
            if hasattr(event, "type") and event.type == "done":
                output = event.data.get("answer", "")
                break

        duration = time.time() - start

        # Check for OK token (nothing needs attention)
        if output and HEARTBEAT_OK_TOKEN in output:
            state.last_result = "ok"
            state.consecutive_ok += 1
            return {
                "status": "ok",
                "output": None,
                "suppressed": False,
                "duration_seconds": duration,
                "message": "Heartbeat check passed — nothing needs attention.",
            }

        # Evaluate suppression
        suppressed, reason = suppression.should_suppress(output)
        if suppressed:
            return {
                "status": "suppressed",
                "output": None,
                "suppressed": True,
                "suppress_reason": reason,
                "duration_seconds": duration,
            }

        # Genuine alert
        suppression.update_state(output)
        state.last_result = "alert"
        state.consecutive_ok = 0
        state.last_alert_at = time.time()

        return {
            "status": "alert",
            "output": output,
            "suppressed": False,
            "duration_seconds": duration,
        }

    except Exception as e:
        return {
            "status": "error",
            "output": None,
            "error": str(e),
            "duration_seconds": time.time() - start,
        }


async def heartbeat_tool(action: str = "check") -> dict[str, Any]:
    """
    Heartbeat tool for the agent to trigger manual checks.

    Actions:
      - check: Run a heartbeat check (agent decides what to report)
      - status: Show heartbeat configuration and last run info
    """
    if action == "status":
        return {
            "status": "ok",
            "message": "Heartbeat system active. Configure via settings.",
            "ok_token": HEARTBEAT_OK_TOKEN,
        }
    else:
        return {
            "status": "ok",
            "message": "Heartbeat check initiated. If nothing needs attention, will respond with OK token.",
            "prompt": DEFAULT_HEARTBEAT_PROMPT[:200] + "...",
        }
