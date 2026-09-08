from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Callable

from .selection_policy import load_policy, policy_selector


Selector = Callable[[dict, list[dict], int, int], list[str]]

# These are immutable compatibility releases, not a general Python plugin API.
# Any future generated artifact must be a declarative selection policy.
LEGACY_RELEASES = {
    "v1.py": "7f4b5aa6b50b4f504915792b88b681b68cf6864f669f4504876a9bea3406d56c",
    "generated_20260906T125305Z_92e7e913.py": "d37f48335f87c4c4370ea78d7719cf3a79aa26ef41b0911c81f448f7828d2cb1",
}
ARTIFACT_TYPES = {"legacy_python", "declarative_policy"}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_selector(path: str | Path) -> Selector:
    """Load an immutable legacy release only.

    This compatibility function intentionally rejects arbitrary Python, even if
    it would have passed the former AST gate.
    """
    return load_legacy_selector(path)


def load_legacy_selector(path: str | Path) -> Selector:
    source_path = Path(path).resolve()
    expected = LEGACY_RELEASES.get(source_path.name)
    if (
        expected is None
        or source_path.parent.name != "versions"
        or source_path.parent.parent.name != "context_selector"
        or sha256_file(source_path) != expected
    ):
        raise PermissionError("Python selector is not an immutable allowlisted legacy release")
    module_name = f"stoe_selector_{sha256_file(source_path)[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load selector from {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    selector = getattr(module, "select_context", None)
    if not callable(selector):
        raise TypeError("candidate must define callable select_context")
    return selector


def load_selector_artifact(path: str | Path, artifact_type: str) -> Selector:
    if artifact_type not in ARTIFACT_TYPES:
        raise ValueError(f"unsupported selector artifact type: {artifact_type}")
    if artifact_type == "legacy_python":
        return load_legacy_selector(path)
    return policy_selector(load_policy(path))


def infer_artifact_type(path: str | Path) -> str:
    source_path = Path(path)
    return "declarative_policy" if source_path.name.endswith(".policy.json") else "legacy_python"


def validate_selection(
    selected: object,
    items: list[dict],
    max_items: int,
    max_chars: int,
) -> list[str]:
    if not isinstance(selected, list) or not all(isinstance(ref, str) for ref in selected):
        raise TypeError("selector must return list[str]")
    if len(selected) != len(set(selected)):
        raise ValueError("selector returned duplicate refs")
    if len(selected) > max_items:
        raise ValueError("selector exceeded max_items")
    by_ref = {str(item["ref"]): item for item in items}
    missing = [ref for ref in selected if ref not in by_ref]
    if missing:
        raise ValueError(f"selector returned unknown refs: {missing}")
    used_chars = sum(len(str(by_ref[ref].get("content", ""))) for ref in selected)
    if used_chars > max_chars:
        raise ValueError("selector exceeded max_chars")
    return selected
