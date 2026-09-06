from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from .investigation import evaluate_public_selector
from .selector_loader import load_selector


class BoundedTextSink:
    def __init__(self, limit: int = 16_000) -> None:
        self.limit = limit
        self.parts: list[str] = []
        self.seen = 0

    def write(self, value: str) -> int:
        text = str(value)
        self.seen += len(text)
        remaining = self.limit - sum(len(part) for part in self.parts)
        if remaining > 0:
            self.parts.append(text[:remaining])
        return len(text)

    def flush(self) -> None:
        return None

    def result(self) -> dict[str, object]:
        return {
            "text": "".join(self.parts),
            "original_chars": self.seen,
            "truncated": self.seen > self.limit,
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args(argv)
    captured_stdout = BoundedTextSink()
    captured_stderr = BoundedTextSink()
    try:
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            selector = load_selector(args.source.resolve())
            result = evaluate_public_selector(selector)
        result["candidate_stdout"] = captured_stdout.result()
        result["candidate_stderr"] = captured_stderr.result()
        rendered = json.dumps(result, ensure_ascii=True, sort_keys=True)
        sys.__stdout__.write(rendered)
        return 0
    except Exception as exc:
        result = {
            "status": "rejected",
            "failure_kind": "worker_exception",
            "error": f"{type(exc).__name__}: {exc}",
            "candidate_stdout": captured_stdout.result(),
            "candidate_stderr": captured_stderr.result(),
        }
        sys.__stdout__.write(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
