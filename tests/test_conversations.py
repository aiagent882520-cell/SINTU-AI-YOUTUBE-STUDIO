import sqlite3
from starlette.requests import Request

import pytest
from fastapi import HTTPException

from app import main


def _request(user_id=7):
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/conversations",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("testclient", 1234),
        "scheme": "http",
    })
    request.state.user = {"id": user_id}
    return request


@pytest.fixture
def conversation_db(monkeypatch, tmp_path):
    connection = sqlite3.connect(tmp_path / "conversations.sqlite")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE ai_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT 'New conversation',
            workflow TEXT NOT NULL DEFAULT 'content',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE ai_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES ai_conversations(id)
        );
        INSERT INTO ai_conversations(owner_user_id,title,workflow,created_at,updated_at)
        VALUES (7,'New conversation','content','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z');
        INSERT INTO ai_conversations(owner_user_id,title,workflow,created_at,updated_at)
        VALUES (8,'Private conversation','content','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z');
        """
    )
    connection.commit()
    monkeypatch.setattr(main, "db", lambda: connection)
    yield connection
    connection.close()


def test_conversation_lookup_rejects_another_users_conversation(conversation_db):
    with pytest.raises(HTTPException) as exc:
        main._owned_conversation(2, 7)
    assert exc.value.status_code == 404


def test_conversation_list_is_scoped_to_authenticated_owner(conversation_db):
    result = main.list_conversations(_request(user_id=7))
    assert [item["title"] for item in result["conversations"]] == ["New conversation"]
    assert all(item.get("owner_user_id") is None for item in result["conversations"])


def test_message_turn_persists_user_and_assistant_messages(conversation_db, monkeypatch):
    observed = {}

    def fake_generate_text(prompt, workflow, provider=None):
        observed["prompt"] = prompt
        observed["workflow"] = workflow
        observed["provider"] = provider
        return {"output": "Namaste! Main SINTU hoon.", "provider": "local", "model": "test-model"}

    monkeypatch.setattr(main, "_get_app_setting", lambda key, default: default)
    monkeypatch.setattr(main, "generate_text", fake_generate_text)

    result = main.send_conversation_message(
        1,
        main.ConversationMessageInput(content="Namaste SINTU"),
        _request(user_id=7),
    )

    rows = conversation_db.execute(
        "SELECT role,content,status,provider,model FROM ai_messages "
        "WHERE conversation_id=1 ORDER BY id"
    ).fetchall()
    assert [(row["role"], row["content"], row["status"]) for row in rows] == [
        ("user", "Namaste SINTU", "received"),
        ("assistant", "Namaste! Main SINTU hoon.", "completed"),
    ]
    assert rows[1]["provider"] == "local"
    assert rows[1]["model"] == "test-model"
    assert result["message"]["content"] == "Namaste! Main SINTU hoon."
    assert observed["workflow"] == "content"
    assert "यूज़र: Namaste SINTU" in observed["prompt"]
