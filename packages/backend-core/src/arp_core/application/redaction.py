from __future__ import annotations

from collections.abc import Mapping
from typing import Any


REDACTED_VALUE = "[REDACTED]"
_SENSITIVE_KEY_PARTS = ("api_key", "apikey", "authorization", "credential", "password", "secret", "token")


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_payload(value: Any) -> Any:
    """Return a JSON-compatible copy with conventional secret fields removed.

    This intentionally runs at every trace/audit serialization boundary so legacy
    callers cannot accidentally bypass a route-level sanitizer.
    """
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED_VALUE if is_sensitive_key(str(key)) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item) for item in value]
    return value
