"""Memory tools — let the agent persist/recall cross-session facts."""

from kaori_agent.tools.base import BaseTool, ToolResult


class SaveMemoryTool(BaseTool):
    """Persist a fact about the user for future conversations."""

    name = "save_memory"
    description = (
        "Save a key-value fact about the user that persists across conversations. "
        "Use this when the user shares a preference, personal detail, or important "
        "fact that should be remembered in future sessions."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Short identifier (e.g. 'preferred_language', 'name', 'timezone')",
            },
            "value": {
                "type": "string",
                "description": "The fact to remember",
            },
            "category": {
                "type": "string",
                "enum": ["general", "preference", "fact"],
                "description": "Category of the memory entry (default: general)",
            },
        },
        "required": ["key", "value"],
    }

    def __init__(self, session_store=None, session_id: str | None = None):
        self._store = session_store
        self._session_id = session_id

    async def execute(self, **kwargs) -> ToolResult:
        key = kwargs["key"]
        value = kwargs["value"]
        category = kwargs.get("category", "general")

        if self._store is None:
            return ToolResult(
                output="Memory not available (no session store configured).",
                is_error=True,
            )

        await self._store.set_memory(key, value, category, source=self._session_id)
        return ToolResult(output=f"Saved: {key} = {value}")


class GetMemoryTool(BaseTool):
    """Recall previously saved facts about the user."""

    name = "get_memory"
    description = (
        "Retrieve previously saved facts about the user. "
        "Call with a specific key to get one fact, or without arguments to list all."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Specific key to look up (optional — omit to list all)",
            },
        },
    }

    def __init__(self, session_store=None):
        self._store = session_store

    async def execute(self, **kwargs) -> ToolResult:
        if self._store is None:
            return ToolResult(
                output="Memory not available (no session store configured).",
                is_error=True,
            )

        key = kwargs.get("key")
        if key:
            entry = await self._store.get_memory(key)
            if entry is None:
                return ToolResult(output=f"No memory found for key: {key}")
            return ToolResult(output=f"{entry['key']}: {entry['value']} [{entry['category']}]")

        entries = await self._store.list_memory()
        if not entries:
            return ToolResult(output="No memories saved yet.")
        lines = [f"- {e['key']}: {e['value']} [{e['category']}]" for e in entries]
        return ToolResult(output="\n".join(lines))
