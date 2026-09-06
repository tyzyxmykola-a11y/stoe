from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Callable


Selector = Callable[[dict, list[dict], int, int], list[str]]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_selector(path: str | Path) -> Selector:
    source_path = Path(path).resolve()
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
