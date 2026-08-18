from sink.rewrite import build_prompt, mark_up

TEXT = (
    "A phrase can appear forty times on one page, so the quote alone is not enough.\n\n"
    "The surrounding words settle it, and the quote alone is not enough without them."
)

DOCUMENT = {
    "title": "Anchoring",
    "url": "https://ex.com/anchoring",
    "snapshots": [{"id": "20260818-090000-abc", "captured_at": "2026-08-18T09:00:00+00:00"}],
}


def annotation(quote, note, ident="ann-1", prefix="", category=None):
    return {
        "id": ident,
        "quote": quote,
        "note": note,
        "prefix": prefix,
        "suffix": "",
        "category": category,
    }


def test_each_marked_passage_is_numbered_in_place():
    marked, numbered, orphans = mark_up(
        TEXT,
        [
            annotation("without them", "why does this matter", ident="ann-late"),
            annotation("forty times", "the core problem", ident="ann-early"),
        ],
    )

    assert "⟦1⟧forty times⟦/1⟧" in marked
    assert "⟦2⟧without them⟦/2⟧" in marked
    assert [a["id"] for _, a in numbered] == ["ann-early", "ann-late"]
    assert orphans == []


def test_the_numbering_follows_the_text_not_the_order_they_were_written():
    _marked, numbered, _ = mark_up(
        TEXT,
        [
            annotation("without them", "second in the page", ident="ann-a"),
            annotation("A phrase", "first in the page", ident="ann-b"),
        ],
    )
    assert [n for n, _ in numbered] == [1, 2]
    assert [a["note"] for _, a in numbered] == ["first in the page", "second in the page"]


def test_marking_never_disturbs_the_text_between_passages():
    marked, _, _ = mark_up(TEXT, [annotation("forty times", "x")])
    assert marked.replace("⟦1⟧", "").replace("⟦/1⟧", "") == TEXT


def test_a_passage_no_longer_in_the_text_is_kept_as_evidence():
    prompt = build_prompt(
        DOCUMENT,
        [annotation("a sentence the editor removed", "this confused me", ident="ann-gone")],
        TEXT,
    )
    assert "no longer in the text" in prompt
    assert "a sentence the editor removed" in prompt
    assert "this confused me" in prompt


def test_the_prompt_carries_the_notes_the_page_and_where_it_came_from():
    prompt = build_prompt(
        DOCUMENT,
        [annotation("forty times", "the core problem", category="unclear")],
        TEXT,
    )
    assert "the core problem" in prompt
    assert "Category: unclear" in prompt
    assert "https://ex.com/anchoring" in prompt
    assert "2026-08-18T09:00:00+00:00" in prompt
    assert "⟦1⟧forty times⟦/1⟧" in prompt
    assert "Rewrite the whole page" in prompt


def test_a_page_with_no_notes_still_produces_a_usable_prompt():
    prompt = build_prompt(DOCUMENT, [], TEXT)
    assert "Nothing on this page is marked" in prompt
    assert TEXT in prompt


def test_a_note_left_empty_does_not_read_as_a_missing_line():
    prompt = build_prompt(DOCUMENT, [annotation("forty times", "   ")], TEXT)
    assert "the passage itself was the point" in prompt


def test_a_very_long_quote_is_shortened_in_the_brief_but_not_in_the_page():
    long_quote = TEXT[:170]
    prompt = build_prompt(DOCUMENT, [annotation(long_quote, "too much")], TEXT)
    assert "…" in prompt.split("## What to do")[0]
    assert f"⟦1⟧{long_quote}⟦/1⟧" in prompt
