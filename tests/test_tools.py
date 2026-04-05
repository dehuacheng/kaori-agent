"""Tests for concrete tool implementations."""

import pytest

from kaori_agent.tools.read_file import ReadFileTool
from kaori_agent.tools.search import GlobTool, GrepTool


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
