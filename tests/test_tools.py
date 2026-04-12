"""Tests for concrete tool implementations."""

from unittest.mock import patch

import pytest

from kaori_agent.tools.read_file import ReadFileTool
from kaori_agent.tools.search import GlobTool, GrepTool
from kaori_agent.tools.web_search import WebSearchTool


class TestReadFileTool:
    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")

        tool = ReadFileTool()
        result = await tool.execute(file_path=str(f))
        assert not result.is_error
        assert "1\tline1" in result.output
        assert "3\tline3" in result.output

    @pytest.mark.asyncio
    async def test_read_with_offset_limit(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("\n".join(f"line{i}" for i in range(10)))

        tool = ReadFileTool()
        result = await tool.execute(file_path=str(f), offset=2, limit=3)
        assert not result.is_error
        assert "3\tline2" in result.output
        assert "5\tline4" in result.output
        assert "line0" not in result.output

    @pytest.mark.asyncio
    async def test_read_nonexistent(self):
        tool = ReadFileTool()
        result = await tool.execute(file_path="/nonexistent/file.txt")
        assert result.is_error
        assert "not found" in result.output.lower()

    @pytest.mark.asyncio
    async def test_read_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")

        tool = ReadFileTool()
        result = await tool.execute(file_path=str(f))
        assert not result.is_error
        assert "empty" in result.output.lower()


class TestGlobTool:
    @pytest.mark.asyncio
    async def test_find_python_files(self, tmp_path):
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.py").write_text("pass")
        (tmp_path / "c.txt").write_text("text")

        tool = GlobTool()
        result = await tool.execute(pattern="*.py", path=str(tmp_path))
        assert not result.is_error
        assert "a.py" in result.output
        assert "b.py" in result.output
        assert "c.txt" not in result.output

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        tool = GlobTool()
        result = await tool.execute(pattern="*.xyz", path=str(tmp_path))
        assert "no files" in result.output.lower()

    @pytest.mark.asyncio
    async def test_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.py").write_text("pass")

        tool = GlobTool()
        result = await tool.execute(pattern="**/*.py", path=str(tmp_path))
        assert "deep.py" in result.output


class TestGrepTool:
    @pytest.mark.asyncio
    async def test_find_pattern(self, tmp_path):
        (tmp_path / "code.py").write_text("def hello():\n    return 42\n")

        tool = GrepTool()
        result = await tool.execute(pattern="def hello", path=str(tmp_path))
        assert not result.is_error
        assert "code.py:1" in result.output

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        (tmp_path / "code.py").write_text("x = 1\n")

        tool = GrepTool()
        result = await tool.execute(pattern="nonexistent", path=str(tmp_path))
        assert "no matches" in result.output.lower()

    @pytest.mark.asyncio
    async def test_glob_filter(self, tmp_path):
        (tmp_path / "a.py").write_text("target = True\n")
        (tmp_path / "b.txt").write_text("target = True\n")

        tool = GrepTool()
        result = await tool.execute(pattern="target", path=str(tmp_path), glob="*.py")
        assert "a.py" in result.output
        assert "b.txt" not in result.output

    @pytest.mark.asyncio
    async def test_invalid_regex(self, tmp_path):
        tool = GrepTool()
        result = await tool.execute(pattern="[invalid", path=str(tmp_path))
        assert result.is_error
        assert "regex" in result.output.lower()


class TestWebSearchTool:
    @pytest.mark.asyncio
    async def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        tool = WebSearchTool()
        result = await tool.execute(query="anything")
        assert result.is_error
        assert "TAVILY_API_KEY" in result.output

    @pytest.mark.asyncio
    async def test_formats_results(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

        fake_response = {
            "answer": "Leo Messi is an Argentine footballer.",
            "results": [
                {"title": "Lionel Messi - Wikipedia", "url": "https://en.wikipedia.org/wiki/Lionel_Messi", "content": "Messi is a forward..."},
                {"title": "Official Site", "url": "https://messi.com", "content": "Home of Leo."},
            ],
        }

        class FakeClient:
            def __init__(self, api_key): pass
            def search(self, **kwargs): return fake_response

        with patch("tavily.TavilyClient", FakeClient):
            tool = WebSearchTool()
            result = await tool.execute(query="Who is Messi?", max_results=2)

        assert not result.is_error
        assert "Leo Messi is an Argentine footballer" in result.output
        assert "[1] Lionel Messi - Wikipedia" in result.output
        assert "https://messi.com" in result.output

    @pytest.mark.asyncio
    async def test_clamps_max_results(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        captured = {}

        class FakeClient:
            def __init__(self, api_key): pass
            def search(self, **kwargs):
                captured.update(kwargs)
                return {"results": []}

        with patch("tavily.TavilyClient", FakeClient):
            tool = WebSearchTool()
            await tool.execute(query="x", max_results=50)
        assert captured["max_results"] == 10
