"""Search tools: GlobTool (file pattern matching) and GrepTool (content search)."""

import fnmatch
import re
from pathlib import Path

from kaori_agent.tools.base import BaseTool, ToolResult

_MAX_RESULTS = 100


class GlobTool(BaseTool):
    name = "glob"
    description = "Find files matching a glob pattern. Returns file paths sorted by modification time."
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Default: current directory.",
            },
        },
        "required": ["pattern"],
    }

    async def execute(self, pattern: str, path: str = ".") -> ToolResult:
        base = Path(path).expanduser().resolve()
        if not base.exists():
            return ToolResult(output=f"Directory not found: {path}", is_error=True)

        try:
            matches = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception as e:
            return ToolResult(output=f"Glob error: {e}", is_error=True)

        # Filter out hidden/venv/git dirs
        filtered = [
            m for m in matches
            if m.is_file() and not _is_ignored(m, base)
        ]

        if not filtered:
            return ToolResult(output="No files matched.")

        lines = [str(m.relative_to(base)) for m in filtered[:_MAX_RESULTS]]
        output = "\n".join(lines)
        if len(filtered) > _MAX_RESULTS:
            output += f"\n\n... and {len(filtered) - _MAX_RESULTS} more files"
        return ToolResult(output=output)


class GrepTool(BaseTool):
    name = "grep"
    description = "Search file contents for a regex pattern. Returns matching lines with file paths and line numbers."
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in. Default: current directory.",
            },
            "glob": {
                "type": "string",
                "description": "File glob filter (e.g. '*.py'). Only search matching files.",
            },
        },
        "required": ["pattern"],
    }

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        **kwargs,
    ) -> ToolResult:
        base = Path(path).expanduser().resolve()
        if not base.exists():
            return ToolResult(output=f"Path not found: {path}", is_error=True)

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(output=f"Invalid regex: {e}", is_error=True)

        # Collect files to search
        if base.is_file():
            files = [base]
        else:
            file_pattern = glob or "**/*"
            files = [
                f for f in sorted(base.glob(file_pattern))
                if f.is_file() and not _is_ignored(f, base)
            ]

        matches: list[str] = []
        for filepath in files:
            try:
                text = filepath.read_text(errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = filepath.relative_to(base) if base.is_dir() else filepath.name
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
