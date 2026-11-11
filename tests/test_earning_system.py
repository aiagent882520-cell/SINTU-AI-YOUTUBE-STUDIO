from fastapi.testclient import TestClient
from app import main

def setup_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SINTU_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SINTU_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "studio.sqlite3")
    main.init_db()
    return TestClient(main.app)

def test_earning_record_summary_and_export(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    created = client.post("/api/earnings/records", json={
        "kind": "income", "source": "affiliate", "title": "Affiliate payout",
        "amount": 1250.50, "currency": "INR", "status": "received",
        "record_date": "2026-11-05"
    })
    assert created.status_code == 201
    record_id = created.json()["record"]["id"]
    expense = client.post("/api/earnings/records", json={
        "kind": "expense", "source": "other", "title": "Editing expense",
        "amount": 200, "currency": "INR", "status": "confirmed",
        "record_date": "2026-11-06"
    })
    assert expense.status_code == 201
    summary = client.get("/api/earnings/summary?month=2026-11").json()
    assert summary["received_income"]["INR"] == 1250.5
    assert summary["expenses"]["INR"] == 200
    assert summary["net_confirmed"]["INR"] == 1050.5
    assert summary["notice"]
    assert "Affiliate payout" in client.get("/api/earnings/export.csv").text
    assert client.delete(f"/api/earnings/records/{record_id}").json()["deleted"] is True

def test_estimated_income_not_counted_as_received(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    client.post("/api/earnings/records", json={
        "kind": "income", "source": "youtube_ads", "title": "Estimated YouTube",
        "amount": 500, "currency": "INR", "status": "estimated",
        "record_date": "2026-11-07"
    })
    summary = client.get("/api/earnings/summary?month=2026-11").json()
    assert summary["estimated_income"]["INR"] == 500
    assert summary["received_income"] == {}
    assert summary["net_confirmed"] == {}

def test_monthly_target_progress(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    client.put("/api/earnings/target", json={"month":"2026-11","target_amount":10000,"currency":"INR"})
    client.post("/api/earnings/records", json={
        "kind":"income","source":"service","title":"Project payment",
        "amount":2500,"currency":"INR","status":"received","record_date":"2026-11-09"
    })
    summary=client.get("/api/earnings/summary?month=2026-11").json()
    assert summary["target_progress_percent"] == 25.0

def test_earning_dashboard_is_available(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    page = client.get("/earnings")
    assert page.status_code == 200
    assert "SINTU AI" in page.text
    assert "/api/earnings/summary" in page.text
