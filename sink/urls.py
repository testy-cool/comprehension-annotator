"""Turning a visited URL into a stable Document identity."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Parameters that identify a campaign rather than a page. Dropping them keeps
# the same article from becoming several Documents.
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "spm",
        "_hsenc",
        "_hsmi",
        "vero_id",
        "yclid",
    }
)

DEFAULT_PORTS = {"http": "80", "https": "443"}


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES)


def normalize_url(url: str) -> str:
    """Collapse the cosmetic differences between two visits to the same page.

    Lowercases the scheme and host, drops the fragment, drops a default port,
    drops tracking parameters, and trims a trailing slash from the path. The
    remaining query is kept and sorted, because for many sites it selects the
    content.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    port = parts.port

    netloc = host
    if port is not None and str(port) != DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    kept = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    )
    query = urlencode(kept)

    return urlunsplit((scheme, netloc, path, query, ""))


def document_id(url: str) -> str:
    """The directory name a Document lives under, derived from its normal form."""
    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
