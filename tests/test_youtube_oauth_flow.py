import json
import time
import urllib.parse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import main


def configure_youtube_test(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "sintu-test.sqlite3")
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("YOUTUBE_REDIRECT_URI", "https://studio.example.test/api/admin/youtube/oauth/callback")
    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    main.init_db()


def test_youtube_oauth_state_channel_verification_and_encrypted_storage(tmp_path, monkeypatch):
    configure_youtube_test(tmp_path, monkeypatch)
    calls = []

    def fake_google_request(url, data=None, headers=None, method=None):
        calls.append((url, data, headers))
        if url == "https://oauth2.googleapis.com/token":
            return 200, {}, json.dumps({
                "access_token": "test-access-secret",
                "refresh_token": "test-refresh-secret",
                "expires_in": 3600,
                "token_type": "Bearer",
            }).encode("utf-8")
        assert url == "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
        assert headers["Authorization"] == "Bearer test-access-secret"
        return 200, {}, json.dumps({
            "items": [{"id": "channel-123", "snippet": {"title": "Verified test channel"}}]
        }).encode("utf-8")

    monkeypatch.setattr(main, "_youtube_request", fake_google_request)
    client = TestClient(main.app, follow_redirects=False)

    started = client.post("/api/admin/youtube/oauth/start")
    assert started.status_code == 200
    authorization = urllib.parse.urlsplit(started.json()["authorization_url"])
    query = urllib.parse.parse_qs(authorization.query)
    assert authorization.netloc == "accounts.google.com"
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == [main._youtube_config()["redirect_uri"]]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["state"] and len(query["state"][0]) >= 32
    state = query["state"][0]

    callback = client.get(
        "/api/admin/youtube/oauth/callback",
        params={"code": "one-time-auth-code", "state": state},
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/?youtube_oauth=connected"
    assert len(calls) == 2
    assert urllib.parse.parse_qs(calls[0][1].decode())["grant_type"] == ["authorization_code"]

    connection = main._youtube_connection()
    assert connection["channel_id"] == "channel-123"
    assert connection["channel_title"] == "Verified test channel"
    with main.db() as conn:
        row = conn.execute("SELECT encrypted_tokens FROM youtube_connection WHERE id=1").fetchone()
    stored = json.loads(main._youtube_cipher().decrypt(row["encrypted_tokens"].encode()).decode())
    assert stored["access_token"] == "test-access-secret"
    assert stored["refresh_token"] == "test-refresh-secret"

    status = client.get("/api/admin/youtube/status")
    assert status.status_code == 200
    assert status.json()["connected"] is True
    assert status.json()["channel"]["id"] == "channel-123"
    assert "test-access-secret" not in status.text
    assert "test-refresh-secret" not in status.text

    replay = client.get(
        "/api/admin/youtube/oauth/callback",
        params={"code": "replayed-code", "state": state},
    )
    assert replay.status_code == 400


def test_youtube_access_token_refresh_preserves_refresh_token(tmp_path, monkeypatch):
    configure_youtube_test(tmp_path, monkeypatch)
    cipher = main._youtube_cipher()
    encrypted = cipher.encrypt(json.dumps({
        "access_token": "expired-access",
        "refresh_token": "long-lived-refresh",
        "token_type": "Bearer",
    }).encode()).decode()
    with main.db() as conn:
        conn.execute(
            """INSERT INTO youtube_connection(
                id,channel_id,channel_title,encrypted_tokens,token_expiry,connected_at
            ) VALUES(1,?,?,?,?,?)""",
            ("channel-456", "Refresh test channel", encrypted, int(time.time()) - 10, "now"),
        )

    requests = []

    def fake_google_request(url, data=None, headers=None, method=None):
        requests.append((url, urllib.parse.parse_qs(data.decode()), headers))
        assert url == "https://oauth2.googleapis.com/token"
        return 200, {}, json.dumps({
            "access_token": "fresh-access-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }).encode("utf-8")

    monkeypatch.setattr(main, "_youtube_request", fake_google_request)
    assert main._youtube_access_token() == "fresh-access-token"
    assert len(requests) == 1
    assert requests[0][1]["refresh_token"] == ["long-lived-refresh"]
    with main.db() as conn:
        row = conn.execute("SELECT encrypted_tokens,token_expiry FROM youtube_connection WHERE id=1").fetchone()
    refreshed = json.loads(cipher.decrypt(row["encrypted_tokens"].encode()).decode())
    assert refreshed["access_token"] == "fresh-access-token"
    assert refreshed["refresh_token"] == "long-lived-refresh"
    assert row["token_expiry"] > int(time.time())



def test_youtube_oauth_state_is_bound_to_the_starting_browser_session(tmp_path, monkeypatch):
    configure_youtube_test(tmp_path, monkeypatch)
    client = TestClient(main.app, follow_redirects=False)
    started = client.post("/api/admin/youtube/oauth/start")
    assert started.status_code == 200
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(started.json()["authorization_url"]).query)
    state = query["state"][0]

    other_browser = TestClient(main.app, follow_redirects=False)
    other_browser.cookies.set(main.SESSION_COOKIE, "different-browser-session")
    rejected = other_browser.get(
        "/api/admin/youtube/oauth/callback",
        params={"code": "must-not-be-exchanged", "state": state},
    )
    assert rejected.status_code == 400
