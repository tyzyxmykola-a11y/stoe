from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class InformationPoint:
    ref: str
    content: str
    kind: str
    outcome: str = "unknown"
    visible: bool = True
    created_order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class Edge:
    source: str
    target: str
    relation: str


@dataclass(slots=True)
class ObserverState:
    ref: str
    current_question: str
    current_goal: str
    active_constraints: list[str]
    changed_constraints: list[str]
    current_reasoning_ref: str | None = None
    recent_evidence: list[str] = field(default_factory=list)
    traversal_history: list[str] = field(default_factory=list)

    def relevance_text(self) -> str:
        return "\n".join([
            self.current_question,
            self.current_goal,
            *self.active_constraints,
            *self.changed_constraints,
            *self.recent_evidence,
        ])


@dataclass(slots=True)
class CandidateTrace:
    current_state_ip: str
    candidate_ip: str
    path: list[dict[str, Any]]
    edge_directions: list[str]
    edge_types: list[str]
    structural_score: float
    goal_relevance_score: float
    state_change_score: float
    provenance_relevance_score: float
    failure_relevance_score: float
    distance_penalty: float
    redundancy_penalty: float
    stale_locality_penalty: float
    final_score: float
    eligible: bool
    selected: bool
    reason: str
    canonical_tie_key: str
    origin: str


@dataclass(slots=True)
class RetrievalResult:
    refs: list[str]
    method: str
    scores: list[float]
    traces: list[CandidateTrace] = field(default_factory=list)
    realized_artifact_count: int = 0
    serialization: dict[str, Any] | None = None


@dataclass(slots=True)
class TaskDefinition:
    id: str
    family: str
    subset: str
    question: str
    goal: str
    active_constraints: list[str]
    changed_constraints: list[str]
    expected_answer: str
    focal: dict[str, Any]
    constraint: dict[str, Any]
    state_change: dict[str, Any]
    recent: dict[str, Any]
    evaluation: dict[str, Any]
    distractors: list[dict[str, Any]]
    topology_target_ref: str = "IP_00002"
    metadata: dict[str, Any] = field(default_factory=dict)
