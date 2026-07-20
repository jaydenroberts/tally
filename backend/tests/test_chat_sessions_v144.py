"""
BACKLOG-016 (v1.4.4) — chat session persistence tests.

Covers the locked-spec invariants:
- cross-cutting 404 (cross-user AND cross-persona, identical body shape on all
  three id-taking paths: GET, DELETE, POST /api/chat with session_id)
- tail-match idempotent retry vs 409
- orphan-tool reconciliation on read (synthetic directive results, incl.
  multi-round orphans; Anthropic and OpenAI replay formats)
- provider-lock refuse on resume
- cascade delete
- cursor pagination
- provider-aware history cap (CHAT_HISTORY_TURNS)
- title heuristic
- stream-error redaction (literal marker + correlation ID, no exception text)

All AI provider traffic is mocked at the stream_chat seam — no fixture ships
any real conversation content, and no seed chat rows exist anywhere.
"""
import json

import pytest

from app import models
from app.auth import hash_password
from app.routers import chat as chat_module
from app.routers import chat_sessions as sessions_module
from app.routers.chat import (
    ORPHAN_TOOL_NOTICE,
    STREAM_INTERRUPTED,
    _build_replay_messages,
    _history_turn_limit,
    _load_history_rows,
    _finalize_session,
    SENTINEL,
)

NOT_FOUND_BODY = {"detail": "Session not found"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_stream(rounds, calls=None):
    """
    Build a fake stream_chat. `rounds` is a list of per-round chunk lists;
    each call consumes one round. Strings starting with SENTINEL are tool
    sentinels. A chunk that is an Exception instance is raised mid-stream.
    """
    state = {"i": 0}

    async def _stream(messages, tools, system):
        if calls is not None:
            calls.append({"messages": [dict(m) for m in messages], "tools": list(tools)})
        chunks = rounds[min(state["i"], len(rounds) - 1)]
        state["i"] += 1
        for chunk in chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    return _stream


def tool_sentinel(tool_id, name, tool_input=None):
    return SENTINEL + json.dumps({"id": tool_id, "name": name, "input": tool_input or {}})


def parse_sse(body: str):
    """Parse an SSE body into a list of (event, data) tuples."""
    events = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event, data_lines = "delta", []
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
        events.append((event, "\n".join(data_lines)))
    return events


def seed_session(db, user, persona, provider="anthropic", title=None):
    session = models.ChatSession(
        user_id=user.id, persona_id=persona.id, provider=provider, title=title,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def seed_row(db, session_id, role, content, tool_use_id=None):
    row = models.ChatMessage(
        session_id=session_id, role=role, content=content, tool_use_id=tool_use_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mem_row(row_id, role, content, tool_use_id=None):
    """Detached in-memory row for pure replay-builder tests."""
    return models.ChatMessage(
        id=row_id, session_id=1, role=role, content=content, tool_use_id=tool_use_id,
    )


@pytest.fixture()
def owner_user(db, owner_token):
    return db.query(models.User).filter(models.User.username == "testowner").first()


@pytest.fixture()
def analyst_persona(db, owner_token):
    return db.query(models.Persona).filter(models.Persona.name == "analyst").first()


@pytest.fixture()
def second_user_headers(client, db, owner_token, analyst_persona):
    """A second user on the SAME persona — exercises the cross-user 404."""
    role = db.query(models.Role).filter(models.Role.name == "owner").first()
    user = models.User(
        username="seconduser",
        hashed_password=hash_password("otherpass"),
        role_id=role.id,
        persona_id=analyst_persona.id,
    )
    db.add(user)
    db.commit()
    resp = client.post("/api/auth/login", json={"username": "seconduser", "password": "otherpass"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def second_persona(db, owner_token):
    persona = models.Persona(
        name="secondary",
        description="Test",
        data_access_level="full",
        can_modify_data=False,
        is_system=False,
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return persona


# ---------------------------------------------------------------------------
# Session creation + streamed persistence
# ---------------------------------------------------------------------------

def test_chat_creates_session_emits_event_and_persists_rows(
    client, db, auth_headers, owner_user, monkeypatch,
):
    monkeypatch.setattr(chat_module, "stream_chat", make_stream([["Hello ", "there."]]))
    resp = client.post(
        "/api/chat",
        headers=auth_headers,
        json={"messages": [{"role": "user", "content": "What did I spend on groceries?"}]},
    )
    assert resp.status_code == 200
    events = parse_sse(resp.text)

    # `session` must be the FIRST event when a session was implicitly created.
    assert events[0][0] == "session"
    session_id = json.loads(events[0][1])["session_id"]
    assert events[-1] == ("done", "[DONE]")

    rows = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session_id)
        .order_by(models.ChatMessage.id)
        .all()
    )
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].content == "What did I spend on groceries?"
    assert rows[1].content == "Hello there."

    session = db.get(models.ChatSession, session_id)
    assert session.provider == "anthropic"
    assert session.title == "What did I spend on groceries?"
    assert session.persona_id == owner_user.persona_id


def test_resumed_chat_does_not_emit_session_event_and_replays_db_history(
    client, db, auth_headers, owner_user, analyst_persona, monkeypatch,
):
    session = seed_session(db, owner_user, analyst_persona)
    seed_row(db, session.id, "user", "first question")
    seed_row(db, session.id, "assistant", "first answer")

    calls = []
    monkeypatch.setattr(chat_module, "stream_chat", make_stream([["ok"]], calls))
    resp = client.post(
        "/api/chat",
        headers=auth_headers,
        json={
            "session_id": session.id,
            # Client-side junk history beyond the tail must be ignored.
            "messages": [
                {"role": "user", "content": "client-side stale copy"},
                {"role": "user", "content": "second question"},
            ],
        },
    )
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    assert all(ev != "session" for ev, _ in events)

    # Replay came from the DB, not the client payload.
    sent = calls[0]["messages"]
    assert sent == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
    ]
    assert not any(m.get("content") == "client-side stale copy" for m in sent)


def test_tool_rounds_persist_call_and_result_rows(client, db, auth_headers, monkeypatch):
    rounds = [
        ["Checking. ", tool_sentinel("tu_1", "get_accounts")],
        ["All done."],
    ]
    monkeypatch.setattr(chat_module, "stream_chat", make_stream(rounds))
    monkeypatch.setattr(chat_module, "_execute_tool", lambda **kw: {"ok": True})

    resp = client.post(
        "/api/chat",
        headers=auth_headers,
        json={"messages": [{"role": "user", "content": "check my accounts"}]},
    )
    assert resp.status_code == 200
    session_id = json.loads(parse_sse(resp.text)[0][1])["session_id"]

    rows = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session_id)
        .order_by(models.ChatMessage.id)
        .all()
    )
    # user, tool_call, tool_result, assistant (round close), assistant (final)
    assert [r.role for r in rows] == ["user", "tool_call", "tool_result", "assistant", "assistant"]
    assert rows[1].tool_use_id == "tu_1"
    assert rows[2].tool_use_id == "tu_1"
    assert json.loads(rows[2].content) == {"ok": True}
    assert rows[3].content == "Checking. "
    assert rows[4].content == "All done."


# ---------------------------------------------------------------------------
# Cross-cutting 404 invariant
# ---------------------------------------------------------------------------

def _assert_404_everywhere(client, headers, session_id):
    """All three id-taking paths must return an identical 404 body."""
    get_resp = client.get(f"/api/chat/sessions/{session_id}", headers=headers)
    del_resp = client.delete(f"/api/chat/sessions/{session_id}", headers=headers)
    chat_resp = client.post(
        "/api/chat",
        headers=headers,
        json={"session_id": session_id, "messages": [{"role": "user", "content": "hi"}]},
    )
    for resp in (get_resp, del_resp, chat_resp):
        assert resp.status_code == 404
        assert resp.json() == NOT_FOUND_BODY


def test_404_invariant_cross_user(
    client, db, auth_headers, second_user_headers, owner_user, analyst_persona,
):
    session = seed_session(db, owner_user, analyst_persona)
    _assert_404_everywhere(client, second_user_headers, session.id)
    # Session untouched
    assert db.get(models.ChatSession, session.id) is not None


def test_404_invariant_cross_persona(
    client, db, auth_headers, owner_user, analyst_persona, second_persona,
):
    session = seed_session(db, owner_user, analyst_persona)
    # Same user switches persona — their own old-persona session must 404.
    owner_user.persona_id = second_persona.id
    db.commit()
    _assert_404_everywhere(client, auth_headers, session.id)


def test_404_invariant_nonexistent_id_same_shape(client, auth_headers, owner_token):
    _assert_404_everywhere(client, auth_headers, 999999)


# ---------------------------------------------------------------------------
# Tail-match idempotency vs 409
# ---------------------------------------------------------------------------

def test_retry_with_matching_tail_does_not_duplicate_user_row(
    client, db, auth_headers, owner_user, analyst_persona, monkeypatch,
):
    session = seed_session(db, owner_user, analyst_persona)
    seed_row(db, session.id, "user", "retry me")  # interrupted turn: user row, no reply

    monkeypatch.setattr(chat_module, "stream_chat", make_stream([["answered"]]))
    resp = client.post(
        "/api/chat",
        headers=auth_headers,
        json={"session_id": session.id, "messages": [{"role": "user", "content": "retry me"}]},
    )
    assert resp.status_code == 200
    user_rows = (
        db.query(models.ChatMessage)
        .filter(
            models.ChatMessage.session_id == session.id,
            models.ChatMessage.role == "user",
        )
        .all()
    )
    assert len(user_rows) == 1  # idempotent — no duplicate insert


def test_new_user_message_appends_row(
    client, db, auth_headers, owner_user, analyst_persona, monkeypatch,
):
    session = seed_session(db, owner_user, analyst_persona)
    seed_row(db, session.id, "user", "old question")
    seed_row(db, session.id, "assistant", "old answer")

    monkeypatch.setattr(chat_module, "stream_chat", make_stream([["new answer"]]))
    resp = client.post(
        "/api/chat",
        headers=auth_headers,
        json={"session_id": session.id, "messages": [{"role": "user", "content": "new question"}]},
    )
    assert resp.status_code == 200
    user_rows = (
        db.query(models.ChatMessage)
        .filter(
            models.ChatMessage.session_id == session.id,
            models.ChatMessage.role == "user",
        )
        .order_by(models.ChatMessage.id)
        .all()
    )
    assert [r.content for r in user_rows] == ["old question", "new question"]


def test_non_user_trailing_message_409(
    client, db, auth_headers, owner_user, analyst_persona,
):
    session = seed_session(db, owner_user, analyst_persona)
    resp = client.post(
        "/api/chat",
        headers=auth_headers,
        json={"session_id": session.id, "messages": [{"role": "assistant", "content": "?"}]},
    )
    assert resp.status_code == 409

    # Same check without session_id must not leave an orphan session behind.
    before = db.query(models.ChatSession).count()
    resp = client.post(
        "/api/chat",
        headers=auth_headers,
        json={"messages": [{"role": "assistant", "content": "?"}]},
    )
    assert resp.status_code == 409
    assert db.query(models.ChatSession).count() == before


# ---------------------------------------------------------------------------
# Provider lock
# ---------------------------------------------------------------------------

def test_provider_mismatch_refuses_resume(
    client, db, auth_headers, owner_user, analyst_persona,
):
    session = seed_session(db, owner_user, analyst_persona, provider="openai")
    resp = client.post(
        "/api/chat",
        headers=auth_headers,
        json={"session_id": session.id, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 409
    assert "different AI provider" in resp.json()["detail"]
    # Nothing was written to the locked session.
    assert (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session.id)
        .count()
    ) == 0


def test_list_endpoint_reports_current_provider(client, auth_headers, owner_token):
    resp = client.get("/api/chat/sessions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == chat_module.AI_PROVIDER
    assert body["sessions"] == []


# ---------------------------------------------------------------------------
# List / create / delete
# ---------------------------------------------------------------------------

def test_list_is_scoped_and_ordered(
    client, db, auth_headers, owner_user, analyst_persona, second_persona,
):
    s1 = seed_session(db, owner_user, analyst_persona, title="older")
    s2 = seed_session(db, owner_user, analyst_persona, title="newer")
    seed_session(db, owner_user, second_persona, title="other persona")
    # Bump s2 so it sorts first.
    seed_row(db, s2.id, "user", "x")
    _finalize_session(db, s2.id)

    resp = client.get("/api/chat/sessions", headers=auth_headers)
    body = resp.json()
    ids = [s["id"] for s in body["sessions"]]
    assert ids == [s2.id, s1.id]  # other-persona session excluded, newest first


def test_create_empty_session(client, db, auth_headers, owner_user):
    resp = client.post("/api/chat/sessions", headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] is None
    assert body["provider"] == chat_module.AI_PROVIDER
    session = db.get(models.ChatSession, body["id"])
    assert session.user_id == owner_user.id


def test_delete_cascades_messages(
    client, db, auth_headers, owner_user, analyst_persona,
):
    session = seed_session(db, owner_user, analyst_persona)
    seed_row(db, session.id, "user", "a")
    seed_row(db, session.id, "assistant", "b")
    seed_row(db, session.id, "tool_call", "{}", tool_use_id="tu_9")

    resp = client.delete(f"/api/chat/sessions/{session.id}", headers=auth_headers)
    assert resp.status_code == 204
    assert db.get(models.ChatSession, session.id) is None
    assert (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session.id)
        .count()
    ) == 0


# ---------------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------------

def test_get_session_cursor_pagination(
    client, db, auth_headers, owner_user, analyst_persona, monkeypatch,
):
    session = seed_session(db, owner_user, analyst_persona)
    rows = [seed_row(db, session.id, "user", f"m{i}") for i in range(8)]

    # Default page returns everything (under the cap), ascending.
    resp = client.get(f"/api/chat/sessions/{session.id}", headers=auth_headers)
    body = resp.json()
    assert [m["content"] for m in body["messages"]] == [f"m{i}" for i in range(8)]
    assert body["has_more"] is False

    # Shrink the cap: newest page returned, has_more flags older history.
    monkeypatch.setattr(sessions_module, "MESSAGE_PAGE_CAP", 3)
    resp = client.get(f"/api/chat/sessions/{session.id}", headers=auth_headers)
    body = resp.json()
    assert [m["content"] for m in body["messages"]] == ["m5", "m6", "m7"]
    assert body["has_more"] is True

    # Page backwards with before_id from the oldest returned row.
    before = body["messages"][0]["id"]
    resp = client.get(
        f"/api/chat/sessions/{session.id}?before_id={before}", headers=auth_headers,
    )
    body = resp.json()
    assert [m["content"] for m in body["messages"]] == ["m2", "m3", "m4"]
    assert body["has_more"] is True
    assert all(m["id"] < before for m in body["messages"])


# ---------------------------------------------------------------------------
# Orphan-tool reconciliation (pure replay builder)
# ---------------------------------------------------------------------------

def test_orphan_tool_gets_synthetic_result_anthropic():
    rows = [
        mem_row(1, "user", "check accounts"),
        mem_row(2, "tool_call", json.dumps({"id": "tu_1", "name": "get_accounts", "input": {}}), "tu_1"),
        mem_row(3, "assistant", STREAM_INTERRUPTED),  # crashed before tool_result
        mem_row(4, "user", "did that work?"),
    ]
    out = _build_replay_messages(rows, "anthropic")

    assert out[0] == {"role": "user", "content": "check accounts"}
    # Assistant turn owns the orphaned tool_use.
    kinds = [b["type"] for b in out[1]["content"]]
    assert out[1]["role"] == "assistant" and "tool_use" in kinds
    # Synthetic directive result is grouped into the FOLLOWING user turn.
    assert out[2]["role"] == "user"
    synthetic = out[2]["content"][0]
    assert synthetic["type"] == "tool_result"
    assert synthetic["tool_use_id"] == "tu_1"
    assert synthetic["is_error"] is True
    assert synthetic["content"] == ORPHAN_TOOL_NOTICE
    # The real user text rides in the same turn (role alternation preserved).
    assert out[2]["content"][-1] == {"type": "text", "text": "did that work?"}
    assert len(out) == 3


def test_multi_round_orphans_each_get_synthetics():
    rows = [
        mem_row(1, "user", "do two things"),
        # Round 1: completed normally.
        mem_row(2, "tool_call", json.dumps({"id": "tu_1", "name": "get_accounts", "input": {}}), "tu_1"),
        mem_row(3, "tool_result", json.dumps({"ok": 1}), "tu_1"),
        mem_row(4, "assistant", ""),
        # Round 2: two calls, only the first got a result before the crash.
        mem_row(5, "tool_call", json.dumps({"id": "tu_2", "name": "get_categories", "input": {}}), "tu_2"),
        mem_row(6, "tool_call", json.dumps({"id": "tu_3", "name": "get_budget_summary", "input": {}}), "tu_3"),
        mem_row(7, "tool_result", json.dumps({"ok": 2}), "tu_2"),
        mem_row(8, "assistant", STREAM_INTERRUPTED),
        mem_row(9, "user", "continue"),
    ]
    out = _build_replay_messages(rows, "anthropic")

    # user, A(round1), U(results1), A(round2), U(results2 + text)
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant", "user"]
    results1 = out[2]["content"]
    assert results1[0]["tool_use_id"] == "tu_1"
    assert results1[0].get("is_error") is None
    results2 = out[4]["content"]
    by_id = {b["tool_use_id"]: b for b in results2 if b.get("type") == "tool_result"}
    assert by_id["tu_2"].get("is_error") is None          # real result kept
    assert by_id["tu_3"]["is_error"] is True              # orphan → synthetic
    assert by_id["tu_3"]["content"] == ORPHAN_TOOL_NOTICE


def test_orphan_synthetic_openai_format():
    rows = [
        mem_row(1, "user", "check"),
        mem_row(2, "tool_call", json.dumps({"id": "call_1", "name": "get_accounts", "input": {}}), "call_1"),
        mem_row(3, "assistant", STREAM_INTERRUPTED),
        mem_row(4, "user", "and now?"),
    ]
    out = _build_replay_messages(rows, "openai")
    assert out[1]["role"] == "assistant"
    assert out[1]["tool_calls"][0]["id"] == "call_1"
    tool_msg = out[2]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"
    payload = json.loads(tool_msg["content"])
    assert payload["is_error"] is True
    assert payload["content"] == ORPHAN_TOOL_NOTICE
    assert out[3] == {"role": "user", "content": "and now?"}


def test_completed_tool_round_replays_without_synthetics():
    rows = [
        mem_row(1, "user", "check"),
        mem_row(2, "tool_call", json.dumps({"id": "tu_1", "name": "get_accounts", "input": {}}), "tu_1"),
        mem_row(3, "tool_result", json.dumps([{"id": 1}]), "tu_1"),
        mem_row(4, "assistant", "Text with the round."),
        mem_row(5, "assistant", "Final answer."),
        mem_row(6, "user", "thanks"),
    ]
    out = _build_replay_messages(rows, "anthropic")
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant", "user"]
    assert not any(
        b.get("is_error")
        for m in out if isinstance(m["content"], list)
        for b in m["content"]
    )


# ---------------------------------------------------------------------------
# Provider-aware history cap
# ---------------------------------------------------------------------------

def test_history_turn_limit_defaults(monkeypatch):
    monkeypatch.delenv("CHAT_HISTORY_TURNS", raising=False)
    assert _history_turn_limit("anthropic", "") == 30
    assert _history_turn_limit("claude", "") == 30
    assert _history_turn_limit("openai", "") == 30
    assert _history_turn_limit("ollama", "") == 10
    assert _history_turn_limit("openai", "http://localhost:11434/v1") == 10  # base-url override
    assert _history_turn_limit("someday-provider", "") == 20


def test_history_turn_limit_env_override(monkeypatch):
    monkeypatch.setenv("CHAT_HISTORY_TURNS", "7")
    assert _history_turn_limit("anthropic", "") == 7
    monkeypatch.setenv("CHAT_HISTORY_TURNS", "not-a-number")
    assert _history_turn_limit("anthropic", "") == 30  # falls back to default


def test_load_history_rows_cuts_on_user_turn_boundary(
    db, owner_user, analyst_persona,
):
    session = seed_session(db, owner_user, analyst_persona)
    for i in range(4):
        seed_row(db, session.id, "user", f"q{i}")
        seed_row(db, session.id, "assistant", f"a{i}")

    rows = _load_history_rows(db, session, turn_limit=2)
    # Window starts at the 3rd user turn — always a user row first.
    assert [(r.role, r.content) for r in rows] == [
        ("user", "q2"), ("assistant", "a2"),
        ("user", "q3"), ("assistant", "a3"),
    ]


# ---------------------------------------------------------------------------
# Title heuristic
# ---------------------------------------------------------------------------

def test_title_truncates_on_whitespace(db, owner_user, analyst_persona):
    session = seed_session(db, owner_user, analyst_persona)
    long_msg = "please review all of my grocery spending patterns across the last three months in detail"
    seed_row(db, session.id, "user", long_msg)
    seed_row(db, session.id, "assistant", "Sure.")
    _finalize_session(db, session.id)
    db.refresh(session)
    assert len(session.title) <= 60
    assert not long_msg.startswith(session.title + " ") is False  # prefix on a word boundary
    assert long_msg.startswith(session.title)
    assert session.title[-1] != " "


def test_title_short_prompt_appends_assistant_snippet(db, owner_user, analyst_persona):
    session = seed_session(db, owner_user, analyst_persona)
    seed_row(db, session.id, "user", "review budget")  # ≤3 words → heuristic kicks in
    seed_row(db, session.id, "assistant", "Your monthly budget is currently tracking under target overall.")
    _finalize_session(db, session.id)
    db.refresh(session)
    assert session.title.startswith("review budget — ")
    appended = session.title.split(" — ", 1)[1]
    assert len(appended) <= 40


def test_title_not_overwritten_once_set(db, owner_user, analyst_persona):
    session = seed_session(db, owner_user, analyst_persona, title="kept")
    seed_row(db, session.id, "user", "something else")
    _finalize_session(db, session.id)
    db.refresh(session)
    assert session.title == "kept"


# ---------------------------------------------------------------------------
# Stream-error redaction
# ---------------------------------------------------------------------------

def test_stream_error_is_redacted_and_marks_interruption(
    client, db, auth_headers, monkeypatch,
):
    boom = RuntimeError("SECRET-PROVIDER-DETAIL https://internal.example/api key=abc")
    monkeypatch.setattr(
        chat_module, "stream_chat", make_stream([["partial ", boom]]),
    )
    resp = client.post(
        "/api/chat",
        headers=auth_headers,
        json={"messages": [{"role": "user", "content": "trigger failure"}]},
    )
    assert resp.status_code == 200
    # No exception text, URL, or detail leaks into the SSE payload.
    assert "SECRET-PROVIDER-DETAIL" not in resp.text
    assert "internal.example" not in resp.text
    assert "RuntimeError" not in resp.text

    events = parse_sse(resp.text)
    error_events = [d for e, d in events if e == "error"]
    assert len(error_events) == 1
    assert "(ref: " in error_events[0]  # correlation ID for support
    assert events[-1] == ("done", "[DONE]")

    # Terminal marker row persisted; partial state kept truthfully.
    session_id = json.loads(events[0][1])["session_id"]
    rows = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session_id)
        .order_by(models.ChatMessage.id)
        .all()
    )
    assert rows[-1].role == "assistant"
    assert rows[-1].content == STREAM_INTERRUPTED
