"""Initial lexical research-context selector.

This intentionally small implementation is the active version at the beginning
of the first rebuild cycle. Its limitation is measured before a successor is
requested.
"""

from __future__ import annotations

import re


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}


def select_context(
    observer_state: dict,
    items: list[dict],
    max_items: int,
    max_chars: int,
) -> list[str]:
    """Return refs ranked by lexical overlap with the current goal."""
    query = _tokens(str(observer_state.get("goal", "")))
    ranked: list[tuple[float, int, str, dict]] = []
    for item in items:
        content_tokens = _tokens(str(item.get("content", "")))
        overlap = len(query & content_tokens) / max(1, len(query | content_tokens))
        ranked.append((overlap, int(item.get("created_order", 0)), str(item["ref"]), item))

    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
    selected: list[str] = []
    used_chars = 0
    for _score, _order, ref, item in ranked:
        size = len(str(item.get("content", "")))
        if len(selected) >= max_items:
            break
        if used_chars + size > max_chars:
            continue
        selected.append(ref)
        used_chars += size
    return selected
