"""Turning a Document and its Annotations into a prompt for a rewrite.

This is what the whole library is collected for. Nothing here calls a model: it
produces the text you hand to one.
"""

from __future__ import annotations

from pathlib import Path

from .anchor import resolve_all

TEMPLATE = Path(__file__).parent / "templates" / "rewrite.md"


def mark_up(text: str, annotations: list[dict]) -> tuple[str, list[tuple[int, dict]], list[dict]]:
    """Put numbered markers around each annotated passage, last one first.

    Working backwards means an earlier passage's offsets are still correct after
    a later one has been wrapped.
    """
    placed, orphans = resolve_all(text, annotations)
    numbered = [(number, annotation, found) for number, (annotation, found) in enumerate(placed, 1)]

    marked = text
    for number, _annotation, found in reversed(numbered):
        marked = (
            marked[: found.start]
            + f"⟦{number}⟧"
            + marked[found.start : found.end]
            + f"⟦/{number}⟧"
            + marked[found.end :]
        )

    return marked, [(number, annotation) for number, annotation, _ in numbered], orphans


def _describe(number: int, annotation: dict) -> str:
    note = (annotation.get("note") or "").strip() or "(no note, the passage itself was the point)"
    quote = " ".join((annotation.get("quote") or "").split())
    if len(quote) > 160:
        quote = quote[:157] + "…"
    lines = [f"**{number}.** “{quote}”", f"> {note}"]
    if annotation.get("category"):
        lines.append(f"> Category: {annotation['category']}")
    return "\n".join(lines)


def build_prompt(document: dict, annotations: list[dict], text: str) -> str:
    """The prompt for one Document, against one Snapshot's readable text."""
    marked, numbered, orphans = mark_up(text, annotations)

    if numbered:
        described = "\n\n".join(_describe(number, a) for number, a in numbered)
    else:
        described = (
            "Nothing on this page is marked. Rewrite it for a reader who found it "
            "worth keeping but slow going."
        )

    if orphans:
        described += "\n\n" + "\n\n".join(
            [
                "The reader also marked these passages, which are no longer in the text "
                "captured here. Treat them as evidence of what they found hard, not as "
                "places in this version:",
                *[
                    f"- “{' '.join((o.get('quote') or '').split())[:120]}” — "
                    f"{(o.get('note') or '').strip() or 'no note'}"
                    for o in orphans
                ],
            ]
        )

    snapshots = document.get("snapshots") or [{}]
    return TEMPLATE.read_text(encoding="utf-8").format(
        annotations=described,
        title=document.get("title") or "(untitled)",
        url=document.get("url", ""),
        captured_at=snapshots[-1].get("captured_at", "unknown"),
        text=marked,
    )
