"""Memory and session tools — persist/recall facts and access past conversations."""

import json

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

    def __init__(self, session_store=None, session_id: str | None = None, on_save=None):
        """
        Args:
            on_save: Optional callback (key, value, category) -> None, invoked after a
                successful save. The CLI uses this to print a dim indicator so the user
                sees what was captured without the agent announcing it in chat.
        """
        self._store = session_store
        self._session_id = session_id
        self._on_save = on_save

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
        if self._on_save is not None:
            try:
                self._on_save(key, value, category)
            except Exception:
                pass
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


class ListSessionsTool(BaseTool):
    """List past conversation sessions."""

    name = "list_sessions"
    description = (
        "List past conversation sessions. Returns session IDs (8-char prefix), "
        "titles, message counts, and dates. Use this to find a session before "
        "reading it with read_session."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max number of sessions to return (default: 20)",
            },
            "status": {
                "type": "string",
                "enum": ["active", "archived"],
                "description": "Filter by status (default: active)",
            },
        },
    }

    def __init__(self, session_store=None):
        self._store = session_store

    async def execute(self, **kwargs) -> ToolResult:
        if self._store is None:
            return ToolResult(
                output="Sessions not available (no session store configured).",
                is_error=True,
            )

        limit = kwargs.get("limit", 20)
        status = kwargs.get("status", "active")
        sessions = await self._store.list_sessions(status=status, limit=limit)
        if not sessions:
            return ToolResult(output="No sessions found.")

        lines = []
        for s in sessions:
            title = s["title"] or "(untitled)"
            count = s["message_count"]
            date = s["updated_at"][:16] if s["updated_at"] else "?"
            sid = s["id"][:8]
            lines.append(f"- {sid}  {title}  ({count} msgs, {date})")
        return ToolResult(output="\n".join(lines))


class ReadSessionTool(BaseTool):
    """Read messages from a past conversation session."""

    name = "read_session"
    description = (
        "Read messages from a past conversation session by ID prefix. "
        "Returns the conversation transcript. Use list_sessions first "
        "to find the session ID."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "session_id_prefix": {
                "type": "string",
                "description": "First 8+ characters of the session ID",
            },
            "limit": {
                "type": "integer",
                "description": "Max messages to return (default: 50, from most recent)",
            },
        },
        "required": ["session_id_prefix"],
    }

    def __init__(self, session_store=None):
        self._store = session_store

    async def execute(self, **kwargs) -> ToolResult:
        if self._store is None:
            return ToolResult(
                output="Sessions not available (no session store configured).",
                is_error=True,
            )

        prefix = kwargs["session_id_prefix"]
        limit = kwargs.get("limit", 50)

        # Find matching session
        sessions = await self._store.list_sessions(limit=100)
        matches = [s for s in sessions if s["id"].startswith(prefix)]

        if not matches:
            return ToolResult(output=f"No session found starting with '{prefix}'.", is_error=True)
        if len(matches) > 1:
            ids = ", ".join(s["id"][:8] for s in matches[:5])
            return ToolResult(
                output=f"Ambiguous prefix '{prefix}' — matches {len(matches)} sessions: {ids}",
                is_error=True,
            )

        target = matches[0]
        session = await self._store.load_session(target["id"])

        title = session.title or "(untitled)"
        header = f"Session: {session.id[:8]} — {title} ({len(session.messages)} messages)"

        # Take the last `limit` messages
        msgs = session.messages[-limit:]
        lines = [header, "---"]

        for msg in msgs:
            role = msg.get("role", "?")
            content = msg.get("content", "")

            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                # Content blocks — extract text
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            text_parts.append(f"[tool_use: {block.get('name', '?')}]")
                        elif block.get("type") == "tool_result":
                            out = block.get("content", "")
                            if len(out) > 200:
                                out = out[:200] + "..."
                            text_parts.append(f"[tool_result: {out}]")
                text = "\n".join(text_parts)
            else:
                text = str(content)

            # Truncate very long messages for readability
            if len(text) > 500:
                text = text[:500] + "..."

            lines.append(f"**{role}**: {text}")

        return ToolResult(output="\n".join(lines))
