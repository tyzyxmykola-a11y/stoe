from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable


class ContextBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class TokenEstimator:
    """Token counter with an explicit conservative fallback.

    A caller may inject the exact tokenizer for the frozen provider model. Ollama
    does not expose that tokenizer through its generation API, so the default is
    deliberately labelled as an estimate rather than an exact token count.
    """

    tokenizer: Callable[[str], Any] | None = None
    tokenizer_name: str = "conservative_utf8_bytes_div_3"

    @property
    def exact(self) -> bool:
        return self.tokenizer is not None

    def estimate(self, text: str) -> int:
        value = str(text)
        if not value:
            return 0
        if self.tokenizer is not None:
            encoded = self.tokenizer(value)
            if hasattr(encoded, "ids"):
                encoded = encoded.ids
            return len(encoded)
        # Three UTF-8 bytes per token is intentionally more conservative than
        # the common four-characters heuristic, especially for mixed scripts.
        return max(1, math.ceil(len(value.encode("utf-8")) / 3))

    def metadata(self) -> dict[str, Any]:
        return {
            "method": self.tokenizer_name,
            "exact": self.exact,
            "limitation": (
                "Exact model tokenizer supplied by caller."
                if self.exact
                else "Estimate only; reconcile with provider prompt_eval_count when available."
            ),
        }


class TokenBudgetManager:
    def __init__(
        self,
        *,
        context_limit_tokens: int = 8192,
        checkpoint_reserve_tokens: int = 512,
        estimator: TokenEstimator | None = None,
    ) -> None:
        if context_limit_tokens <= 0 or checkpoint_reserve_tokens < 0:
            raise ValueError("invalid context budget")
        self.context_limit_tokens = context_limit_tokens
        self.checkpoint_reserve_tokens = checkpoint_reserve_tokens
        self.estimator = estimator or TokenEstimator()

    def plan(
        self,
        *,
        system: str,
        prompt: str,
        reserved_generation_tokens: int,
        categories: dict[str, str] | None = None,
        truncation_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if reserved_generation_tokens < 0:
            raise ValueError("reserved_generation_tokens must be non-negative")
        system_tokens = self.estimator.estimate(system)
        prompt_tokens = self.estimator.estimate(prompt)
        reserved = reserved_generation_tokens + self.checkpoint_reserve_tokens
        estimated_total = system_tokens + prompt_tokens + reserved
        allocation = {
            name: self.estimator.estimate(text)
            for name, text in (categories or {"task_context": prompt}).items()
        }
        for required in ("task_context", "retrieved_material", "tool_results"):
            allocation.setdefault(required, 0)
        return {
            "context_limit_tokens": self.context_limit_tokens,
            "estimator": self.estimator.metadata(),
            "estimated": {
                "system_instructions": system_tokens,
                "prompt_total": prompt_tokens,
                "category_attribution": allocation,
                "reserved_generation": reserved_generation_tokens,
                "checkpoint_reserve": self.checkpoint_reserve_tokens,
                "total_with_reserves": estimated_total,
                "remaining": self.context_limit_tokens - estimated_total,
            },
            "fits": estimated_total <= self.context_limit_tokens,
            "truncation_events": list(truncation_events or []),
            "note": "Category attribution explains prompt composition; prompt_total is counted once.",
        }

    def require_plan(self, **kwargs: Any) -> dict[str, Any]:
        plan = self.plan(**kwargs)
        if not plan["fits"]:
            raise ContextBudgetExceeded(
                "estimated context exceeds fixed limit while preserving generation and checkpoint reserves: "
                f"{plan['estimated']['total_with_reserves']} > {self.context_limit_tokens}"
            )
        return plan


def compact_text(text: str, *, max_tokens: int, estimator: TokenEstimator) -> tuple[str, dict[str, Any] | None]:
    value = str(text)
    original_tokens = estimator.estimate(value)
    if original_tokens <= max_tokens:
        return value, None
    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if estimator.estimate(value[:middle]) <= max_tokens:
            low = middle
        else:
            high = middle - 1
    preview = value[:low]
    event = {
        "reason": "token_budget",
        "original_chars": len(value),
        "visible_chars": len(preview),
        "estimated_original_tokens": original_tokens,
        "estimated_visible_tokens": estimator.estimate(preview),
        "full_content_preserved": True,
    }
    return preview, event
