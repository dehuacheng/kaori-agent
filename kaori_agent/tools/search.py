"""Search tools: GlobTool (file pattern matching) and GrepTool (content search).

When constructed with a `vault_root`, both tools default their search base to
that root, resolve the `path` arg under it, and reject paths that escape.
`exclude_paths` are vault-relative prefixes (e.g. 'personal/.ex-spouse-archive')
filtered out of results — soft exclusion, no error.
"""

import re
from pathlib import Path

from kaori_agent.tools.base import BaseTool, ToolResult

_MAX_RESULTS = 100


class GlobTool(BaseTool):
    name = "glob"

    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g. '**/*.md', 'readings/**/summary.md').",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. When vault is enabled, relative to vault root; default is the vault root itself.",
            },
        },
        "required": ["pattern"],
    }

    def __init__(
        self,
        vault_root: Path | None = None,
        exclude_paths: list[str] | None = None,
    ) -> None:
        self.vault_root = vault_root.resolve() if vault_root else None
        self.exclude_paths = list(exclude_paths or [])
        if self.vault_root:
            excluded = (
                f" Excluded by default: {', '.join(self.exclude_paths)}."
                if self.exclude_paths
                else ""
            )
            self.description = (
                f"Find files in the Obsidian vault at {self.vault_root} "
                f"matching a glob pattern. Returns vault-relative paths sorted "
                f"by modification time.{excluded}"
            )
        else:
            self.description = (
                "Find files matching a glob pattern. Returns file paths "
                "sorted by modification time."
            )

    async def execute(self, pattern: str, path: str | None = None) -> ToolResult:
        base, err = _resolve_base(path, self.vault_root)
        if err:
            return err

        try:
            matches = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception as e:
            return ToolResult(output=f"Glob error: {e}", is_error=True)

        filtered = [
            m for m in matches
            if m.is_file()
            and not _is_ignored(m, base)
            and not _is_excluded(m, self.vault_root, self.exclude_paths)
            and not _is_symlink_escape(m, self.vault_root)
        ]

        if not filtered:
            return ToolResult(output="No files matched.")

        rel_base = self.vault_root if self.vault_root else base
        lines = [str(m.relative_to(rel_base)) for m in filtered[:_MAX_RESULTS]]
        output = "\n".join(lines)
        if len(filtered) > _MAX_RESULTS:
            output += f"\n\n... and {len(filtered) - _MAX_RESULTS} more files"
        return ToolResult(output=output)


class GrepTool(BaseTool):
    name = "grep"

    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in. When vault is enabled, relative to vault root; default is the vault root itself.",
            },
            "glob": {
                "type": "string",
                "description": "File glob filter (e.g. '*.md'). Only search matching files.",
            },
        },
        "required": ["pattern"],
    }

    def __init__(
        self,
        vault_root: Path | None = None,
        exclude_paths: list[str] | None = None,
    ) -> None:
        self.vault_root = vault_root.resolve() if vault_root else None
        self.exclude_paths = list(exclude_paths or [])
        if self.vault_root:
            excluded = (
                f" Excluded by default: {', '.join(self.exclude_paths)}."
                if self.exclude_paths
                else ""
            )
            self.description = (
                f"Search file contents in the Obsidian vault at {self.vault_root} "
                f"for a regex pattern. Returns matching lines with vault-relative "
                f"paths and line numbers.{excluded}"
            )
        else:
            self.description = (
                "Search file contents for a regex pattern. Returns matching "
                "lines with file paths and line numbers."
            )

    async def execute(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        **kwargs,
    ) -> ToolResult:
        base, err = _resolve_base(path, self.vault_root)
        if err:
            return err

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(output=f"Invalid regex: {e}", is_error=True)

        if base.is_file():
            files = [base]
        else:
            file_pattern = glob or "**/*"
            files = [
                f for f in sorted(base.glob(file_pattern))
                if f.is_file()
                and not _is_ignored(f, base)
                and not _is_excluded(f, self.vault_root, self.exclude_paths)
                and not _is_symlink_escape(f, self.vault_root)
            ]

        rel_base = self.vault_root if self.vault_root else base

        matches: list[str] = []
        for filepath in files:
            try:
                text = filepath.read_text(errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    if base.is_file():
                        rel = filepath.name
                    else:
                        rel = filepath.relative_to(rel_base)
                    matches.append(f"{rel}:{i}: {line}")
                    if len(matches) >= _MAX_RESULTS:
                        break
            if len(matches) >= _MAX_RESULTS:
                break

        if not matches:
            return ToolResult(output="No matches found.")

        output = "\n".join(matches)
        if len(matches) >= _MAX_RESULTS:
            output += f"\n\n(truncated at {_MAX_RESULTS} matches)"
        return ToolResult(output=output)


def _resolve_base(
    path: str | None, vault_root: Path | None
) -> tuple[Path, ToolResult | None]:
    """Resolve the search base path.

    With vault_root: default is the vault root; user-supplied path is interpreted
    relative to the vault root and rejected if it escapes after resolution.

    Without vault_root: legacy CWD-rooted behavior.
    """
    if vault_root:
        if path is None or path == "":
            return vault_root, None
        raw = Path(path).expanduser()
        candidate = raw if raw.is_absolute() else (vault_root / raw)
        try:
            resolved = candidate.resolve()
        except OSError as e:
            return vault_root, ToolResult(
                output=f"Error resolving path: {e}", is_error=True
            )
        if not resolved.is_relative_to(vault_root):
            return vault_root, ToolResult(
                output=f"Path escapes vault root: {path}", is_error=True
            )
        if not resolved.exists():
            return vault_root, ToolResult(
                output=f"Path not found: {path}", is_error=True
            )
        return resolved, None

    base = Path(path or ".").expanduser().resolve()
    if not base.exists():
        return base, ToolResult(output=f"Path not found: {path}", is_error=True)
    return base, None


def _is_ignored(path: Path, base: Path) -> bool:
    """Skip common non-content directories."""
    try:
        rel = path.relative_to(base)
    except ValueError:
        return False
    parts = rel.parts
    return any(
        p.startswith(".") or p in ("__pycache__", "node_modules", ".venv", "venv", ".git")
        for p in parts
    )


def _is_excluded(
    path: Path, vault_root: Path | None, exclude_paths: list[str]
) -> bool:
    """True if path falls under any vault-relative excluded prefix."""
    if not vault_root or not exclude_paths:
        return False
    try:
        rel = path.relative_to(vault_root)
    except ValueError:
        return False
    rel_str = str(rel)
    for prefix in exclude_paths:
        norm = prefix.strip("/")
        if rel_str == norm or rel_str.startswith(norm + "/"):
            return True
    return False


def _is_symlink_escape(path: Path, vault_root: Path | None) -> bool:
    """True if `path` resolves outside vault_root (e.g. a symlink target).

    GlobTool/GrepTool enumerate files via base.glob(...), which returns
    unresolved paths. ReadFileTool resolves before checking, but these tools
    must do the same before reading or listing — otherwise a symlink inside
    the vault pointing outside (vault/innocent.md → /etc/passwd) leaks.
    """
    if not vault_root:
        return False
    try:
        return not path.resolve().is_relative_to(vault_root)
    except OSError:
        return True  # broken symlink or unreadable — drop it
