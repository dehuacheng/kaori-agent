"""Session persistence — store conversations in SQLite (co-located with kaori.db).

Two main classes:
  SessionStore — manages DB connection, table creation, session CRUD
  Session      — wraps an active conversation with auto-persistence
"""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

# ---------------------------------------------------------------------------
# Schema — agent tables created via CREATE TABLE IF NOT EXISTS so that
# kaori-agent can self-bootstrap even before kaori backend adopts them.
# ---------------------------------------------------------------------------

_AGENT_SCHEMA = """\
CREATE TABLE IF NOT EXISTS agent_sessions (
    id          TEXT    PRIMARY KEY,
    title       TEXT,
    status      TEXT    NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','archived','deleted')),
    backend     TEXT,
    model       TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    token_count_approx INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now')),
    updated_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    role        TEXT    NOT NULL CHECK(role IN ('user','assistant','tool_result','summary')),
    content     TEXT    NOT NULL,
    token_count_approx INTEGER DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT    NOT NULL UNIQUE,
    value       TEXT    NOT NULL,
    category    TEXT    DEFAULT 'general',
    source      TEXT,
    created_at  TEXT    DEFAULT (datetime('now')),
    updated_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_compactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    summary_text    TEXT    NOT NULL,
    messages_summarized INTEGER NOT NULL,
    up_to_seq       INTEGER NOT NULL,
    llm_backend     TEXT,
    model           TEXT,
    raw_response    TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_prompts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    prompt_text TEXT    NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now')),
    updated_at  TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_session
    ON agent_messages(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status
    ON agent_sessions(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_compactions_session
    ON agent_compactions(session_id, is_active);
"""

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Approximate context window sizes per model (tokens).
_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
    "moonshot-v1-128k": 128_000,
    "moonshot-v1-32k": 32_000,
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-6": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "gpt-4o": 128_000,
}
_DEFAULT_CONTEXT_WINDOW = 64_000


def estimate_tokens(text: str) -> int:
    """Rough token count: ~4 chars/token for ASCII, ~2 for CJK."""
    if not text:
        return 0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u30ff')
    ascii_chars = len(text) - cjk
    return (ascii_chars // 4) + (cjk // 2)


def _estimate_message_tokens(content: str) -> int:
    """Estimate tokens from a JSON-encoded message content string."""
    return estimate_tokens(content)


def get_context_window(model: str) -> int:
    """Look up context window size for a model."""
    return _CONTEXT_WINDOWS.get(model, _DEFAULT_CONTEXT_WINDOW)


# ---------------------------------------------------------------------------
# SessionStore — DB connection + CRUD
# ---------------------------------------------------------------------------

class SessionStore:
    """Manages session persistence in SQLite."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def _get_db(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(str(self.db_path))
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        return db

    async def initialize(self) -> None:
        """Ensure agent tables exist. Safe to call on every startup."""
        db = await self._get_db()
        try:
            await db.executescript(_AGENT_SCHEMA)
            await db.commit()
        finally:
            await db.close()

    # --- Session CRUD ---

    async def create_session(self, backend: str, model: str) -> "Session":
        """Create a new session and return a Session wrapper."""
        session_id = str(uuid.uuid4())
        db = await self._get_db()
        try:
            await db.execute(
                "INSERT INTO agent_sessions (id, backend, model) VALUES (?, ?, ?)",
                (session_id, backend, model),
            )
            await db.commit()
        finally:
            await db.close()
        return Session(
            store=self,
            id=session_id,
            title=None,
            backend=backend,
            model=model,
            messages=[],
            _next_seq=0,
        )

    async def load_session(self, session_id: str) -> "Session":
        """Load a session and all its messages from DB."""
        db = await self._get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM agent_sessions WHERE id = ?", (session_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Session not found: {session_id}")
            session_data = dict(row)

            # Load messages
            cursor = await db.execute(
                "SELECT * FROM agent_messages WHERE session_id = ? ORDER BY seq",
                (session_id,),
            )
            msg_rows = [dict(r) for r in await cursor.fetchall()]

            # Load active compaction
            cursor = await db.execute(
                "SELECT * FROM agent_compactions "
                "WHERE session_id = ? AND is_active = 1 "
                "ORDER BY version DESC LIMIT 1",
                (session_id,),
            )
            compaction_row = await cursor.fetchone()
            compaction = dict(compaction_row) if compaction_row else None
        finally:
            await db.close()

        # Reconstruct messages list (backend-specific dicts)
        messages: list = []
        for msg in msg_rows:
            messages.append(json.loads(msg["content"]))

        next_seq = msg_rows[-1]["seq"] + 1 if msg_rows else 0

        session = Session(
            store=self,
            id=session_data["id"],
            title=session_data["title"],
            backend=session_data["backend"],
            model=session_data["model"],
            messages=messages,
            _next_seq=next_seq,
            _compaction=compaction,
        )
        return session

    async def list_sessions(
        self, status: str = "active", limit: int = 20
    ) -> list[dict]:
        """List sessions by status, most recent first."""
        db = await self._get_db()
        try:
            cursor = await db.execute(
                "SELECT id, title, status, backend, model, message_count, "
                "token_count_approx, created_at, updated_at "
                "FROM agent_sessions WHERE status = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]
        finally:
            await db.close()

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and its messages (CASCADE)."""
        db = await self._get_db()
        try:
            cursor = await db.execute(
                "DELETE FROM agent_sessions WHERE id = ?", (session_id,)
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()

    # --- Memory CRUD ---

    async def get_memory(self, key: str) -> dict | None:
        db = await self._get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM agent_memory WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def list_memory(self, category: str | None = None) -> list[dict]:
        db = await self._get_db()
        try:
            if category:
                cursor = await db.execute(
                    "SELECT * FROM agent_memory WHERE category = ? ORDER BY key",
                    (category,),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM agent_memory ORDER BY key"
                )
            return [dict(r) for r in await cursor.fetchall()]
        finally:
            await db.close()

    async def set_memory(
        self, key: str, value: str, category: str = "general", source: str | None = None
    ) -> None:
        db = await self._get_db()
        try:
            await db.execute(
                "INSERT INTO agent_memory (key, value, category, source) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, category=excluded.category, "
                "source=excluded.source, updated_at=datetime('now')",
                (key, value, category, source),
            )
            await db.commit()
        finally:
            await db.close()

    async def delete_memory(self, key: str) -> bool:
        db = await self._get_db()
        try:
            cursor = await db.execute(
                "DELETE FROM agent_memory WHERE key = ?", (key,)
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()


# ---------------------------------------------------------------------------
# Session — active conversation wrapper
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """Wraps an active conversation with auto-persistence.

    The `messages` list is the same list that engine.py mutates.
    After each turn, call `append_message()` to persist new messages.
    """
    store: SessionStore
    id: str
    title: str | None
    backend: str
    model: str
    messages: list  # backend-specific message dicts (what engine.py uses)
    _next_seq: int = 0
    _compaction: dict | None = field(default=None, repr=False)
    _total_tokens: int = 0

    async def append_message(self, role: str, content_dict: dict) -> None:
        """Persist a single message to DB. Call after engine appends to messages."""
        content_json = json.dumps(content_dict, ensure_ascii=False)
        tokens = _estimate_message_tokens(content_json)
        self._total_tokens += tokens

        db = await self.store._get_db()
        try:
            await db.execute(
                "INSERT INTO agent_messages (session_id, seq, role, content, token_count_approx) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.id, self._next_seq, role, content_json, tokens),
            )
            self._next_seq += 1
            await db.execute(
                "UPDATE agent_sessions SET message_count = ?, token_count_approx = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (self._next_seq, self._total_tokens, self.id),
            )
            await db.commit()
        finally:
            await db.close()

    async def set_title(self, title: str) -> None:
        """Update session title."""
        self.title = title
        db = await self.store._get_db()
        try:
            await db.execute(
                "UPDATE agent_sessions SET title = ?, updated_at = datetime('now') WHERE id = ?",
                (title, self.id),
            )
            await db.commit()
        finally:
            await db.close()

    async def auto_title(self) -> None:
        """Set title from first user message if no title yet."""
        if self.title or not self.messages:
            return
        first = self.messages[0]
        text = ""
        if isinstance(first, dict):
            content = first.get("content", "")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        break
        if text:
            title = text[:60].strip()
            if len(text) > 60:
                title += "..."
            await self.set_title(title)

    def get_effective_messages(self) -> list:
        """Return messages for LLM: compaction summary + recent messages.

        If compaction exists, returns the summary as a user message followed
        by only messages with seq > compaction.up_to_seq.
        Without compaction, returns all messages.
        """
        if not self._compaction:
            return self.messages

        up_to_seq = self._compaction["up_to_seq"]
        # Count how many stored messages are before/at compaction point
        # Messages in self.messages correspond to seq 0..N-1
        cut = up_to_seq + 1
        if cut >= len(self.messages):
            # All messages compacted — just summary
            return [{"role": "user", "content": self._compaction["summary_text"]}]

        summary_msg = {"role": "user", "content": self._compaction["summary_text"]}
        return [summary_msg] + self.messages[cut:]

    async def compact_if_needed(
        self,
        backend,  # LLMBackend instance
        system_prompt: str,
        max_tokens: int,
        threshold_pct: int = 80,
    ) -> bool:
        """Trigger compaction if token usage exceeds threshold. Returns True if compacted."""
        context_window = get_context_window(self.model)
        threshold = context_window * threshold_pct // 100

        if self._total_tokens < threshold:
            return False

        # Select oldest messages to summarize (~50% of current tokens)
        target = self._total_tokens // 2
        accumulated = 0
        cut_seq = 0

        db = await self.store._get_db()
        try:
            cursor = await db.execute(
                "SELECT seq, token_count_approx FROM agent_messages "
                "WHERE session_id = ? ORDER BY seq",
                (self.id,),
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()

        messages_to_summarize = []
        for row in rows:
            accumulated += row["token_count_approx"]
            cut_seq = row["seq"]
            messages_to_summarize.append(row["seq"])
            if accumulated >= target:
                break

        if not messages_to_summarize:
            return False

        # Build the text to summarize from actual message content
        db = await self.store._get_db()
        try:
            placeholders = ",".join("?" * len(messages_to_summarize))
            cursor = await db.execute(
                f"SELECT role, content FROM agent_messages "
                f"WHERE session_id = ? AND seq IN ({placeholders}) ORDER BY seq",
                [self.id] + messages_to_summarize,
            )
            old_messages = await cursor.fetchall()
        finally:
            await db.close()

        # Build a text representation for summarization
        text_parts = []
        for msg in old_messages:
            content = json.loads(msg["content"])
            role = msg["role"]
            if isinstance(content, dict):
                c = content.get("content", "")
                if isinstance(c, str):
                    text_parts.append(f"{role}: {c}")
                elif isinstance(c, list):
                    for block in c:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(f"{role}: {block.get('text', '')}")
            elif isinstance(content, str):
                text_parts.append(f"{role}: {content}")

        transcript = "\n".join(text_parts)

        # Ask LLM to summarize
        compaction_prompt = (
            "Summarize the following conversation excerpt concisely. "
            "Preserve all key facts, decisions, tool call results, and action items.\n\n"
            f"{transcript}"
        )
        summary_messages = [{"role": "user", "content": compaction_prompt}]
        from kaori_agent.llm.base import TurnResult
        result: TurnResult = await backend.chat(
            summary_messages, [], system_prompt, self.model, max_tokens
        )
        summary_text = (
            f"[Earlier in this conversation, we discussed the following:\n"
            f"{result.text}\n"
            f"The conversation continues from here.]"
        )

        # Determine version
        db = await self.store._get_db()
        try:
            cursor = await db.execute(
                "SELECT COALESCE(MAX(version), 0) FROM agent_compactions WHERE session_id = ?",
                (self.id,),
            )
            row = await cursor.fetchone()
            new_version = row[0] + 1

            # Deactivate previous compactions
            await db.execute(
                "UPDATE agent_compactions SET is_active = 0 WHERE session_id = ?",
                (self.id,),
            )

            # Insert new compaction
            await db.execute(
                "INSERT INTO agent_compactions "
                "(session_id, version, is_active, summary_text, messages_summarized, "
                "up_to_seq, llm_backend, model, raw_response) "
                "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)",
                (
                    self.id, new_version, summary_text,
                    len(messages_to_summarize), cut_seq,
                    self.backend, self.model, result.text,
                ),
            )

            # Recalculate token count for remaining messages
            cursor = await db.execute(
                "SELECT COALESCE(SUM(token_count_approx), 0) FROM agent_messages "
                "WHERE session_id = ? AND seq > ?",
                (self.id, cut_seq),
            )
            remaining_tokens = (await cursor.fetchone())[0]
            summary_tokens = estimate_tokens(summary_text)
            self._total_tokens = remaining_tokens + summary_tokens

            await db.execute(
                "UPDATE agent_sessions SET token_count_approx = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (self._total_tokens, self.id),
            )
            await db.commit()
        finally:
            await db.close()

        self._compaction = {
            "summary_text": summary_text,
            "up_to_seq": cut_seq,
            "version": new_version,
        }
        return True
