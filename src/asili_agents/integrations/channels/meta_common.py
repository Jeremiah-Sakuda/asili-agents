"""Shared helpers for Meta-platform connectors (Instagram + WhatsApp)."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping

META_SIGNATURE_HEADER = "x-hub-signature-256"


def verify_meta_signature(
    raw_body: bytes, headers: Mapping[str, str], app_secret: str | None
) -> bool:
    """Verify Meta's ``X-Hub-Signature-256`` over the raw request body.

    Fails closed: no app secret or missing/!malformed header => False.
    """
    if not app_secret:
        return False
    # Header lookup is case-insensitive; callers pass a lower-cased mapping.
    provided = headers.get(META_SIGNATURE_HEADER) or headers.get("X-Hub-Signature-256")
    if not provided or not provided.startswith("sha256="):
        return False
    expected = (
        "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(provided, expected)
