"""Tests for session persistence (Phase 4)."""

import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from kaori_agent.session import Session, SessionStore, estimate_tokens, get_context_window


@pytest_asyncio.fixture
async def store(tmp_path):
    """Create a SessionStore with a temp DB file."""
    db_path = tmp_path / "test_agent.db"
    s = SessionStore(db_path)
    await s.initialize()
    return s


# ---------------------------------------------------------------------------
# SessionStore tests
# ---------------------------------------------------------------------------

class TestSessionStore:

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, store: SessionStore):
        """Tables should exist after initialize()."""
        import aiosqlite
        db = await aiosqlite.connect(str(store.db_path))
        try:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'agent_%'"
            )
            tables = {row[0] for row in await cursor.fetchall()}
            assert "agent_sessions" in tables
            assert "agent_messages" in tables
            assert "agent_memory" in tables
            assert "agent_compactions" in tables
            assert "agent_prompts" in tables
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, store: SessionStore):
        """Calling initialize() twice should not error."""
        await store.initialize()  # second call

    @pytest.mark.asyncio
    async def test_create_session(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        assert session.id
        assert session.backend == "deepseek"
        assert session.model == "deepseek-chat"
        assert session.messages == []
        assert session.title is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, store: SessionStore):
        await store.create_session("deepseek", "deepseek-chat")
        await store.create_session("anthropic", "claude-sonnet-4-6")
        sessions = await store.list_sessions()
        assert len(sessions) == 2
        backends = {s["backend"] for s in sessions}
        assert backends == {"deepseek", "anthropic"}

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, store: SessionStore):
        sessions = await store.list_sessions()
        assert sessions == []

    @pytest.mark.asyncio
    async def test_delete_session(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        deleted = await store.delete_session(session.id)
        assert deleted is True
        sessions = await store.list_sessions()
        assert len(sessions) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store: SessionStore):
        deleted = await store.delete_session("nonexistent-id")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_load_session_not_found(self, store: SessionStore):
        with pytest.raises(ValueError, match="Session not found"):
            await store.load_session("nonexistent-id")


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

class TestSession:

    @pytest.mark.asyncio
    async def test_append_and_load(self, store: SessionStore):
        """Messages should persist and be loadable."""
        session = await store.create_session("deepseek", "deepseek-chat")
        msg = {"role": "user", "content": "Hello"}
        session.messages.append(msg)
        await session.append_message("user", msg)

        # Load the same session
        loaded = await store.load_session(session.id)
        assert len(loaded.messages) == 1
        assert loaded.messages[0]["role"] == "user"
        assert loaded.messages[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_append_multiple_messages(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        for i in range(5):
            msg = {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            session.messages.append(msg)
            await session.append_message(msg["role"], msg)

        loaded = await store.load_session(session.id)
        assert len(loaded.messages) == 5
        assert loaded.messages[0]["content"] == "msg 0"
        assert loaded.messages[4]["content"] == "msg 4"

    @pytest.mark.asyncio
    async def test_set_title(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        await session.set_title("My Conversation")

        loaded = await store.load_session(session.id)
        assert loaded.title == "My Conversation"

    @pytest.mark.asyncio
    async def test_auto_title(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        msg = {"role": "user", "content": "What is the meaning of life?"}
        session.messages.append(msg)
        await session.append_message("user", msg)
        await session.auto_title()

        assert session.title == "What is the meaning of life?"
        # Verify persisted
        loaded = await store.load_session(session.id)
        assert loaded.title == "What is the meaning of life?"

    @pytest.mark.asyncio
    async def test_auto_title_truncates(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        msg = {"role": "user", "content": "x" * 100}
        session.messages.append(msg)
        await session.append_message("user", msg)
        await session.auto_title()

        assert len(session.title) == 63  # 60 chars + "..."
        assert session.title.endswith("...")

    @pytest.mark.asyncio
    async def test_auto_title_skips_if_already_set(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        await session.set_title("Already Set")
        msg = {"role": "user", "content": "This should not become the title"}
        session.messages.append(msg)
        await session.auto_title()

        assert session.title == "Already Set"

    @pytest.mark.asyncio
    async def test_get_effective_messages_no_compaction(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        for m in msgs:
            session.messages.append(m)
            await session.append_message(m["role"], m)

        effective = session.get_effective_messages()
        assert effective == session.messages

    @pytest.mark.asyncio
    async def test_get_effective_messages_with_compaction(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        for i in range(6):
            msg = {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            session.messages.append(msg)
            await session.append_message(msg["role"], msg)

        # Manually set compaction
        session._compaction = {
            "summary_text": "[Summary of messages 0-3]",
            "up_to_seq": 3,
            "version": 1,
        }
        effective = session.get_effective_messages()
        # Should be: summary + messages[4:]
        assert len(effective) == 3  # summary + msg 4 + msg 5
        assert effective[0]["content"] == "[Summary of messages 0-3]"
        assert effective[1]["content"] == "msg 4"
        assert effective[2]["content"] == "msg 5"

    @pytest.mark.asyncio
    async def test_message_count_and_tokens_updated(self, store: SessionStore):
        session = await store.create_session("deepseek", "deepseek-chat")
        msg = {"role": "user", "content": "Hello world"}
        session.messages.append(msg)
        await session.append_message("user", msg)

        sessions = await store.list_sessions()
        assert sessions[0]["message_count"] == 1
        assert sessions[0]["token_count_approx"] > 0


# ---------------------------------------------------------------------------
# Memory tests
# ---------------------------------------------------------------------------

class TestMemory:

    @pytest.mark.asyncio
    async def test_set_and_get(self, store: SessionStore):
        await store.set_memory("name", "Alice", "fact")
        entry = await store.get_memory("name")
        assert entry is not None
        assert entry["value"] == "Alice"
        assert entry["category"] == "fact"

    @pytest.mark.asyncio
    async def test_upsert(self, store: SessionStore):
        await store.set_memory("lang", "en")
        await store.set_memory("lang", "zh")
        entry = await store.get_memory("lang")
        assert entry["value"] == "zh"

    @pytest.mark.asyncio
    async def test_list_all(self, store: SessionStore):
        await store.set_memory("a", "1")
        await store.set_memory("b", "2")
        entries = await store.list_memory()
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_list_by_category(self, store: SessionStore):
        await store.set_memory("a", "1", "preference")
        await store.set_memory("b", "2", "fact")
        entries = await store.list_memory(category="preference")
        assert len(entries) == 1
        assert entries[0]["key"] == "a"

    @pytest.mark.asyncio
    async def test_delete(self, store: SessionStore):
        await store.set_memory("temp", "value")
        deleted = await store.delete_memory("temp")
        assert deleted is True
        assert await store.get_memory("temp") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store: SessionStore):
        deleted = await store.delete_memory("nope")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store: SessionStore):
        entry = await store.get_memory("nope")
        assert entry is None


# ---------------------------------------------------------------------------
# Token estimation tests
# ---------------------------------------------------------------------------

class TestTokenEstimation:

    def test_ascii(self):
        # ~4 chars per token
        assert estimate_tokens("hello world") == 2  # 11 / 4 = 2

    def test_cjk(self):
        # ~2 chars per token
        text = "你好世界"
        assert estimate_tokens(text) == 2  # 4 CJK chars / 2 = 2

    def test_mixed(self):
        text = "Hello 你好"
        # 6 ASCII + 2 CJK = 6//4 + 2//2 = 1 + 1 = 2
        assert estimate_tokens(text) == 2

    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_context_window_known(self):
        assert get_context_window("deepseek-chat") == 64_000

    def test_context_window_unknown(self):
        assert get_context_window("unknown-model") == 64_000


# ---------------------------------------------------------------------------
# Memory tools tests
# ---------------------------------------------------------------------------

class TestMemoryTools:

    @pytest.mark.asyncio
    async def test_save_memory_tool(self, store: SessionStore):
        from kaori_agent.tools.memory import SaveMemoryTool
        tool = SaveMemoryTool(session_store=store, session_id="test-session")
        result = await tool.execute(key="name", value="Bob")
        assert not result.is_error
        assert "Saved" in result.output

        entry = await store.get_memory("name")
        assert entry["value"] == "Bob"

    @pytest.mark.asyncio
    async def test_save_memory_tool_no_store(self):
        from kaori_agent.tools.memory import SaveMemoryTool
        tool = SaveMemoryTool()
        result = await tool.execute(key="name", value="Bob")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_get_memory_tool_all(self, store: SessionStore):
        from kaori_agent.tools.memory import GetMemoryTool
        await store.set_memory("a", "1")
        await store.set_memory("b", "2")
        tool = GetMemoryTool(session_store=store)
        result = await tool.execute()
        assert not result.is_error
        assert "a: 1" in result.output
        assert "b: 2" in result.output

    @pytest.mark.asyncio
    async def test_get_memory_tool_by_key(self, store: SessionStore):
        from kaori_agent.tools.memory import GetMemoryTool
        await store.set_memory("lang", "zh")
        tool = GetMemoryTool(session_store=store)
        result = await tool.execute(key="lang")
        assert not result.is_error
        assert "zh" in result.output

    @pytest.mark.asyncio
    async def test_get_memory_tool_empty(self, store: SessionStore):
        from kaori_agent.tools.memory import GetMemoryTool
        tool = GetMemoryTool(session_store=store)
        result = await tool.execute()
        assert not result.is_error
        assert "No memories" in result.output
