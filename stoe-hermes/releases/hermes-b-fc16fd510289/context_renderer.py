from __future__ import annotations

import hashlib
from typing import Any


def render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:
    """Render one canonical payload per hash and every distinct connection."""
    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    logical_lines: list[str] = []
    seen_payloads: dict[str, str] = {}
    connections: list[str] = []
    collapsed = 0
    canonical_payloads = 0
    collapsed_duplicates = 0
    for index, item in enumerate(items):
        content = str(item.get("content", ""))
        computed = hashlib.sha256(content.encode("utf-8")).hexdigest()
        declared = str(item.get("sha256") or computed)
        if declared != computed:
            declared = computed
        if declared not in seen_payloads:
            seen_payloads[declared] = content
            logical_lines.append(f"PAYLOAD | {declared} | {content}")
            canonical_payloads += 1
        else:
            collapsed += 1
            collapsed_duplicates += 1
        connections.append(
            "CONNECTION | "
            + " | ".join(
                str(item.get(key, ""))
                for key in ("ref", "origin", "kind", "outcome", "path", "relation", "direction", "provenance")
            )
            + f" | payload_sha256={declared}"
        )
    logical_lines = [
        f"[stoe-memory] payloads={canonical_payloads} connections={len(connections)} collapsed={collapsed} canonical_payloads={canonical_payloads} collapsed_duplicates={collapsed_duplicates}",
        *logical_lines,
        *connections,
    ]
    included: list[str] = []
    used = 0
    for line in logical_lines:
        addition = len(line) + (1 if included else 0)
        if used + addition > max_chars:
            break
        included.append(line)
        used += addition
    return "\n".join(included)
