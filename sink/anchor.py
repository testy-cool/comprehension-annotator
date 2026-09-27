"""Finding an annotated passage inside stored text.

The extension resolves anchors against a live DOM. The sink has to do the same
job against what it captured, so the scoring rules here deliberately mirror
extension/anchor.js: quote first, surrounding words to choose between repeats,
stored position only to break a remaining tie.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CONTEXT = 32
_WHITESPACE = re.compile(r"[\s ]+")


@dataclass
class Match:
    start: int
    end: int
    exact: bool
    ambiguous: bool


def collapse(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def _collapsed_with_map(text: str) -> tuple[str, list[int]]:
    """The text with runs of whitespace flattened, and where each character came from."""
    out: list[str] = []
    origin: list[int] = []
    previous_was_space = False
    for position, character in enumerate(text):
        if _WHITESPACE.match(character):
            if previous_was_space:
                continue
            out.append(" ")
            origin.append(position)
            previous_was_space = True
        else:
            out.append(character)
            origin.append(position)
            previous_was_space = False
    return "".join(out), origin


# What the extension quotes is the page's text nodes run together, so a
# passage that crosses two list items arrives as "MVPsComfort", while the
# stored markdown holds "MVPs\n- Comfort". The last resort compares the two
# with whitespace and markdown syntax taken out of both.
_MARKUP = re.compile(
    r"(?m)^[ \t]*(?:[-*+]|\d+[.)]|#{1,6}|>)[ \t]+"  # list, heading and quote markers
    r"|\*\*|__|`"  # emphasis and code
    r"|\]\([^)\s]*\)|\["  # link syntax around the link's words
)


def _skeleton_with_map(text: str) -> tuple[str, list[int]]:
    """The text with whitespace and markdown syntax removed, and where each character came from."""
    dropped = [False] * len(text)
    for found in _MARKUP.finditer(text):
        for position in range(found.start(), found.end()):
            dropped[position] = True
    out: list[str] = []
    origin: list[int] = []
    for position, character in enumerate(text):
        if dropped[position] or _WHITESPACE.match(character):
            continue
        out.append(character)
        origin.append(position)
    return "".join(out), origin


def _occurrences(haystack: str, needle: str, limit: int = 200) -> list[int]:
    if not needle:
        return []
    found = []
    at = haystack.find(needle)
    while at != -1 and len(found) < limit:
        found.append(at)
        at = haystack.find(needle, at + 1)
    return found


def _common_suffix(a: str, b: str) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _common_prefix(a: str, b: str) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[n] == b[n]:
        n += 1
    return n


def resolve(text: str, annotation: dict) -> Match | None:
    """Where this annotation points in this text, or None if the passage is gone."""
    quote = annotation.get("quote") or ""
    if not quote:
        return None

    starts = _occurrences(text, quote)
    if starts:
        spans = [(at, at + len(quote)) for at in starts]
        exact = True
    else:
        flat, origin = _collapsed_with_map(text)
        wanted = collapse(quote)
        flat_starts = _occurrences(flat, wanted)
        if not flat_starts:
            flat, origin = _skeleton_with_map(text)
            wanted = _WHITESPACE.sub("", quote)
            flat_starts = _occurrences(flat, wanted)
        if not flat_starts:
            return None
        exact = False
        spans = [
            (origin[at], origin[min(at + len(wanted) - 1, len(origin) - 1)] + 1)
            for at in flat_starts
        ]

    prefix = annotation.get("prefix") or ""
    suffix = annotation.get("suffix") or ""
    position = annotation.get("text_position")

    def score(span: tuple[int, int]) -> float:
        start, end = span
        before = text[max(0, start - CONTEXT) : start]
        after = text[end : end + CONTEXT]
        total = float(_common_suffix(before, prefix) + _common_prefix(after, suffix))
        if isinstance(position, int):
            total += max(0.0, 8 - abs(start - position) / 500)
        return total

    ranked = sorted(spans, key=score, reverse=True)
    winner = ranked[0]
    ambiguous = len(ranked) > 1 and score(ranked[1]) >= score(winner) - 1
    return Match(winner[0], winner[1], exact, ambiguous)


def resolve_all(text: str, annotations: list[dict]) -> tuple[list[tuple[dict, Match]], list[dict]]:
    """Split annotations into the ones this text still holds and the orphans."""
    placed: list[tuple[dict, Match]] = []
    orphans: list[dict] = []
    for annotation in annotations:
        found = resolve(text, annotation)
        if found is None:
            orphans.append(annotation)
        else:
            placed.append((annotation, found))
    placed.sort(key=lambda pair: pair[1].start)
    return placed, orphans
