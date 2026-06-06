"""Tests for the MongoDB MCP toolset wiring."""

from asili_agents.agents.mcp_tools import make_mongodb_mcp_toolset, resolve_use_mcp
from asili_agents.config import Settings


class TestResolveUseMcp:
    def test_explicit_true_wins(self):
        assert resolve_use_mcp(True, Settings(use_mcp=False)) is True

    def test_explicit_false_wins(self):
        assert resolve_use_mcp(False, Settings(use_mcp=True)) is False

    def test_falls_back_to_settings(self):
        assert resolve_use_mcp(None, Settings(use_mcp=True)) is True
        assert resolve_use_mcp(None, Settings(use_mcp=False)) is False


class TestMakeToolset:
    def test_none_without_uri(self):
        """No MongoDB configured -> no MCP toolset (callers fall back)."""
        assert make_mongodb_mcp_toolset(Settings(mongodb_uri=None)) is None

    def test_builds_with_uri(self):
        """A connection string yields a real McpToolset (lazy; not connected)."""
        toolset = make_mongodb_mcp_toolset(
            Settings(mongodb_uri="mongodb://localhost:27017/asili", use_mcp=True)
        )
        assert toolset is not None
