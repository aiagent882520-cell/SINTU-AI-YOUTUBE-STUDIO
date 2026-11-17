import json

import pytest

from app.youtube_upload import (
    UploadProtocolError,
    parse_acknowledged_offset,
    transfer_resumable_upload,
)


SESSION = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test"


def response(status, headers=None, body=b""):
    return status, headers or {}, body


def test_chunk_upload_uses_server_acknowledged_range_and_completes(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"a" * (256 * 1024 + 17))
    calls = []

    def request(method, url, data, headers):
        calls.append((method, headers["Content-Range"], len(data)))
        if len(calls) == 1:
            return response(308, {"Range": "bytes=0-262143"})
        return response(201, {}, json.dumps({"id": "youtube123"}).encode())

    result = transfer_resumable_upload(path, SESSION, "test-token", request=request,
                                       chunk_size=256 * 1024, sleep=lambda _: None)
    assert result["id"] == "youtube123"
    assert calls == [
        ("PUT", "bytes 0-262143/262161", 262144),
        ("PUT", "bytes 262144-262160/262161", 17),
    ]


def test_network_disconnect_probes_server_before_resuming(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * (256 * 1024 + 4))
    calls = []

    def request(method, url, data, headers):
        calls.append(headers["Content-Range"])
        if len(calls) == 1:
            raise ConnectionError("offline")
        if len(calls) == 2:
            return response(308, {"Range": "bytes=0-262143"})
        return response(200, {}, b'{"id":"recovered"}')

    result = transfer_resumable_upload(path, SESSION, "token", request=request,
                                       chunk_size=256 * 1024, sleep=lambda _: None)
    assert result["id"] == "recovered"
    assert calls == ["bytes 0-262143/262148", "bytes */262148", "bytes 262144-262147/262148"]


@pytest.mark.parametrize("status", [404, 410])
def test_expired_session_is_reported_without_new_upload(tmp_path, status):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"content")
    with pytest.raises(UploadProtocolError) as error:
        transfer_resumable_upload(path, SESSION, "token",
                                  request=lambda *args: response(status), sleep=lambda _: None)
    assert error.value.state == "EXPIRED"


@pytest.mark.parametrize("headers", [
    {"Range": "bytes=1-10"},
    {"Range": "bytes=0-x"},
    {"Range": "bytes=0-999"},
])
def test_malformed_or_out_of_bounds_server_range_is_rejected(headers):
    with pytest.raises(UploadProtocolError):
        parse_acknowledged_offset(headers, 100)


def test_zero_byte_file_is_rejected(tmp_path):
    path = tmp_path / "empty.mp4"
    path.write_bytes(b"")
    with pytest.raises(UploadProtocolError, match="Zero-byte"):
        transfer_resumable_upload(path, SESSION, "token")


def test_changed_source_is_paused_not_resumed(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"a" * (256 * 1024 + 10))
    changed = False

    def progress(offset, state):
        nonlocal changed
        if offset == 256 * 1024 and not changed:
            path.write_bytes(b"replacement")

    def request(*args):
        return response(308, {"Range": "bytes=0-262143"})

    with pytest.raises(UploadProtocolError) as error:
        transfer_resumable_upload(path, SESSION, "token", request=request,
                                  on_progress=progress, chunk_size=256 * 1024)
    assert error.value.state == "PAUSED"

def test_process_restart_probes_server_and_uses_acknowledged_offset(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"r" * (256 * 1024 + 8))
    calls = []

    def request(method, url, data, headers):
        calls.append(headers["Content-Range"])
        if len(calls) == 1:
            return response(308, {"Range": "bytes=0-262143"})
        return response(201, {}, b'{"id":"restart-safe"}')

    result = transfer_resumable_upload(path, SESSION, "token", request=request,
                                       chunk_size=256 * 1024, probe_first=True, sleep=lambda _: None)
    assert result["id"] == "restart-safe"
    assert calls == ["bytes */262152", "bytes 262144-262151/262152"]


def test_process_restart_recovers_completion_from_status_probe(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"abc")
    calls = []

    def request(method, url, data, headers):
        calls.append(headers["Content-Range"])
        return response(200, {}, b'{"id":"already-finished"}')

    result = transfer_resumable_upload(path, SESSION, "token", request=request, probe_first=True)
    assert result["id"] == "already-finished"
    assert calls == ["bytes */3"]


def test_state_machine_rejects_unsafe_transitions():
    from app.youtube_upload import validate_state_transition

    validate_state_transition("PAUSED", "RESUMING")
    validate_state_transition("VERIFYING", "COMPLETED")
    with pytest.raises(UploadProtocolError, match="Invalid upload state transition"):
        validate_state_transition("COMPLETED", "UPLOADING")
    with pytest.raises(UploadProtocolError):
        validate_state_transition("QUEUED", "COMPLETED")


def test_session_uri_rejects_non_google_hosts():
    from app.youtube_upload import validate_session_uri

    with pytest.raises(UploadProtocolError):
        validate_session_uri("https://attacker.example/upload/youtube/session")

def test_no_progress_308_response_has_bounded_retries(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"no-progress")
    calls = []
    with pytest.raises(UploadProtocolError) as error:
        transfer_resumable_upload(
            path, SESSION, "token",
            request=lambda *args: (calls.append(args[3]["Content-Range"]) or response(308)),
            max_attempts=3, sleep=lambda _: None,
        )
    assert error.value.state == "PAUSED"
    assert len(calls) == 3
