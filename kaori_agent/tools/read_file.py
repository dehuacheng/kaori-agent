"""ReadFile tool: read file contents with optional line range.

When constructed with a `vault_root`, all paths are resolved relative to
that root and any path that escapes it (after symlink resolution) is rejected.
This is how the agent reads from the user's Obsidian vault read-only.
"""

from pathlib import Path

from kaori_agent.tools.base import BaseTool, ToolResult


class ReadFileTool(BaseTool):
    name = "read_file"

    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file. When vault is enabled, this is relative to the vault root.",
            },
            "offset": {
                "type": "integer",
                "description": "Starting line number (0-based). Default: 0.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Default: 2000.",
            },
        },
        "required": ["file_path"],
    }

    def __init__(self, vault_root: Path | None = None) -> None:
        self.vault_root = vault_root.resolve() if vault_root else None
        if self.vault_root:
            self.description = (
                f"Read a file from the Obsidian vault at {self.vault_root}. "
                "file_path is relative to the vault root (e.g. 'INDEX.md', "
                "'readings/papers/foo/summary.md'). Optionally specify a line "
                "range with offset and limit."
            )
        else:
            self.description = (
                "Read the contents of a file. Optionally specify a line range "
                "with offset and limit."
            )

    async def execute(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ToolResult:
        if self.vault_root:
            raw = Path(file_path).expanduser()
            candidate = raw if raw.is_absolute() else (self.vault_root / raw)
            try:
                p = candidate.resolve()
            except OSError as e:
                return ToolResult(output=f"Error resolving path: {e}", is_error=True)
            if not p.is_relative_to(self.vault_root):
                return ToolResult(
                    output=f"Path escapes vault root: {file_path}",
                    is_error=True,
                )
        else:
            p = Path(file_path).expanduser()

        if not p.exists():
            return ToolResult(output=f"File not found: {file_path}", is_error=True)
        if not p.is_file():
            return ToolResult(output=f"Not a file: {file_path}", is_error=True)

        try:
            text = p.read_text(errors="replace")
        except Exception as e:
            return ToolResult(output=f"Error reading file: {e}", is_error=True)

        lines = text.splitlines()
        selected = lines[offset : offset + limit]

        numbered = []
        for i, line in enumerate(selected, start=offset + 1):
            numbered.append(f"{i}\t{line}")

        output = "\n".join(numbered)
        if not output:
            output = "(empty file)" if not lines else "(no lines in requested range)"

        return ToolResult(output=output)
