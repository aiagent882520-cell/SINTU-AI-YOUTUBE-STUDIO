from app.provider_registry import list_providers, provider_summary

def test_provider_catalog_has_stable_unique_ids_and_sanitized_rows():
    rows = list_providers()
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert len(rows) >= 30
    assert all(row["credential_values_exposed"] is False for row in rows)
    assert all(row["id"] and row["name"] and row["capabilities"] for row in rows)

def test_provider_catalog_can_exclude_external_optional_vendors():
    rows = list_providers(include_external=False)
    assert rows
    assert all(row["status"] != "external_optional" for row in rows)

def test_provider_summary_never_auto_activates_paid_tools():
    summary = provider_summary()
    assert summary["total"] == len(list_providers())
    assert summary["free_first"] is True
    assert summary["paid_auto_activation"] is False
    assert summary["integrated_or_runtime_supported"] < summary["total"]
