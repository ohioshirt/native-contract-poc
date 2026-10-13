"""Strict version-1 HTTP envelopes for the standalone integration harness."""

from __future__ import annotations

import json
import re


MAX_BODY_BYTES = 16 * 1024
MAX_SIGNED64 = (1 << 63) - 1
_DECIMAL_ID = re.compile(r"[1-9][0-9]{0,18}\Z", re.ASCII)
_TOKEN = re.compile(r"demo-([AB])-v([0-9]+)\Z", re.ASCII)


class WireError(ValueError):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.code = code


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WireError(400, "duplicate_key", f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(token):
    raise ValueError(f"invalid JSON constant {token}")


def parse_json_object(body: bytes, *, limit: int = MAX_BODY_BYTES) -> dict:
    if not isinstance(body, bytes):
        raise WireError(400, "invalid_body", "request body must be bytes")
    if len(body) > limit:
        raise WireError(413, "body_too_large", "request body exceeds the frozen size limit")
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except WireError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WireError(400, "invalid_json", "request body is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise WireError(400, "invalid_envelope", "request body must be a JSON object")
    return value


def _ascii_label(value, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value.isascii()
        and all("!" <= character <= "~" for character in value)
        and not any(character.isspace() for character in value)
    )


def parse_refresh(body: bytes) -> dict:
    """Parse a refresh request, preserving requestId as exact decimal text."""
    value = parse_json_object(body)
    required = {"version", "runId", "requestTag", "requestId", "account", "refreshToken"}
    if set(value) != required:
        raise WireError(400, "invalid_envelope", "refresh envelope must contain exactly the version-1 fields")
    if type(value["version"]) is not int or value["version"] != 1:
        raise WireError(400, "invalid_version", "version must be integer 1")
    if not _ascii_label(value["runId"], 128):
        raise WireError(400, "invalid_run_id", "runId must be a short printable ASCII label")
    if not _ascii_label(value["requestTag"], 256):
        raise WireError(400, "invalid_request_tag", "requestTag must be a short printable ASCII label")
    request_id = value["requestId"]
    if not isinstance(request_id, str) or not _DECIMAL_ID.fullmatch(request_id) or int(request_id) > MAX_SIGNED64:
        raise WireError(400, "invalid_request_id", "requestId must be a canonical positive signed64 decimal string")
    account = value["account"]
    if account not in {"A", "B"}:
        raise WireError(400, "invalid_account", "account must be A or B")
    refresh_token = value["refreshToken"]
    match = _TOKEN.fullmatch(refresh_token) if isinstance(refresh_token, str) and len(refresh_token) <= 64 else None
    if not match or match.group(1) != account or int(match.group(2)) > MAX_SIGNED64:
        raise WireError(400, "invalid_refresh_token", "refreshToken must match the synthetic account/version")
    return value
