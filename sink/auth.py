"""The shared secret between the extension and the sink.

The sink listens on the loopback interface, which any page you visit can also
reach. A token in a custom header keeps them out: sending a custom header forces
a CORS preflight, and the sink answers that preflight only for the extension.
"""

from __future__ import annotations

import secrets
from pathlib import Path

HEADER = "X-Annotator-Token"
EXTENSION_ORIGIN = r"^chrome-extension://[a-p]{32}$"


def ensure_token(path: Path) -> str:
    """Read the token, generating it on first run."""
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    return token


def matches(expected: str, presented: str | None) -> bool:
    if not presented:
        return False
    return secrets.compare_digest(expected, presented)
