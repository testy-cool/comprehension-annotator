import json
from datetime import datetime, timedelta, timezone

import pytest

from sink.library import Library, sha256

PAGE = "<html><head><title>Anchoring</title></head><body><article><p>{}</p></article></body></html>"
START = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)


def annotation(ident="ann-1", quote="the quoted passage", note="why it matters"):
    return {
        "id": ident,
        "quote": quote,
        "prefix": "before ",
        "suffix": " after",
        "text_position": 42,
        "note": note,
    }


@pytest.fixture
def library(tmp_path):
    return Library(tmp_path / "library")


def body(text="A passage worth keeping and reading twice, at some length."):
    return PAGE.format(text)


def test_the_first_annotation_asks_for_the_page(library):
    result = library.store(
        url="https://ex.com/a", title="A", dom_hash=sha256(body()), html=None,
        annotation=annotation(), now=START,
    )
    assert result is None
    assert not (library.root / "documents").exists()


def test_resending_with_the_page_stores_a_snapshot_and_its_markdown(library):
    html = body()
    result = library.store(
        url="https://ex.com/a", title="Anchoring", dom_hash=sha256(html), html=html,
        annotation=annotation(), now=START,
    )
    assert result.deduped is False
    assert result.created is True

    snapshots = library.document_dir(result.document_id) / "snapshots"
    assert (snapshots / f"{result.snapshot_id}.html").read_text() == html
    assert "worth keeping" in (snapshots / f"{result.snapshot_id}.md").read_text()
    meta = json.loads((snapshots / f"{result.snapshot_id}.meta.json").read_text())
    assert meta["hash"] == sha256(html)
    assert meta["word_count"] > 0


def test_a_second_annotation_on_an_unchanged_page_adds_no_snapshot(library):
    html = body()
    first = library.store(
        url="https://ex.com/a", title="A", dom_hash=sha256(html), html=html,
        annotation=annotation("ann-1"), now=START,
    )
    second = library.store(
        url="https://ex.com/a", title="A", dom_hash=sha256(html), html=None,
        annotation=annotation("ann-2", quote="another passage"), now=START + timedelta(minutes=5),
    )
    assert second.deduped is True
    assert second.snapshot_id == first.snapshot_id
    document = library.load_document(first.document_id)
    assert len(document["snapshots"]) == 1
    assert len(library.annotations(first.document_id)) == 2


def test_a_page_that_changed_gets_a_second_snapshot(library):
    first_html = body()
    grown = body("A passage worth keeping, plus everything infinite scroll loaded later.")
    first = library.store(
        url="https://ex.com/a", title="A", dom_hash=sha256(first_html), html=first_html,
        annotation=annotation("ann-1"), now=START,
    )
    second = library.store(
        url="https://ex.com/a", title="A", dom_hash=sha256(grown), html=grown,
        annotation=annotation("ann-2"), now=START + timedelta(hours=2),
    )
    assert second.snapshot_id != first.snapshot_id
    assert len(library.load_document(first.document_id)["snapshots"]) == 2


def test_a_page_that_reverted_reuses_the_snapshot_it_already_has(library):
    original = body()
    changed = body("Rewritten entirely, by someone with opinions about clarity.")
    library.store(url="https://ex.com/a", title="A", dom_hash=sha256(original), html=original,
                  annotation=annotation("ann-1"), now=START)
    library.store(url="https://ex.com/a", title="A", dom_hash=sha256(changed), html=changed,
                  annotation=annotation("ann-2"), now=START + timedelta(days=1))
    back = library.store(url="https://ex.com/a", title="A", dom_hash=sha256(original), html=None,
                         annotation=annotation("ann-3"), now=START + timedelta(days=2))
    assert back.deduped is True
    assert len(library.load_document(back.document_id)["snapshots"]) == 2


def test_a_replayed_queue_item_does_not_become_a_second_annotation(library):
    html = body()
    args = dict(url="https://ex.com/a", title="A", dom_hash=sha256(html), html=html)
    first = library.store(**args, annotation=annotation("ann-1"), now=START)
    again = library.store(**args, annotation=annotation("ann-1"), now=START + timedelta(minutes=1))

    assert again.created is False
    assert len(library.annotations(first.document_id)) == 1
    assert again.annotation["created_at"] == first.annotation["created_at"]


def test_the_same_article_reached_with_tracking_junk_is_one_document(library):
    html = body()
    a = library.store(url="https://ex.com/a", title="A", dom_hash=sha256(html), html=html,
                      annotation=annotation("ann-1"), now=START)
    b = library.store(url="https://ex.com/a/?utm_source=newsletter#top", title="A",
                      dom_hash=sha256(html), html=None, annotation=annotation("ann-2"),
                      now=START + timedelta(days=3))
    assert a.document_id == b.document_id
    assert len(library.list_documents()) == 1


def test_an_annotation_records_the_snapshot_it_was_made_against(library):
    html = body()
    result = library.store(url="https://ex.com/a", title="A", dom_hash=sha256(html), html=html,
                           annotation=annotation(), now=START)
    stored = library.annotations(result.document_id)[0]
    assert stored["snapshot_id"] == result.snapshot_id
    assert stored["category"] is None
    assert stored["source"] == "human"
    assert stored["status"] == "open"
    assert stored["quote"] == "the quoted passage"


def test_editing_a_note_leaves_everything_else_alone(library):
    html = body()
    result = library.store(url="https://ex.com/a", title="A", dom_hash=sha256(html), html=html,
                           annotation=annotation(), now=START)
    patched = library.patch_annotation("ann-1", {"note": "sharper second thought"})
    assert patched["note"] == "sharper second thought"
    assert patched["quote"] == "the quoted passage"
    assert patched["created_at"] == result.annotation["created_at"]
    assert patched["updated_at"] != result.annotation["updated_at"]


def test_a_deleted_annotation_is_hidden_but_kept(library):
    html = body()
    result = library.store(url="https://ex.com/a", title="A", dom_hash=sha256(html), html=html,
                           annotation=annotation(), now=START)
    library.patch_annotation("ann-1", {"status": "deleted"})
    assert library.annotations(result.document_id) == []
    assert len(library.annotations(result.document_id, include_deleted=True)) == 1


def test_patching_something_that_does_not_exist_reports_it(library):
    assert library.patch_annotation("ann-nope", {"note": "x"}) is None


def test_the_index_tracks_what_is_worth_returning_to(library):
    html = body()
    library.store(url="https://ex.com/a", title="Anchoring", dom_hash=sha256(html), html=html,
                  annotation=annotation("ann-1"), now=START)
    library.store(url="https://ex.com/b", title="Other", dom_hash=sha256(html), html=html,
                  annotation=annotation("ann-2"), now=START + timedelta(hours=1))
    documents = library.list_documents()
    assert [d["title"] for d in documents] == ["Other", "Anchoring"]
    assert documents[0]["annotation_count"] == 1
    assert documents[0]["snapshot_count"] == 1
