from __future__ import annotations

from typing import Any


def render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:
    """Render canonical payloads once while preserving every connection."""
    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    seen: set[str] = set()
    logical_lines: list[str] = []
    collapsed_duplicate_count = 0
    for index, item in enumerate(items):
        declared = str(item.get("payload_sha256", ""))
        identity = declared if declared else "unhashed:" + str(index)
        content = str(item.get("content", "")).replace("\n", " ")
        if identity not in seen:
            seen.add(identity)
            logical_lines.append("PAYLOAD | " + identity + " | " + content)
        else:
            collapsed_duplicate_count += 1
        logical_lines.append(
            "CONNECTION | " + " | ".join((
                str(item.get("ref", "unknown")),
                str(item.get("origin", "unknown")),
                str(item.get("kind", "unknown")),
                str(item.get("outcome", "unknown")),
                str(item.get("path", "unknown")),
            ))
        )
    header = "canonical_payload_count=" + str(len(seen)) + " | collapsed_duplicate_count=" + str(collapsed_duplicate_count)
    output: list[str] = []
    used = 0
    for line in [header] + logical_lines:
        addition = line if not output else "\n" + line
        if used + len(addition) > max_chars:
            continue
        output.append(line)
        used += len(addition)
    return "\n".join(output)
