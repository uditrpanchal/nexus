"""
Cron Worker Task Scheduling for NEXUS.

Implements:
  - Background job scheduling with cron expressions
  - Decoupled notification abstractions (WhatsApp/Slack gateways)
  - Group chat @mention tracking support
  - Persistent job store at .heon/cron/
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


CRON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ))),
    ".heon", "cron"
)


@dataclass
class CronJob:
    """A scheduled cron job."""
    id: str
    name: str
    schedule: str  # cron expression or "every 30m"
    prompt: str
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_run_at: Optional[float] = None
    last_run_status: Optional[str] = None
    last_error: Optional[str] = None
    notification_channels: list[str] = field(default_factory=list)  # "whatsapp", "slack"
    mention_users: list[str] = field(default_factory=list)  # @mention targets
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationConfig:
    """Configuration for a notification channel."""
    channel: str  # "whatsapp", "slack", "telegram"
    enabled: bool = True
    webhook_url: str = ""
    chat_id: str = ""
    format_template: str = "markdown"  # "markdown", "plain", "html"
    mention_prefix: str = "@"  # prefix for @mentions


class CronStore:
    """Persistent job store using JSON file."""

    def __init__(self, store_dir: str = CRON_DIR):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.store_file = self.store_dir / "jobs.json"
        self._jobs: dict[str, CronJob] = {}
        self._load()

    def _load(self):
        """Load jobs from disk."""
        if self.store_file.exists():
            try:
                data = json.loads(self.store_file.read_text())
                for job_data in data.get("jobs", []):
                    job = CronJob(**job_data)
                    self._jobs[job.id] = job
            except (json.JSONDecodeError, TypeError):
                pass

    def _save(self):
        """Save jobs to disk."""
        data = {
            "jobs": [asdict(job) for job in self._jobs.values()],
            "updated_at": time.time(),
        }
        self.store_file.write_text(json.dumps(data, indent=2, default=str))

    def create_job(self, job: CronJob) -> CronJob:
        """Create a new cron job."""
        self._jobs[job.id] = job
        self._save()
        return job

    def get_job(self, job_id: str) -> Optional[CronJob]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[CronJob]:
        return list(self._jobs.values())

    def update_job(self, job_id: str, **updates) -> Optional[CronJob]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        for key, value in updates.items():
            if hasattr(job, key):
                setattr(job, key, value)
        job.updated_at = time.time()
        self._save()
        return job

    def delete_job(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save()
            return True
        return False

    def get_due_jobs(self) -> list[CronJob]:
        """Get jobs that are due to run."""
        now = time.time()
        due = []
        for job in self._jobs.values():
            if not job.enabled:
                continue
            # Simple interval-based scheduling
            if job.schedule.startswith("every "):
                parts = job.schedule.split()
                if len(parts) >= 2:
                    try:
                        amount = int(parts[1][:-1])  # "30m" -> 30
                        unit = parts[1][-1]  # m, h, d
                        multipliers = {"m": 60, "h": 3600, "d": 86400}
                        interval = amount * multipliers.get(unit, 60)

                        if job.last_run_at is None or (now - job.last_run_at) >= interval:
                            due.append(job)
                    except (ValueError, IndexError):
                        pass
        return due


class NotificationRouter:
    """
    Decoupled notification abstraction for cron job outputs.

    Supports formatting profiles for WhatsApp, Slack, and other gateways.
    """

    def __init__(self):
        self.channels: dict[str, NotificationConfig] = {}

    def register_channel(self, config: NotificationConfig):
        """Register a notification channel."""
        self.channels[config.channel] = config

    def format_message(
        self,
        text: str,
        channel: str = "plain",
        mentions: Optional[list[str]] = None,
    ) -> dict[str, str]:
        """
        Format a message for different channels.
        Returns dict with channel name -> formatted text.
        """
        formatted = {}

        for ch_name, config in self.channels.items():
            if not config.enabled:
                continue

            fmt_text = text
            # Add @mentions
            if mentions and config.mention_prefix:
                mention_str = " ".join(
                    f"{config.mention_prefix}{user}" for user in mentions
                )
                fmt_text = f"{mention_str}\n{fmt_text}"

            # Strip markdown for plain-text channels
            if config.format_template == "plain":
                fmt_text = self._strip_markdown(fmt_text)

            formatted[ch_name] = fmt_text

        return formatted

    def _strip_markdown(self, text: str) -> str:
        """Basic markdown-to-plain conversion."""
        import re
        # Remove bold/italic
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)
        # Remove links
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        # Remove code blocks
        text = re.sub(r'```[^`]*```', '[code block]', text)
        return text


def create_cron_job(
    name: str,
    schedule: str,
    prompt: str,
    channels: Optional[list[str]] = None,
    mention_users: Optional[list[str]] = None,
) -> CronJob:
    """Create a cron job with a unique ID."""
    import uuid
    job = CronJob(
        id=str(uuid.uuid4())[:8],
        name=name,
        schedule=schedule,
        prompt=prompt,
        notification_channels=channels or [],
        mention_users=mention_users or [],
    )
    return job
