"""
Text formatting utilities for display output.
"""

from typing import Any


def format_full_analysis(data: dict[str, Any], title: str = "") -> str:
    """Format a full analysis dict into readable markdown."""
    lines = []
    if title:
        lines.append(f"## {title}")
        lines.append("")

    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"### {key}")
            for k, v in value.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")
        elif isinstance(value, list):
            lines.append(f"### {key}")
            for item in value[:10]:
                if isinstance(item, dict):
                    row = " | ".join(f"{k}: {v}" for k, v in item.items())
                    lines.append(f"- {row}")
                else:
                    lines.append(f"- {item}")
            lines.append("")
        else:
            lines.append(f"**{key}**: {value}")

    return "\n".join(lines)
