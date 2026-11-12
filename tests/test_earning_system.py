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



def test_earning_record_can_be_updated_and_missing_record_returns_404(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    created = client.post("/api/earnings/records", json={
        "kind": "income", "source": "affiliate", "title": "Draft payout",
        "amount": 100, "currency": "INR", "status": "pending",
        "record_date": "2026-11-10"
    })
    record_id = created.json()["record"]["id"]
    updated = client.patch(f"/api/earnings/records/{record_id}", json={
        "kind": "income", "source": "affiliate", "title": "Final payout",
        "amount": 250, "currency": "INR", "status": "received",
        "record_date": "2026-11-11", "reference": "INV-11", "notes": "Paid"
    })
    assert updated.status_code == 200
    assert updated.json()["record"]["title"] == "Final payout"
    assert updated.json()["record"]["amount"] == 250
    assert updated.json()["record"]["notes"] == "Paid"
    assert client.patch("/api/earnings/records/999999", json={
        "kind": "income", "source": "affiliate", "title": "Missing",
        "amount": 1, "record_date": "2026-11-11"
    }).status_code == 404


def test_earning_record_month_filter_rejects_invalid_month(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    assert client.get("/api/earnings/records?month=2026-99").status_code == 400
    assert client.get("/api/earnings/records?month=2026-ab").status_code == 400


def test_csv_export_neutralizes_spreadsheet_formula_injection(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    response = client.post("/api/earnings/records", json={
        "kind": "income", "source": "affiliate", "title": "=HYPERLINK(\"https://evil.example\")",
        "amount": 50, "currency": "INR", "status": "received",
        "record_date": "2026-11-12", "reference": "@SUM(1,1)", "notes": "+cmd|' /C calc'!A0"
    })
    assert response.status_code == 201
    exported = client.get("/api/earnings/export.csv").text
    assert "'=HYPERLINK" in exported
    assert "'@SUM" in exported
    assert "'+cmd" in exported


def test_earning_dashboard_has_record_management_controls(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    page = client.get("/earnings").text
    assert "data-edit-id" in page
    assert "data-delete-id" in page
    assert "recordKindFilter" in page
    assert "cancelEdit" in page


def test_earning_dashboard_includes_official_youtube_analytics_panel(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    page = client.get("/earnings").text
    assert 'id="youtubeAnalyticsPanel"' in page
    assert 'id="youtubeAnalyticsLoad"' in page
    assert 'id="youtubeAnalyticsMetrics"' in page
    assert 'id="youtubeAnalyticsRevenue"' in page
    assert 'id="youtubeAnalyticsDailyChart"' in page
    assert 'id="youtubeAnalyticsRevenueComparison"' in page
    assert "renderDailyAnalytics" in page
    assert "Ledger में दर्ज प्राप्त YouTube Ads रकम" in page
    assert '/api/admin/youtube/analytics' in page
    assert "अनुमानित रकम वास्तविक भुगतान नहीं है" in page
    assert "YouTube डेटा लोड करें" in page



def test_net_confirmed_excludes_estimated_and_pending_expenses(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    records = [
        ("income", "received", 1000, "Received income"),
        ("expense", "confirmed", 100, "Confirmed expense"),
        ("expense", "estimated", 300, "Estimated expense"),
        ("expense", "pending", 200, "Pending expense"),
        ("expense", "cancelled", 999, "Cancelled expense"),
    ]
    for kind, status, amount, title in records:
        response = client.post("/api/earnings/records", json={
            "kind": kind, "source": "other", "title": title, "amount": amount,
            "currency": "INR", "status": status, "record_date": "2026-11-12"
        })
        assert response.status_code == 201
    summary = client.get("/api/earnings/summary?month=2026-11").json()
    assert summary["expenses"]["INR"] == 600
    assert summary["confirmed_expenses"]["INR"] == 100
    assert summary["estimated_expenses"]["INR"] == 300
    assert summary["pending_expenses"]["INR"] == 200
    assert summary["net_confirmed"]["INR"] == 900



def test_earning_record_rejects_blank_title_and_normalizes_source(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    payload = {
        "kind": "income", "source": "affiliate", "title": "   ",
        "amount": 10, "currency": "INR", "status": "received",
        "record_date": "2026-11-12"
    }
    assert client.post("/api/earnings/records", json=payload).status_code == 422
    payload["title"] = "  Affiliate payment  "
    payload["source"] = " affiliate "
    created = client.post("/api/earnings/records", json=payload)
    assert created.status_code == 201
    assert created.json()["record"]["title"] == "Affiliate payment"
    assert created.json()["record"]["source"] == "affiliate"


def test_earning_record_rejects_unknown_source_at_validation(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    response = client.post("/api/earnings/records", json={
        "kind": "income", "source": "untrusted-category", "title": "Payment",
        "amount": 10, "currency": "INR", "status": "received",
        "record_date": "2026-11-12"
    })
    assert response.status_code == 422


def test_earning_record_filters_and_pagination(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    samples = [
        ("affiliate", "received", "2026-11-01", "Affiliate paid"),
        ("youtube_ads", "estimated", "2026-11-05", "YouTube estimate"),
        ("affiliate", "pending", "2026-11-10", "Affiliate pending"),
    ]
    for source, status, record_date, title in samples:
        response = client.post("/api/earnings/records", json={
            "kind": "income", "source": source, "title": title, "amount": 100,
            "currency": "INR", "status": status, "record_date": record_date
        })
        assert response.status_code == 201

    filtered = client.get(
        "/api/earnings/records?kind=income&source=affiliate&status=received"
        "&start_date=2026-11-01&end_date=2026-11-09&limit=1"
    )
    assert filtered.status_code == 200
    data = filtered.json()
    assert data["total"] == 1
    assert data["records"][0]["title"] == "Affiliate paid"
    assert data["has_more"] is False

    page = client.get("/api/earnings/records?month=2026-11&limit=1&offset=1")
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["records"]) == 1
    assert page.json()["offset"] == 1


def test_earning_record_filters_reject_invalid_values_and_date_order(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    assert client.get("/api/earnings/records?status=unknown").status_code == 400
    assert client.get("/api/earnings/records?source=unknown").status_code == 400
    assert client.get(
        "/api/earnings/records?start_date=2026-11-20&end_date=2026-11-01"
    ).status_code == 400


def test_earning_dashboard_exposes_record_filters(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    page = client.get("/earnings").text
    for control in ["recordStatusFilter", "recordSourceFilter", "recordStartDate", "recordEndDate"]:
        assert f'id="{control}"' in page



def test_earning_record_can_be_fetched_by_id(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    created = client.post('/api/earnings/records', json={
        'kind': 'income', 'source': 'affiliate', 'title': 'Older payout',
        'amount': 75, 'currency': 'INR', 'status': 'received',
        'record_date': '2025-01-10'
    })
    record_id = created.json()['record']['id']
    fetched = client.get('/api/earnings/records/' + str(record_id))
    assert fetched.status_code == 200
    assert fetched.json()['record']['title'] == 'Older payout'
    assert client.get('/api/earnings/records/999999').status_code == 404
