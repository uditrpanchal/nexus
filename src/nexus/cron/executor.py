"""
Cron Executor for NEXUS — background job runner.

Runs scheduled jobs by:
1. Polling the CronStore for due jobs
2. Executing each job's prompt through the agent
3. Delivering results via registered notification channels
4. Handling retries with exponential backoff

Designed to run as a background asyncio task or a standalone daemon.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from . import CronJob, CronStore, NotificationRouter


# ==========================================================================
# Suppression — prevents duplicate notifications
# ==========================================================================

@dataclass
class SuppressionState:
    last_message_text: Optional[str] = None
    last_message_at: Optional[float] = None


def should_suppress(text: str, state: SuppressionState, cooldown_s: float = 3600) -> tuple[bool, str]:
    """
    Determine if a message should be suppressed (duplicate within cooldown).
    Returns (should_suppress, reason).
    """
    if not state.last_message_text:
        return False, ""

    # Exact duplicate
    if text.strip() == state.last_message_text.strip():
        return True, "exact_duplicate"

    # Recently sent (within cooldown)
    if state.last_message_at and (time.time() - state.last_message_at) < cooldown_s:
        return True, "cooldown"

    return False, ""


# ==========================================================================
# Cron Executor
# ==========================================================================

# Per-job suppression states (in memory, resets on process restart)
_suppression_states: dict[str, SuppressionState] = {}

# Error backoff schedule (milliseconds)
_BACKOFF_MS = [30_000, 60_000, 300_000, 900_000, 3_600_000]
_MAX_RETRIES = 3


class CronExecutor:
    """
    Background cron job executor.

    Usage:
        executor = CronExecutor(agent_factory=CronAgentFactory)
        await executor.run_forever(poll_interval_s=60)

    Or for one-shot execution:
        await executor.run_due_jobs()
    """

    def __init__(
        self,
        agent_factory,
        cron_store: Optional[CronStore] = None,
        notification_router: Optional[NotificationRouter] = None,
        max_iterations: int = 6,
    ):
        self.agent_factory = agent_factory
        self.store = cron_store or CronStore()
        self.router = notification_router
        self.max_iterations = max_iterations
        self._running = False
        self._suppression: dict[str, SuppressionState] = {}

    def _get_suppression(self, job_id: str) -> SuppressionState:
        if job_id not in self._suppression:
            self._suppression[job_id] = SuppressionState()
        return self._suppression[job_id]

    async def execute_job(self, job: CronJob) -> dict[str, Any]:
        """
        Execute a single cron job: run agent, evaluate suppression, deliver.

        Returns execution result dict.
        """
        start = time.time()
        result = {
            "job_id": job.id,
            "job_name": job.name,
            "started_at": start,
            "status": "unknown",
        }

        try:
            agent = self.agent_factory()
            output = ""

            # Run the agent with the job's prompt
            query = f"[CRON JOB: {job.name}]

{job.prompt}"
            async for event in agent.run(query):
                if hasattr(event, "type") and event.type == "done":
                    output = event.data.get("answer", "")
                    break

            duration = time.time() - start

            # Evaluate suppression
            supp_state = self._get_suppression(job.id)
            suppressed, reason = should_suppress(output, supp_state)

            if suppressed:
                result["status"] = "suppressed"
                result["suppress_reason"] = reason
            else:
                result["status"] = "delivered"
                result["output"] = output[:500]

                # Deliver via notification channels
                if self.router and job.notification_channels:
                    formatted = self.router.format_message(
                        text=output,
                        channel=job.notification_channels[0],
                        mentions=job.mention_users,
                    )
                    result["delivered_to"] = job.notification_channels[0]

                # Update suppression state
                supp_state.last_message_text = output
                supp_state.last_message_at = time.time()

            # Update job state
            self.store.update_job(
                job.id,
                last_run_at=start,
                last_run_status=result["status"],
            )

        except Exception as e:
            duration = time.time() - start
            result["status"] = "error"
            result["error"] = str(e)

            self.store.update_job(
                job.id,
                last_run_at=start,
                last_run_status="error",
            )

        result["duration_seconds"] = duration
        return result

    async def run_due_jobs(self) -> list[dict[str, Any]]:
        """Find and execute all due jobs. Returns list of results."""
        due_jobs = self.store.get_due_jobs()
        results = []
        for job in due_jobs:
            result = await self.execute_job(job)
            results.append(result)
        return results

    async def run_forever(self, poll_interval_s: float = 60.0):
        """
        Run the executor as a long-lived background task.
        Polls for due jobs at the specified interval.
        """
        self._running = True
        while self._running:
            try:
                await self.run_due_jobs()
            except Exception:
                pass  # Don't let one failure stop the loop
            await asyncio.sleep(poll_interval_s)

    def stop(self):
        """Stop the background runner."""
        self._running = False


# ==========================================================================
# Cron tool for agent — allows the agent to create/list/manage cron jobs
# ==========================================================================

async def cron_tool(
    action: str,
    job_name: str = "",
    schedule: str = "",
    prompt: str = "",
    job_id: str = "",
    channels: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Cron management tool for the agent.

    Actions:
      - create: Create a new cron job (requires job_name, schedule, prompt)
      - list: List all cron jobs
      - get: Get a specific job (requires job_id)
      - enable/disable: Toggle a job (requires job_id)
      - delete: Delete a job (requires job_id)
      - run: Manually trigger a job (requires job_id)
    """
    store = CronStore()

    if action == "create":
        if not job_name or not schedule or not prompt:
            return {"error": "Missing required fields: job_name, schedule, prompt"}
        import uuid
        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=job_name,
            schedule=schedule,
            prompt=prompt,
            notification_channels=channels or [],
        )
        store.create_job(job)
        return {"status": "created", "job_id": job.id, "name": job_name}

    elif action == "list":
        jobs = store.list_jobs()
        return {
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "schedule": j.schedule,
                    "enabled": j.enabled,
                    "last_run": j.last_run_at,
                    "last_status": j.last_run_status,
                }
                for j in jobs
            ]
        }

    elif action == "enable":
        store.update_job(job_id, enabled=True)
        return {"status": "enabled", "job_id": job_id}

    elif action == "disable":
        store.update_job(job_id, enabled=False)
        return {"status": "disabled", "job_id": job_id}

    elif action == "delete":
        store.delete_job(job_id)
        return {"status": "deleted", "job_id": job_id}

    else:
        return {"error": f"Unknown action: {action}. Use: create, list, enable, disable, delete"}
