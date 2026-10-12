import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from ametller.cli import main
from ametller.storage import Storage
from test_cli import Catalog, product

MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
if MCP_AVAILABLE:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    from ametller.mcpserver import create_server


@unittest.skipUnless(MCP_AVAILABLE, "Instala el extra mcp para probar el protocolo")
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_tools_are_read_only_and_capabilities_are_offline(self):
        with tempfile.TemporaryDirectory() as directory, patch("ametller.cli.Client") as catalog:
            async with Client(create_server(directory), raise_exceptions=True) as client:
                tools = (await client.list_tools()).tools
                self.assertTrue(all(tool.annotations.read_only_hint for tool in tools))
                self.assertNotIn("set_remote_cart_item", {tool.name for tool in tools})
                result = await client.call_tool("capabilities", {})
                self.assertFalse(result.is_error)
                self.assertFalse(result.structured_content["mcp_writes_enabled"])
                self.assertTrue(result.structured_content["payments_blocked"])
                self.assertTrue(result.structured_content["orders_blocked"])
                self.assertTrue(result.structured_content["personal_coupons_supported"])
                self.assertFalse(result.structured_content["personal_coupon_activation_supported"])
                catalog.return_value.search.assert_not_called()
                self.assertEqual(list(Path(directory).iterdir()), [])

    async def test_write_rejected_before_account_access_without_confirmation(self):
        with tempfile.TemporaryDirectory() as directory, patch("ametller.mcpserver.execute") as execute:
            async with Client(create_server(directory, allow_writes=True)) as client:
                tools = (await client.list_tools()).tools
                writes = [tool for tool in tools if not tool.annotations.read_only_hint]
                self.assertTrue(writes)
                result = await client.call_tool("set_remote_cart_item", {
                    "product_id": "2351", "quantity": "2", "max_eur": "20"})
                self.assertTrue(result.is_error)
                execute.assert_not_called()
                self.assertEqual(list(Path(directory).iterdir()), [])

    async def test_local_write_and_budget_failure_preserve_scope_and_cart(self):
        with tempfile.TemporaryDirectory() as directory, patch("ametller.cli.Client", return_value=Catalog([product()])):
            async with Client(create_server(directory, allow_writes=True)) as client:
                arguments = {"product_id": "2351", "quantity": "2", "max_eur": "10", "confirmed": True}
                result = await client.call_tool("set_local_cart_item", arguments)
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["scope"], "local")
                self.assertEqual(Storage(directory).read("cart.json"), {"2351": "2"})
                failed = await client.call_tool("set_local_cart_item", {**arguments, "max_eur": "0"})
                self.assertTrue(failed.is_error)
                self.assertIn("Presupuesto superado", failed.content[0].text)
                self.assertEqual(Storage(directory).read("cart.json"), {"2351": "2"})

    async def test_query_is_literal_and_cannot_inject_account_or_other_flags(self):
        fake = Mock()
        fake.search.return_value = {"hits": [], "total": 0}
        with tempfile.TemporaryDirectory() as directory, patch("ametller.cli.Client", return_value=fake), patch("ametller.cli.AccountClient") as account:
            async with Client(create_server(directory)) as client:
                result = await client.call_tool("search_products", {"query": "--account --state-dir /tmp/other"})
                self.assertFalse(result.is_error)
                account.assert_not_called()
                self.assertEqual(fake.search.call_args.kwargs["query"], "--account --state-dir /tmp/other")
                bad = await client.call_tool("search_products", {"query": "yogur", "limit": 0})
                self.assertTrue(bad.is_error)
                self.assertEqual(fake.search.call_count, 1)

    async def test_account_read_does_not_fallback_and_status_omits_profile(self):
        fake = Mock()
        fake.whoami.return_value = {"connected": True, "session_type": "registered", "email": "user@example.test", "customer_id": "private"}
        with tempfile.TemporaryDirectory() as directory, patch("ametller.cli.AccountClient", return_value=fake):
            async with Client(create_server(directory)) as client:
                result = await client.call_tool("get_account_status", {})
                self.assertEqual(result.structured_content, {"connected": True, "session_type": "registered"})
        with tempfile.TemporaryDirectory() as directory, patch("ametller.cli.Client") as guest:
            async with Client(create_server(directory)) as client:
                result = await client.call_tool("get_product", {"product_id": "2351", "account": True})
                self.assertTrue(result.is_error)
                guest.assert_not_called()

    async def test_stdio_subprocess_negotiates_and_returns_json_without_state(self):
        with tempfile.TemporaryDirectory() as directory:
            params = StdioServerParameters(command=sys.executable,
                args=["-m", "ametller.mcpserver", "--state-dir", directory],
                cwd=Path(__file__).resolve().parents[1])
            async def connect():
                async with Client(params) as client:
                    result = await client.call_tool("capabilities", {})
                    self.assertFalse(result.is_error)
                    self.assertFalse(result.structured_content["mcp_writes_enabled"])
                    self.assertTrue((await client.list_tools()).tools)
            await asyncio.wait_for(connect(), timeout=20)
            self.assertEqual(list(Path(directory).iterdir()), [])


class CapabilityTests(unittest.TestCase):
    def test_cli_capabilities_is_json_and_offline(self):
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        with patch("ametller.cli.Client") as catalog, redirect_stdout(output):
            self.assertEqual(main(["capabilities", "--json"]), 0)
        self.assertTrue(json.loads(output.getvalue())["payments_blocked"])
        catalog.return_value.search.assert_not_called()
