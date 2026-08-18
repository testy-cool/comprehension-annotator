"""Where the sink keeps things, and how it is reached."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8790

REPO_ROOT = Path(__file__).resolve().parent.parent


def library_root() -> Path:
    override = os.environ.get("ANNOTATOR_LIBRARY")
    return Path(override).expanduser() if override else REPO_ROOT / "library"


def token_path() -> Path:
    override = os.environ.get("ANNOTATOR_TOKEN_FILE")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "comprehension-annotator" / "token"
