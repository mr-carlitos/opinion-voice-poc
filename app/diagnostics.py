"""Bounded, redacted local diagnostics. Never serialize raw service/browser events."""

import json
import logging
import math
import os
import re
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.config import ROOT

LOG_PATH = ROOT / ".local/diagnostics.jsonl"
MAX_BYTES = 2_000_000
_lock = threading.Lock()
logger = logging.getLogger(__name__)


def safe_text(value, limit=1600):
    if not isinstance(value, str):
        return ""
    value = value[:12000]
    if re.search(r"(?:v=0[\r\n]|a=(?:ice-pwd|ice-ufrag|fingerprint|candidate):)", value):
        return "[SDP omitted]"
    value = re.sub(r"(?:https?|wss?|turns?|stun):[^\s<>\"']+", "[URL omitted]", value)
    value = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", value)
    value = re.sub(
        r"(?i)\b(authorization|token|secret|password|credential|api[-_]?key)"
        r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1=[redacted]",
        value,
    )
    value = re.sub(
        r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+\b", "[JWT omitted]", value
    )
    value = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP omitted]", value)
    value = re.sub(r"\b(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.]+\b", "[IP omitted]", value)
    value = re.sub(r"\b[A-Za-z0-9+/_=-]{100,}\b", "[encoded payload omitted]", value)
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return value[:limit]


def browser_details(value):
    """Allow only state, timing, codec and numeric ICE failure evidence."""
    if not isinstance(value, dict):
        return {}
    clean = {}
    for key in (
        "stage",
        "error_name",
        "error_message",
        "connection_state",
        "ice_connection_state",
        "ice_gathering_state",
        "signaling_state",
        "stats_error",
    ):
        if isinstance(value.get(key), str):
            clean[key] = safe_text(value[key], 1600 if key == "error_message" else 160)
    for key in ("elapsed_ms", "audio_tracks", "video_tracks", "frames_decoded", "bytes_received"):
        number = value.get(key)
        if type(number) in (int, float) and math.isfinite(number) and 0 <= number <= 1e15:
            clean[key] = number
    codecs = value.get("video_codecs")
    if isinstance(codecs, list):
        clean["video_codecs"] = [
            c
            for c in codecs[:20]
            if isinstance(c, str) and re.fullmatch(r"video/[A-Za-z0-9.-]{1,30}", c)
        ]
    for key in ("offer_sent", "answer_received", "h264_supported"):
        if isinstance(value.get(key), bool):
            clean[key] = value[key]
    errors = value.get("ice_errors")
    if isinstance(errors, list):
        clean["ice_errors"] = []
        for item in errors[:8]:
            if not isinstance(item, dict):
                continue
            record = {"text": safe_text(item.get("text"), 500)}
            code = item.get("code")
            if type(code) is int and 0 <= code <= 9999:
                record["code"] = code
            if item.get("protocol") in ("stun", "turn", "turns"):
                record["protocol"] = item["protocol"]
            clean["ice_errors"].append(record)
    return clean


def service_details(value):
    if not isinstance(value, dict):
        return {}
    clean = {}
    for key in ("code", "type", "message", "param", "event_id", "request_id", "request-id"):
        if isinstance(value.get(key), str):
            clean[key] = safe_text(value[key], 2400 if key == "message" else 160)
    for key in ("innerError", "innererror", "details"):
        detail = value.get(key)
        if isinstance(detail, dict):
            clean[key] = {
                k: safe_text(detail[k])
                for k in ("code", "message", "request-id", "request_id")
                if isinstance(detail.get(k), str)
            }
        elif isinstance(detail, list):
            clean[key] = [
                {
                    k: safe_text(item[k])
                    for k in ("code", "message", "param")
                    if isinstance(item.get(k), str)
                }
                for item in detail[:5]
                if isinstance(item, dict)
            ]
    return clean


def record_diagnostic(event, *, browser=None, service=None, error=None, **metadata):
    diagnostic_id = uuid4().hex[:12]
    entry = {
        "time": datetime.now(UTC).isoformat(),
        "diagnostic_id": diagnostic_id,
        "event": safe_text(event, 80),
    }
    for key in (
        "reason",
        "phase",
        "source",
        "service_session_id",
        "service_event_id",
        "voice_api_version",
        "model",
        "delivery_mode",
    ):
        if key in metadata:
            entry[key] = safe_text(metadata[key], 160)
    if browser is not None:
        entry["browser"] = browser_details(browser)
    if service is not None:
        entry["service"] = service_details(service)
    if error is not None:
        entry["exception_type"] = type(error).__name__
        entry["exception_message"] = safe_text(str(error))
        entry["frames"] = [
            {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(error.__traceback__)[-12:]
        ]
    serialized = json.dumps(entry, ensure_ascii=False)
    logger.warning("Diagnostic %s: %s", diagnostic_id, serialized)
    try:
        with _lock:
            LOG_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if LOG_PATH.exists() and LOG_PATH.stat().st_size >= MAX_BYTES:
                LOG_PATH.replace(LOG_PATH.with_suffix(".previous.jsonl"))
            fd = os.open(LOG_PATH, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(serialized + "\n")
    except OSError as failure:
        logger.error(
            "Diagnostic %s could not be saved locally (%s).", diagnostic_id, type(failure).__name__
        )
    return diagnostic_id
