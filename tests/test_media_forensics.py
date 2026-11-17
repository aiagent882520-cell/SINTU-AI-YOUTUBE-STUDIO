from scripts.media_forensics import parse_black_intervals, redact_secrets


def test_black_interval_parser_preserves_time_ranges():
    assert parse_black_intervals(
        "black_start:0 black_end:4.041667 black_start:7.0 black_end:8.0"
    ) == [[0.0, 4.041667], [7.0, 8.0]]


def test_forensic_output_redacts_bearer_tokens_and_session_urls():
    value = (
        "Authorization: Bearer abc.def.secret "
        "access_token=private-value "
        "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=private-session"
    )
    redacted = redact_secrets(value)
    assert "abc.def.secret" not in redacted
    assert "private-value" not in redacted
    assert "private-session" not in redacted
    assert "[REDACTED]" in redacted
    assert "[REDACTED_GOOGLE_UPLOAD_SESSION]" in redacted
