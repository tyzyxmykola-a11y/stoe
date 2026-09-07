from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LINEAGE_SCHEMA_VERSION = 1


class ContinuityDivergenceError(RuntimeError):
    """Raised when two persisted states have no verified succession relation."""


@dataclass(frozen=True)
class Lineage:
    kind: str
    stream_id: str
    branch_id: str
    identity: str
    parent_identity: str | None
    ancestor_identities: tuple[str, ...]

    def to_json(self, *, identity_field: str) -> dict[str, Any]:
        return {
            "schema_version": LINEAGE_SCHEMA_VERSION,
            "kind": self.kind,
            "stream_id": self.stream_id,
            "branch_id": self.branch_id,
            identity_field: self.identity,
            f"parent_{identity_field}": self.parent_identity,
            f"ancestor_{identity_field}s": list(self.ancestor_identities),
        }


def compare_lineage(left: Lineage, right: Lineage) -> str:
    """Return equal/ahead/behind, or fail when succession cannot be proven."""
    if left.kind != right.kind:
        raise ContinuityDivergenceError(
            f"continuity kind mismatch: {left.kind!r} versus {right.kind!r}"
        )
    if left.identity == right.identity:
        return "equal"
    if left.stream_id != right.stream_id:
        raise ContinuityDivergenceError(
            f"divergent {left.kind} streams: {left.stream_id} versus {right.stream_id}"
        )
    if left.branch_id != right.branch_id:
        raise ContinuityDivergenceError(
            f"cross-branch {left.kind} histories: {left.branch_id!r} versus {right.branch_id!r}"
        )
    if right.identity in left.ancestor_identities:
        return "ahead"
    if left.identity in right.ancestor_identities:
        return "behind"
    raise ContinuityDivergenceError(
        f"divergent {left.kind} histories at {left.identity[:12]} and {right.identity[:12]}"
    )


def advance_lineage(lineage: Lineage, identity: str) -> Lineage:
    if identity == lineage.identity:
        return lineage
    ancestors = tuple(dict.fromkeys((*lineage.ancestor_identities, lineage.identity)))
    return Lineage(
        kind=lineage.kind,
        stream_id=lineage.stream_id,
        branch_id=lineage.branch_id,
        identity=identity,
        parent_identity=lineage.identity,
        ancestor_identities=ancestors,
    )
