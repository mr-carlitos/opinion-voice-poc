"""Bounded native Voice Live signaling; never log transient media credentials."""

import base64
import binascii
import json
import re

from app.graph import ServiceError


def checked_sdp(value, kind):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 131072:
            raise ValueError()
        decoded = json.loads(base64.b64decode(value, validate=True))
        if not isinstance(decoded, dict) or set(decoded) != {"type", "sdp"}:
            raise ValueError()
        sdp = decoded["sdp"]
        if decoded["type"] != kind or not isinstance(sdp, str):
            raise ValueError()
        if not sdp.startswith("v=0") or len(sdp) > 96000 or "\x00" in sdp:
            raise ValueError()
        if "m=audio " not in sdp or "m=video " not in sdp:
            raise ValueError()
    except (ValueError, TypeError, binascii.Error):
        raise ServiceError("Ungueltige Avatar-Signalisierung.") from None
    return value


def checked_ice(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ServiceError("Avatar-ICE-Konfiguration fehlt.")
    result = []
    for server in value:
        if not isinstance(server, dict):
            raise ServiceError("Ungueltige Avatar-ICE-Konfiguration.")
        urls = server.get("urls")
        if isinstance(urls, str):
            urls = [urls]
        if not isinstance(urls, list) or not 1 <= len(urls) <= 8:
            raise ServiceError("Ungueltige Avatar-ICE-Adressen.")
        if any(
            not isinstance(url, str)
            or not re.fullmatch(
                r"(?:stun|turn|turns):[A-Za-z0-9.:\-\[\]]+(?:\?transport=(?:udp|tcp))?", url
            )
            or len(url) > 2048
            for url in urls
        ):
            raise ServiceError("Ungueltige Avatar-ICE-Adresse.")
        clean = {"urls": urls}
        for key in ("username", "credential"):
            value = server.get(key, "")
            if not isinstance(value, str) or len(value) > 4096:
                raise ServiceError("Ungueltige Avatar-ICE-Zugangsdaten.")
            clean[key] = value
        result.append(clean)
    return result
