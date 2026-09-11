import json

import pytest

from app import diagnostics


@pytest.fixture(autouse=True)
def local_log(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "LOG_PATH", tmp_path / "diagnostics.jsonl")


def test_diagnostic_records_details_but_never_raw_signaling_or_credentials(caplog):
    diagnostic_id = diagnostics.record_diagnostic(
        "avatar_failure",
        phase="connecting",
        reason="peer_failed",
        service_session_id="sess_test",
        browser={
            "stage": "set_remote_description",
            "error_name": "OperationError",
            "error_message": "Failed video negotiation token=secretvalue https://host/path?secret=123",
            "connection_state": "failed",
            "ice_connection_state": "failed",
            "offer_sent": True,
            "answer_received": True,
            "video_codecs": ["video/H264", "not-a-codec"],
            "ice_errors": [
                {
                    "code": 701,
                    "text": "Unreachable 192.168.2.3 turn:relay.example:3478",
                    "protocol": "turn",
                    "credential": "NEVER_LOG",
                }
            ],
            "sdp": "NEVER_LOG",
            "ice_servers": [{"credential": "NEVER_LOG"}],
            "transcript": "NEVER_LOG",
        },
        service={
            "code": "avatar_service_internal_error",
            "message": "Failed to set remote video description",
            "event_id": "event_test",
            "details": [{"code": "nested", "secret": "NEVER_LOG"}],
            "server_sdp": "NEVER_LOG",
        },
    )
    text = diagnostics.LOG_PATH.read_text()
    record = json.loads(text)
    assert record["diagnostic_id"] == diagnostic_id
    assert record["browser"]["ice_errors"][0]["code"] == 701
    assert record["service"]["message"] == "Failed to set remote video description"
    for forbidden in ("NEVER_LOG", "secretvalue", "192.168.2.3", "relay.example", "https://host"):
        assert forbidden not in text + caplog.text
    assert record["browser"]["video_codecs"] == ["video/H264"]
    assert diagnostics.LOG_PATH.stat().st_mode & 0o777 == 0o600


def test_sdp_and_long_payloads_are_not_written():
    assert diagnostics.safe_text("Operation failed: v=0\r\na=ice-pwd:secret") == "[SDP omitted]"
    assert diagnostics.safe_text("x" * 200) == "[encoded payload omitted]"
    assert "rawsecret" not in diagnostics.safe_text("Bearer rawsecret")
    assert "password123" not in diagnostics.safe_text('password="password123"')


def test_exception_keeps_safe_message_and_frames_without_source_or_locals():
    try:
        raise RuntimeError("Negotiation failed credential=supersecret")
    except RuntimeError as error:
        diagnostics.record_diagnostic("voice_bridge_failure", error=error)
    record = json.loads(diagnostics.LOG_PATH.read_text())
    assert record["exception_type"] == "RuntimeError"
    assert "supersecret" not in record["exception_message"]
    assert record["frames"][-1]["file"] == "test_diagnostics.py"
    assert set(record["frames"][-1]) == {"file", "line", "function"}


def test_log_rotates_and_errors_are_visible(monkeypatch, caplog):
    monkeypatch.setattr(diagnostics, "MAX_BYTES", 1)
    first = diagnostics.record_diagnostic("first")
    second = diagnostics.record_diagnostic("second")
    assert first in diagnostics.LOG_PATH.with_suffix(".previous.jsonl").read_text()
    assert second in diagnostics.LOG_PATH.read_text()
    monkeypatch.setattr(
        diagnostics.os, "open", lambda *args: (_ for _ in ()).throw(PermissionError())
    )
    third = diagnostics.record_diagnostic("third")
    assert third in caplog.text and "could not be saved" in caplog.text


def test_bad_or_excessive_browser_fields_are_bounded():
    result = diagnostics.browser_details(
        {
            "ice_errors": [{"code": 701, "text": "error"}] * 100,
            "video_codecs": ["video/H264"] * 100,
            "elapsed_ms": float("inf"),
            "audio_tracks": -1,
            "offer_sent": "yes",
            "password": "secret",
        }
    )
    assert len(result["ice_errors"]) == 8
    assert len(result["video_codecs"]) == 20
    assert "elapsed_ms" not in result and "audio_tracks" not in result
    assert "offer_sent" not in result and "password" not in result
