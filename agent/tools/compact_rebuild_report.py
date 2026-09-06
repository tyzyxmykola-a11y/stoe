from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def compact(value):
    if isinstance(value, dict):
        result = {}
        omitted = []
        for key, item in value.items():
            if key == "context" and isinstance(item, list):
                omitted.append({"field": key, "item_count": len(item)})
                continue
            result[key] = compact(item)
        if omitted:
            result.setdefault("omitted_large_fields", []).extend(omitted)
        return result
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Remove redundant Ollama token-id arrays from a rebuild report")
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    path = args.report.resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    output = compact(payload)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
