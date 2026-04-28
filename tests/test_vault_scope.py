"""Tests for vault-scoped tool behavior.

When the read_file / glob / grep tools are constructed with a `vault_root`,
all paths must resolve under that root, escapes are rejected, and
soft-excluded paths drop out of search results.
"""

import os

import pytest

from kaori_agent.tools.read_file import ReadFileTool
from kaori_agent.tools.search import GlobTool, GrepTool


@pytest.fixture
def vault(tmp_path):
    """Build a tiny fake vault with a few files and an excluded subtree."""
    (tmp_path / "INDEX.md").write_text("# Index\n")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "alpha.md").write_text("alpha content with secret tag\n")
    (tmp_path / "notes" / "beta.md").write_text("beta content\n")

    excluded = tmp_path / "personal" / ".ex-spouse-archive"
    excluded.mkdir(parents=True)
    (excluded / "private.md").write_text("private content with secret tag\n")
    (excluded / "AGENTS.md").write_text("# Excluded subtree\n")

    return tmp_path


class TestReadFileVaultScope:
    @pytest.mark.asyncio
    async def test_relative_path_resolves_under_vault(self, vault):
        tool = ReadFileTool(vault_root=vault)
        result = await tool.execute(file_path="INDEX.md")
        assert not result.is_error
        assert "Index" in result.output

    @pytest.mark.asyncio
    async def test_nested_relative_path(self, vault):
        tool = ReadFileTool(vault_root=vault)
        result = await tool.execute(file_path="notes/alpha.md")
        assert not result.is_error
        assert "alpha content" in result.output

    @pytest.mark.asyncio
    async def test_escape_with_dotdot_rejected(self, vault):
        tool = ReadFileTool(vault_root=vault)
        result = await tool.execute(file_path="../escape.txt")
        assert result.is_error
        assert "escapes vault root" in result.output.lower()

    @pytest.mark.asyncio
    async def test_absolute_path_outside_vault_rejected(self, vault, tmp_path):
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("nope")
        tool = ReadFileTool(vault_root=vault)
        result = await tool.execute(file_path=str(outside))
        assert result.is_error
        assert "escapes vault root" in result.output.lower()

    @pytest.mark.asyncio
    async def test_symlink_escape_rejected(self, vault, tmp_path):
        outside = tmp_path.parent / "secret.txt"
        outside.write_text("secret content\n")
        os.symlink(outside, vault / "trap.md")
        tool = ReadFileTool(vault_root=vault)
        result = await tool.execute(file_path="trap.md")
        assert result.is_error
        assert "escapes vault root" in result.output.lower()

    @pytest.mark.asyncio
    async def test_absolute_path_inside_vault_works(self, vault):
        tool = ReadFileTool(vault_root=vault)
        result = await tool.execute(file_path=str(vault / "INDEX.md"))
        assert not result.is_error
        assert "Index" in result.output

    @pytest.mark.asyncio
    async def test_read_file_ignores_exclude_list(self, vault):
        # Soft-exclude only applies to glob/grep — read_file can still open it.
        tool = ReadFileTool(vault_root=vault)
        result = await tool.execute(
            file_path="personal/.ex-spouse-archive/AGENTS.md",
        )
        assert not result.is_error
        assert "Excluded subtree" in result.output

    @pytest.mark.asyncio
    async def test_legacy_mode_without_vault_root(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello\n")
        tool = ReadFileTool()
        result = await tool.execute(file_path=str(f))
        assert not result.is_error
        assert "hello" in result.output


class TestGlobVaultScope:
    @pytest.mark.asyncio
    async def test_default_path_is_vault_root(self, vault):
        tool = GlobTool(vault_root=vault)
        result = await tool.execute(pattern="**/*.md")
        assert "INDEX.md" in result.output
        assert "notes/alpha.md" in result.output

    @pytest.mark.asyncio
    async def test_returns_vault_relative_paths(self, vault):
        tool = GlobTool(vault_root=vault)
        result = await tool.execute(pattern="**/*.md")
        # No absolute paths leaking
        assert str(vault) not in result.output

    @pytest.mark.asyncio
    async def test_excluded_subtree_filtered(self, vault):
        tool = GlobTool(
            vault_root=vault,
            exclude_paths=["personal/.ex-spouse-archive"],
        )
        result = await tool.execute(pattern="**/*.md")
        assert "alpha.md" in result.output
        assert "private.md" not in result.output
        assert ".ex-spouse-archive" not in result.output

    @pytest.mark.asyncio
    async def test_path_arg_relative_to_vault(self, vault):
        tool = GlobTool(vault_root=vault)
        result = await tool.execute(pattern="*.md", path="notes")
        assert "alpha.md" in result.output
        assert "beta.md" in result.output

    @pytest.mark.asyncio
    async def test_escape_rejected(self, vault):
        tool = GlobTool(vault_root=vault)
        result = await tool.execute(pattern="*", path="../")
        assert result.is_error
        assert "escapes vault root" in result.output.lower()

    @pytest.mark.asyncio
    async def test_symlink_escapes_filtered_out(self, vault, tmp_path):
        outside = tmp_path.parent / "secret.txt"
        outside.write_text("secret\n")
        os.symlink(outside, vault / "trap.md")
        tool = GlobTool(vault_root=vault)
        result = await tool.execute(pattern="*.md")
        assert "trap.md" not in result.output
        # sanity check: real vault files still appear
        assert "INDEX.md" in result.output


class TestGrepVaultScope:
    @pytest.mark.asyncio
    async def test_default_searches_whole_vault(self, vault):
        tool = GrepTool(vault_root=vault)
        result = await tool.execute(pattern="alpha content")
        assert "notes/alpha.md" in result.output

    @pytest.mark.asyncio
    async def test_excluded_subtree_filtered(self, vault):
        # 'secret tag' appears in both notes/alpha.md and the excluded archive.
        # Without exclude_paths the dot-prefix rule already filters .ex-spouse-archive,
        # but with exclude_paths set this becomes explicit and survives any future
        # change to the dot-prefix filter.
        tool = GrepTool(
            vault_root=vault,
            exclude_paths=["personal/.ex-spouse-archive"],
        )
        result = await tool.execute(pattern="secret tag")
        assert "alpha.md" in result.output
        assert "private.md" not in result.output

    @pytest.mark.asyncio
    async def test_glob_filter_respects_vault(self, vault):
        (vault / "notes" / "gamma.txt").write_text("alpha content via txt\n")
        tool = GrepTool(vault_root=vault)
        # The glob filter is non-recursive by default — same semantics as the
        # legacy CWD-rooted GrepTool. Use **/*.md to recurse.
        result = await tool.execute(pattern="alpha content", glob="**/*.md")
        assert "alpha.md" in result.output
        assert "gamma.txt" not in result.output

    @pytest.mark.asyncio
    async def test_escape_rejected(self, vault):
        tool = GrepTool(vault_root=vault)
        result = await tool.execute(pattern="x", path="../")
        assert result.is_error
        assert "escapes vault root" in result.output.lower()

    @pytest.mark.asyncio
    async def test_symlink_contents_not_searched(self, vault, tmp_path):
        outside = tmp_path.parent / "secret.txt"
        outside.write_text("uniquephrase42\n")
        os.symlink(outside, vault / "trap.md")
        tool = GrepTool(vault_root=vault)
        result = await tool.execute(pattern="uniquephrase42")
        assert "trap.md" not in result.output
        assert "uniquephrase42" not in result.output
