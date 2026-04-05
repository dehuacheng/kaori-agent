"""Tests for ToolRegistry."""

import pytest

from kaori_agent.tools.base import BaseTool, ToolResult
from kaori_agent.tool_registry import ToolRegistry


class DummyTool(BaseTool):
    name = "dummy"
    description = "A dummy tool for testing."
    input_schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }

    async def execute(self, x: int = 0) -> ToolResult:
        return ToolResult(output=str(x * 2))


class AnotherTool(BaseTool):
    name = "another"
    description = "Another test tool."
    input_schema = {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        return ToolResult(output="ok")


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = DummyTool()
        reg.register(tool)
        assert reg.get("dummy") is tool

    def test_get_nonexistent(self):
        reg = ToolRegistry()
        assert reg.get("nope") is None

    def test_get_all(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        reg.register(AnotherTool())
        assert len(reg.get_all()) == 2

    def test_names(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        reg.register(AnotherTool())
        assert set(reg.names()) == {"dummy", "another"}

    def test_overwrite(self):
        reg = ToolRegistry()
        t1 = DummyTool()
        t2 = DummyTool()
        reg.register(t1)
        reg.register(t2)
        assert reg.get("dummy") is t2
        assert len(reg.get_all()) == 1
