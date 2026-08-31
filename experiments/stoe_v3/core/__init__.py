"""SToE v3 core: information field substrate, seed loading, operators, LLM."""

from .field import (
    InformationField,
    EDGE_TYPES,
    CATEGORIES,
    assert_no_deletion_methods,
)
from .seed_loader import load_seed_if_empty
from .llm import LLMClient, OllamaClient, OllamaError, MockLLM
from .operators import (
    Operator,
    OperatorResult,
    ConnectionOp,
    SynergyOp,
    RecursionOp,
    DisruptionOp,
    RemovalOp,
    SummarizeOp,
    default_registry,
)
from .evaluator import (
    Verdict,
    StructuralEvaluator,
)

__all__ = [
    # field
    "InformationField",
    "EDGE_TYPES",
    "CATEGORIES",
    "assert_no_deletion_methods",
    "load_seed_if_empty",
    # llm
    "LLMClient",
    "OllamaClient",
    "OllamaError",
    "MockLLM",
    # operators
    "Operator",
    "OperatorResult",
    "ConnectionOp",
    "SynergyOp",
    "RecursionOp",
    "DisruptionOp",
    "RemovalOp",
    "SummarizeOp",
    "default_registry",
    # evaluator
    "Verdict",
    "StructuralEvaluator",
]
