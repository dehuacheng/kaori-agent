"""ReadFile tool: read file contents with optional line range."""

from pathlib import Path

from kaori_agent.tools.base import BaseTool, ToolResult


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the contents of a file. Optionally specify a line range with offset and limit."
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read.",
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

    async def execute(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ToolResult:
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

        # Format with line numbers
        numbered = []
        for i, line in enumerate(selected, start=offset + 1):
            numbered.append(f"{i}\t{line}")

        output = "\n".join(numbered)
        if not output:
            output = "(empty file)" if not lines else "(no lines in requested range)"

        return ToolResult(output=output)
