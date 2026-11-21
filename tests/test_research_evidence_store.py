import sqlite3

import pytest

from app.documentary_research import validate_documentary_evidence_for_production
from app.research_evidence_store import get_research_evidence, save_research_evidence


def _package():
    return {
        "schema_version": 1,
        "topic": "भारत का इतिहास",
        "researched_at": "2026-11-21T10:00:00+05:30",
        "sources": [
            {"id": "a", "title": "Primary record", "publisher": "Archive A",
             "url": "https://archive-a.example/record", "accessed_at": "2026-11-21",
             "published_at": None, "source_type": "primary"},
            {"id": "b", "title": "Academic paper", "publisher": "University B",
             "url": "https://university-b.example/paper", "accessed_at": "2026-11-21",
             "published_at": "2020-01-01", "source_type": "academic"},
        ],
        "claims": [
            {"id": "claim", "text": "एक सत्यापन योग्य ऐतिहासिक दावा।",
             "claim_type": "factual", "status": "corroborated",
             "source_ids": ["a", "b"], "evidence_notes": "दोनों स्रोतों की संपादकीय समीक्षा आवश्यक है।"}
        ],
    }


def test_store_round_trips_package_and_validation_with_digest(tmp_path):
    package = _package()
    validation = validate_documentary_evidence_for_production(package)
    result = save_research_evidence(tmp_path / "main.sqlite3", "a" * 32, "alice", package, validation)
    assert result["sha256"] == validation["sha256"]
    assert get_research_evidence(tmp_path / "main.sqlite3", "a" * 32, "alice")["package"] == package


def test_store_is_owner_scoped(tmp_path):
    package = _package()
    validation = validate_documentary_evidence_for_production(package)
    db = tmp_path / "main.sqlite3"
    save_research_evidence(db, "b" * 32, "alice", package, validation)
    assert get_research_evidence(db, "b" * 32, "bob") is None


def test_store_refuses_invalid_or_digest_mismatched_evidence(tmp_path):
    package = _package()
    validation = validate_documentary_evidence_for_production(package)
    validation["valid"] = False
    with pytest.raises(ValueError):
        save_research_evidence(tmp_path / "main.sqlite3", "c" * 32, "alice", package, validation)
    validation["valid"] = True
    validation["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        save_research_evidence(tmp_path / "main.sqlite3", "d" * 32, "alice", package, validation)


def test_store_rejects_duplicate_run_evidence_without_overwriting(tmp_path):
    package = _package()
    validation = validate_documentary_evidence_for_production(package)
    db = tmp_path / "main.sqlite3"
    save_research_evidence(db, "e" * 32, "alice", package, validation)
    with pytest.raises(sqlite3.IntegrityError):
        save_research_evidence(db, "e" * 32, "alice", package, validation)
    assert get_research_evidence(db, "e" * 32, "alice")["package"] == package
