"""Single authoritative model-facing contract for StoeCoder navigation tools.

Several trusted adapters wrap ``_generate_role``. If each wrapper rewrites tool
descriptions, installation order can silently discard newer guidance. Install
this adapter before those wrappers so it runs innermost and writes the final
canonical descriptions immediately before the core generator receives them.
"""

from __future__ import annotations

from types import MethodType
from typing import Any

_SEARCH_CONTRACT = (
    "trusted compact repository search under an optional repository-relative path; "
    "natural-language multi-term queries may fall back to ranked keyword coverage and missing bases may fall back to repository root; "
    "results expose bounded matched_files/excerpts and trusted feedback normalizes them into typed evidence_items with source_kind, polarity, path/span and stable identity; "
    "source_kind is provenance rather than truth; new evidence is conserved, but only novel evidence connected to the operator objective or an already connected evidence path counts as exploration progress; "
    "changing query wording without changing the evidence set is not progress"
)

_INSPECT_CONTRACT = (
    "read one repository-relative file; for a large/truncated file, optional query requests bounded matching line windows from anywhere in that file; "
    "declaration-shaped anchors such as 'def name' or 'class Name' require that declaration to exist while plain identifiers may navigate to longer related identifiers; "
    "trusted feedback normalizes positive and negative observations into typed evidence_items; negative evidence is conserved; "
    "only novel evidence connected to the operator objective or an already connected evidence path counts as exploration progress, so do not deepen an unrelated file merely because each read is technically new"
)


def install_tool_contracts(coder: Any) -> None:
    """Install one final source of truth for coder-facing search/inspect text."""

    if getattr(coder, "_stoe_tool_contracts_installed", False):
        return
    original_generate = coder._generate_role

    def contracted_generate(self, *, role: str, prompt: dict[str, Any], **kwargs):
        if role == "coder" and isinstance(prompt, dict):
            prompt = dict(prompt)
            tools = dict(prompt.get("available_tools") or {})
            tools["search"] = _SEARCH_CONTRACT
            tools["inspect"] = _INSPECT_CONTRACT
            prompt["available_tools"] = tools
        return original_generate(role=role, prompt=prompt, **kwargs)

    coder._generate_role = MethodType(contracted_generate, coder)
    coder._stoe_tool_contracts_installed = True
