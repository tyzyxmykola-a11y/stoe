from __future__ import annotations

import asyncio
import os
import sys
import unittest
import uuid
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP_ROOT = PLUGIN_ROOT.parents[1] / "tmp" / "stoe_plugin_tests"


class MCPIntegrationTests(unittest.TestCase):
    def test_stdio_server_lists_and_calls_tools(self) -> None:
        async def scenario() -> None:
            db_path = TEST_TEMP_ROOT / f"mcp_{uuid.uuid4().hex}.sqlite3"
            environment = os.environ.copy()
            environment["STOE_MEMORY_DB"] = str(db_path)
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[str(PLUGIN_ROOT / "server.py")],
                cwd=str(PLUGIN_ROOT),
                env=environment,
            )
            try:
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        names = {tool.name for tool in listed.tools}
                        self.assertIn("stoe_field_status", names)
                        self.assertIn("stoe_set_observer_state", names)
                        self.assertIn("stoe_navigate", names)
                        self.assertIn("stoe_prepare_counterfactual_contexts", names)
                        result = await session.call_tool("stoe_field_status", {})
                        self.assertFalse(result.is_error)
                        self.assertEqual(result.structured_content["canonical_seed"]["core_ips"], 36)
                        self.assertTrue(result.structured_content["fold_unfold_lossless"])
            finally:
                for suffix in ("", "-wal", "-shm"):
                    Path(str(db_path) + suffix).unlink(missing_ok=True)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
