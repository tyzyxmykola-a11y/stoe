from __future__ import annotations

from typing import Any


def render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:
    """Render a bounded development-context summary.

    This deliberately small, non-security-critical component is owned by the
    agent.  The trusted supervisor supplies already-authorized records; this
    function only formats them and has no authority over retrieval or files.
    """

    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    lines: list[str] = []
    used = 0
    for item in items:
        line = " | ".join(
            (
                str(item.get("ref", "unknown")),
                str(item.get("origin", "unknown")),
                str(item.get("kind", "unknown")),
                str(item.get("outcome", "unknown")),
                str(item.get("content", "")).replace("\n", " "),
            )
        )
        addition = line if not lines else "\n" + line
        if used + len(addition) > max_chars:
            continue
        lines.append(line)
        used += len(addition)
    return "\n".join(lines)
