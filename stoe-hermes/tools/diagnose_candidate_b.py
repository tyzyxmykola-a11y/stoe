from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


class MCPFacade:
    def __init__(self, store):
        self.store = store

    def call_mcp(self, server, tool, arguments, timeout=30):
        mapping = {
            "stoe_field_status": self.store.status,
            "stoe_list_recent": self.store.list_recent,
            "stoe_set_observer_state": self.store.set_observer_state,
            "stoe_navigate": self.store.navigate,
            "stoe_add_ip": self.store.add_ip,
            "stoe_add_relation": self.store.add_relation,
        }
        return {"ok": server == "stoe_memory", "structuredContent": mapping[tool](**arguments)}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-db", type=Path, required=True)
    parser.add_argument("--production-db", type=Path, required=True)
    args = parser.parse_args()
    from core import FieldStore
    from stoe_hermes.plugin import SToEHermesAdapter
    before = digest(args.production_db)
    store = FieldStore(args.test_db)
    store.initialize()
    adapter = SToEHermesAdapter(MCPFacade(store))
    adapter.on_session_start(session_id="candidate-b-diagnostic")
    adapter.conserve({"session_id": "candidate-b-diagnostic", "kind": "DiagnosticIP", "outcome": "supported", "content": "candidate B test-field communication"})
    adapter.on_session_end(session_id="candidate-b-diagnostic", completed=True, interrupted=False, model="none", platform="diagnostic")
    after = digest(args.production_db)
    if before != after:
        raise RuntimeError("production SToE field changed during B diagnostic")
    print(json.dumps({"passed": True, "test_field": store.status(), "production_field_sha256_unchanged": before}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
