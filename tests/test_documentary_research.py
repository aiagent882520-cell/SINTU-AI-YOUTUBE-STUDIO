import copy
from app.documentary_research import validate_research_package


def package():
    return {
        "schema_version": 1,
        "topic": "भारतीय स्वतंत्रता आंदोलन",
        "researched_at": "2026-11-21T12:00:00+05:30",
        "sources": [
            {"id": "src-a", "title": "Archive record", "publisher": "National Archives",
             "url": "https://archives.example.org/record/1", "published_at": None,
             "accessed_at": "2026-11-21", "source_type": "primary",
             "evidence_excerpt": "Archival record reference."},
            {"id": "src-b", "title": "Research paper", "publisher": "University Research",
             "url": "https://university.example.org/paper/2", "published_at": "2020-01-01",
             "accessed_at": "2026-11-21", "source_type": "academic"},
        ],
        "claims": [
            {"id": "claim-1", "text": "A documented historical event occurred.",
             "claim_type": "factual", "status": "corroborated",
             "source_ids": ["src-a", "src-b"],
             "evidence_notes": "Both records are cited for editorial review."}
        ],
    }


def test_valid_package_passes_structural_validation_with_explicit_boundary():
    result = validate_research_package(package())
    assert result["valid"] is True
    assert result["claim_count"] == 1
    assert result["source_count"] == 2
    assert "does not browse" in result["acceptance_boundary"]
    assert any("not proof of source independence" in item for item in result["warnings"])


def test_non_object_package_fails_closed():
    result = validate_research_package(["not", "an", "object"])
    assert result["valid"] is False
    assert result["errors"]


def test_factual_claim_without_sources_cannot_be_marked_supported():
    data = package()
    data["claims"][0]["source_ids"] = []
    data["claims"][0]["status"] = "single_source"
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any("must cite at least one source" in item for item in result["errors"])


def test_unverified_factual_claim_is_allowed_but_warned():
    data = package()
    data["claims"][0]["source_ids"] = []
    data["claims"][0]["status"] = "unverified"
    result = validate_research_package(data)
    assert result["valid"] is True
    assert any("must not be narrated as established fact" in item for item in result["warnings"])


def test_corroboration_requires_two_named_publishers():
    data = package()
    data["sources"][1]["publisher"] = data["sources"][0]["publisher"]
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any("at least two named publishers" in item for item in result["errors"])


def test_source_ids_must_exist_and_be_unique():
    data = package()
    data["claims"][0]["source_ids"] = ["src-a", "src-missing", "src-a"]
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any("unknown source IDs" in item for item in result["errors"])
    assert any("duplicate source reference" in item for item in result["errors"])


def test_claim_ids_and_source_ids_must_be_unique():
    data = package()
    data["claims"].append(copy.deepcopy(data["claims"][0]))
    data["sources"].append(copy.deepcopy(data["sources"][0]))
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any("duplicate identifier" in item for item in result["errors"])


def test_private_or_credential_bearing_source_urls_are_rejected():
    for url in ("file:///etc/passwd", "http://127.0.0.1/admin",
                "http://192.168.1.10/source", "https://user:pass@example.org/a",
                "http://localhost/private"):
        data = package()
        data["sources"][0]["url"] = url
        assert validate_research_package(data)["valid"] is False


def test_invalid_dates_and_missing_timezone_are_rejected():
    data = package()
    data["researched_at"] = "2026-11-21T12:00:00"
    data["sources"][0]["accessed_at"] = "yesterday"
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any("researched_at" in item for item in result["errors"])
    assert any("accessed_at" in item for item in result["errors"])


def test_cited_claim_requires_editorial_evidence_notes():
    data = package()
    data["claims"][0]["evidence_notes"] = ""
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any("evidence_notes" in item for item in result["errors"])


def test_disputed_and_single_source_claims_are_warned():
    data = package()
    data["claims"][0]["status"] = "disputed"
    data["claims"][0]["source_ids"] = ["src-a"]
    result = validate_research_package(data)
    assert result["valid"] is True
    assert any("disputed factual claim" in item for item in result["warnings"])


def test_limits_and_schema_version_are_enforced():
    data = package()
    data["schema_version"] = "1"
    data["topic"] = " "
    data["claims"] = []
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any("schema_version" in item for item in result["errors"])
    assert any("topic" in item for item in result["errors"])
    assert any("claims" in item for item in result["errors"])


def test_malformed_enum_types_fail_without_raising_type_error():
    data = package()
    data["claims"][0]["claim_type"] = []
    data["claims"][0]["status"] = {}
    data["sources"][0]["source_type"] = []
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any("claim_type" in item for item in result["errors"])
    assert any("status" in item for item in result["errors"])
    assert any("source_type" in item for item in result["errors"])


def test_boolean_is_not_accepted_as_schema_version_one():
    data = package()
    data["schema_version"] = True
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any("schema_version" in item for item in result["errors"])


def test_invalid_url_port_is_rejected():
    data = package()
    data["sources"][0]["url"] = "https://example.org:99999/source"
    result = validate_research_package(data)
    assert result["valid"] is False
    assert any(".url:" in item for item in result["errors"])
