"""
BACKLOG-054 — POST /api/chat says so when no AI provider is configured.

The refusal is a 503 with a plain detail, raised after the persona check and
before session resolution, so it must leave no ChatSession or ChatMessage
row behind. Configured providers pass straight through to the (mocked)
stream. The AUDIT-13 generic stream-error handler is a separate path and is
covered by test_chat_sessions_v144.py.
"""
import pytest

from app import models, providers
from app.routers import chat as chat_module
from app.routers.chat import NO_PROVIDER_DETAIL

CHAT_BODY = {"messages": [{"role": "user", "content": "How am I tracking this month?"}]}


def _fake_stream(chunks):
    async def _stream(messages, tools, system):
        for c in chunks:
            yield c
    return _stream


def _set_provider(monkeypatch, provider, key="", base_url=""):
    monkeypatch.setattr(providers, "AI_PROVIDER", provider)
    monkeypatch.setattr(providers, "AI_API_KEY", key)
    monkeypatch.setattr(providers, "AI_BASE_URL", base_url)
    # chat.py binds these by value at import; keep it consistent with the
    # provider under test (session provider stamp, ollama write-tool strip).
    monkeypatch.setattr(chat_module, "AI_PROVIDER", provider)
    monkeypatch.setattr(chat_module, "AI_BASE_URL", base_url)


def _counts(db):
    return (db.query(models.ChatSession).count(), db.query(models.ChatMessage).count())


# ── is_configured() ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("provider,key,base_url,expected", [
    ("anthropic", "", "", False),
    ("anthropic", "k", "", True),
    ("openai", "", "http://llm.example.invalid/v1", False),
    ("openai", "k", "", True),
    ("ollama", "", "", False),
    ("ollama", "", "http://ollama.example.invalid:11434/v1", True),
    ("ollama", "k", "", False),
    ("gemini", "k", "http://x.example.invalid", False),
])
def test_is_configured_matrix(monkeypatch, provider, key, base_url, expected):
    monkeypatch.setattr(providers, "AI_PROVIDER", provider)
    monkeypatch.setattr(providers, "AI_API_KEY", key)
    monkeypatch.setattr(providers, "AI_BASE_URL", base_url)
    assert providers.is_configured() is expected


# ── POST /api/chat ───────────────────────────────────────────────────────────

def test_empty_key_returns_503_and_persists_nothing(client, db, auth_headers, monkeypatch):
    _set_provider(monkeypatch, "anthropic", key="")
    called = []

    async def _must_not_stream(*a, **kw):
        called.append(True)
        yield "should not happen"

    monkeypatch.setattr(chat_module, "stream_chat", _must_not_stream)
    before = _counts(db)

    resp = client.post("/api/chat", headers=auth_headers, json=CHAT_BODY)

    assert resp.status_code == 503
    assert resp.json() == {"detail": NO_PROVIDER_DETAIL}
    assert "AI_API_KEY" in NO_PROVIDER_DETAIL
    assert "restart" in NO_PROVIDER_DETAIL
    assert "docs/ai-coach.md" in NO_PROVIDER_DETAIL
    assert _counts(db) == before
    assert called == []


def test_ollama_with_base_url_passes(client, db, auth_headers, monkeypatch):
    _set_provider(monkeypatch, "ollama", key="", base_url="http://ollama.example.invalid:11434/v1")
    monkeypatch.setattr(chat_module, "stream_chat", _fake_stream(["local ", "reply"]))
    sessions_before = db.query(models.ChatSession).count()

    resp = client.post("/api/chat", headers=auth_headers, json=CHAT_BODY)

    assert resp.status_code == 200
    assert "local " in resp.text and "event: done" in resp.text
    assert db.query(models.ChatSession).count() == sessions_before + 1


def test_anthropic_with_key_passes(client, db, auth_headers, monkeypatch):
    _set_provider(monkeypatch, "anthropic", key="not-a-real-key")
    monkeypatch.setattr(chat_module, "stream_chat", _fake_stream(["hosted reply"]))
    sessions_before = db.query(models.ChatSession).count()

    resp = client.post("/api/chat", headers=auth_headers, json=CHAT_BODY)

    assert resp.status_code == 200
    assert "hosted reply" in resp.text
    assert db.query(models.ChatSession).count() == sessions_before + 1
