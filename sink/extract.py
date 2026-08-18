"""Deriving readable text from a captured Snapshot.

The extension stores the DOM as rendered and nothing else. Everything a reader
or a later rewrite pass actually consumes is derived here, so the extraction can
be improved and re-run over the whole library without revisiting a single page.
"""

from __future__ import annotations

import re
from html import unescape

EXTRACTOR = "trafilatura"

_SCRIPTISH = re.compile(r"<(script|style|noscript|template)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]+")


def _plain_text(html: str) -> str:
    """A last resort when the readability pass finds no article.

    Short pages, single-purpose app screens and documentation fragments often
    have no prose body to detect, and returning nothing for them would lose the
    only thing worth keeping.
    """
    stripped = _SCRIPTISH.sub(" ", html)
    stripped = re.sub(r"<(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", stripped, flags=re.I)
    text = unescape(_TAG.sub("", stripped))
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANKS.sub("\n\n", text).strip()


def extract(html: str, url: str | None = None) -> tuple[str, dict]:
    """Return the readable markdown for a Snapshot and what we know about it."""
    markdown = None
    meta: dict = {"extractor": EXTRACTOR, "fallback": False, "title": None, "byline": None}

    try:
        import trafilatura

        markdown = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            favor_recall=True,
        )
        try:
            document = trafilatura.extract_metadata(html, default_url=url)
        except Exception:
            document = None
        if document is not None:
            meta["title"] = getattr(document, "title", None)
            meta["byline"] = getattr(document, "author", None)
            meta["published"] = getattr(document, "date", None)
        meta["extractor_version"] = getattr(trafilatura, "__version__", None)
    except Exception as exc:  # extraction must never lose a capture
        meta["error"] = f"{type(exc).__name__}: {exc}"

    if not markdown or not markdown.strip():
        markdown = _plain_text(html)
        meta["fallback"] = True
        meta["extractor"] = "plaintext"

    meta["word_count"] = len(markdown.split())
    meta["char_count"] = len(markdown)
    return markdown, meta
