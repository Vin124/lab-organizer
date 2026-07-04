"""Optional shared-token gate. Disabled entirely unless AUTH_TOKEN is set.

Uses HTTP Basic auth: the browser prompts natively and caches the credentials,
so the frontend needs zero changes. Any username is accepted; the password is
compared in constant time to AUTH_TOKEN. /healthz stays open so liveness probes
and SSH-tunnel health checks keep working without credentials.

This is intentionally a thin seam, not a full auth system (see CLAUDE.md: no user
accounts in v1). For multi-user/network exposure, terminate auth at a reverse proxy.
"""
from __future__ import annotations

import base64
import binascii
import secrets

# Only /healthz is open when auth is on. NOTE: do NOT add "/static" or "/" here —
# the frontend assets must stay behind the gate (the browser caches Basic creds).
_EXEMPT_PATHS = frozenset({"/healthz"})


def is_exempt(path: str) -> bool:
    """Paths reachable without credentials even when auth is enabled."""
    return path in _EXEMPT_PATHS


def check_basic_auth(auth_header: str | None, token: str) -> bool:
    """True iff `auth_header` carries Basic creds whose password matches `token`."""
    if not token:  # empty token = auth not configured; never authenticate
        return False
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError):
        return False
    _, sep, password = decoded.partition(":")
    if not sep:  # malformed: no colon separating user:pass
        return False
    return secrets.compare_digest(password, token)
