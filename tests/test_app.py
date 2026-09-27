import pytest
from fastapi.testclient import TestClient

from sink.app import create_app
from sink.library import Library, sha256

TOKEN = "test-token"
HTML = "<html><head><title>Anchoring</title></head><body><article><p>{}</p></article></body></html>"
PROSE = "A phrase can appear forty times on one page, so the quote alone is not enough."


def page(text=PROSE):
    return HTML.format(text)


def annotation(ident="ann-1", **over):
    payload = {
        "id": ident,
        "quote": "the quote alone is not enough",
        "prefix": "so ",
        "suffix": ".",
        "text_position": 61,
        "note": "this is the whole argument",
    }
    payload.update(over)
    return payload


@pytest.fixture
def client(tmp_path):
    app = create_app(Library(tmp_path / "library"), TOKEN)
    with TestClient(app) as c:
        c.headers.update({"X-Annotator-Token": TOKEN})
        yield c


def post(client, *, html=None, ident="ann-1", url="https://ex.com/a", body=None, **over):
    body = body if body is not None else page()
    return client.post("/annotate", json={
        "url": url, "title": "Anchoring", "dom_hash": sha256(body),
        "html": html, "annotation": annotation(ident, **over),
    })


def test_health_needs_no_token(tmp_path):
    app = create_app(Library(tmp_path / "library"), TOKEN)
    with TestClient(app) as bare:
        assert bare.get("/health").json()["ok"] is True


def test_a_request_without_the_token_is_refused(tmp_path):
    app = create_app(Library(tmp_path / "library"), TOKEN)
    with TestClient(app) as bare:
        assert bare.post("/annotate", json={}).status_code == 401
        assert bare.get("/documents").status_code == 401


def test_a_request_with_the_wrong_token_is_refused(client):
    assert client.post("/annotate", json={}, headers={"X-Annotator-Token": "no"}).status_code == 401


def test_the_sink_asks_for_the_page_then_stores_it(client):
    first = post(client).json()
    assert first["need_html"] is True

    second = post(client, html=page()).json()
    assert second["status"] == "stored"
    assert second["deduped"] is False
    assert second["annotation"]["snapshot_id"] == second["snapshot_id"]


def test_the_next_annotation_needs_no_page(client):
    post(client, html=page())
    again = post(client, ident="ann-2", quote="forty times").json()
    assert again["need_html"] is False
    assert again["deduped"] is True


def test_annotations_come_back_for_the_url_that_was_visited(client):
    post(client, html=page())
    found = client.get("/documents", params={"url": "https://ex.com/a?utm_source=x"}).json()
    assert found["document"]["title"] == "Anchoring"
    assert len(found["annotations"]) == 1
    assert found["annotations"][0]["prefix"] == "so "


def test_an_unvisited_url_is_empty_rather_than_an_error(client):
    found = client.get("/documents", params={"url": "https://ex.com/never"}).json()
    assert found["document"] is None
    assert found["annotations"] == []


def test_a_note_can_be_sharpened_later(client):
    post(client, html=page())
    patched = client.patch("/annotations/ann-1", json={"note": "second thought"}).json()
    assert patched["annotation"]["note"] == "second thought"


def test_a_deleted_annotation_stops_coming_back(client):
    post(client, html=page())
    client.patch("/annotations/ann-1", json={"status": "deleted"})
    found = client.get("/documents", params={"url": "https://ex.com/a"}).json()
    assert found["annotations"] == []


def test_patching_an_unknown_annotation_is_a_404(client):
    assert client.patch("/annotations/ann-nope", json={"note": "x"}).status_code == 404


def test_the_document_list_is_most_recent_first(client):
    post(client, html=page())
    post(client, url="https://ex.com/b", ident="ann-2", html=page("Another article entirely."),
         body=page("Another article entirely."))
    listed = client.get("/documents").json()["documents"]
    assert [d["url"] for d in listed] == ["https://ex.com/b", "https://ex.com/a"]


def test_a_replayed_annotation_is_stored_once(client):
    post(client, html=page())
    replay = post(client, html=page()).json()
    assert replay["created"] is False
    found = client.get("/documents", params={"url": "https://ex.com/a"}).json()
    assert len(found["annotations"]) == 1


def test_a_page_only_the_extension_could_render_is_kept_verbatim(client):
    rendered = page("Text that only exists after JavaScript ran.")
    post(client, html=rendered, body=rendered)
    doc_id = client.get("/documents", params={"url": "https://ex.com/a"}).json()["document"]["id"]
    detail = client.get(f"/documents/{doc_id}").json()
    snapshot = detail["document"]["snapshots"][0]
    assert snapshot["hash"] == sha256(rendered)


# ------------------------------------------------- reading, prompts and search


def article(text):
    return HTML.format(text)


LONG = (
    "A phrase can appear forty times on one page, so the quote alone is not enough. "
    "The surrounding words settle it, and the quote alone is not enough without them."
)


def stock(client, url="https://ex.com/a", body=None, ident="ann-1", **over):
    body = body or article(LONG)
    payload = {
        "url": url, "title": "Anchoring", "dom_hash": sha256(body), "html": body,
        "annotation": annotation(ident, **over),
    }
    return client.post("/annotate", json=payload).json()


def test_a_reading_locates_every_note_inside_the_captured_text(client):
    stored = stock(client, quote="forty times", prefix="appear ", suffix=" on one")
    found = client.get(f"/documents/{stored['document_id']}/reading").json()

    assert "forty times" in found["text"]
    assert len(found["placed"]) == 1
    placed = found["placed"][0]
    assert found["text"][placed["start"] : placed["end"]] == "forty times"
    assert found["orphans"] == []


def test_a_note_whose_passage_is_gone_is_reported_as_an_orphan(client):
    stored = stock(client, quote="a sentence that was cut", note="this confused me")
    found = client.get(f"/documents/{stored['document_id']}/reading").json()

    assert found["placed"] == []
    assert [o["note"] for o in found["orphans"]] == ["this confused me"]


def test_a_reading_can_ask_for_an_older_snapshot(client):
    first = stock(client, quote="forty times")
    grown = article(LONG + " And then a great deal more arrived as the reader scrolled.")
    client.post("/annotate", json={
        "url": "https://ex.com/a", "title": "Anchoring", "dom_hash": sha256(grown),
        "html": grown, "annotation": annotation("ann-2", quote="a great deal more"),
    })

    doc_id = first["document_id"]
    latest = client.get(f"/documents/{doc_id}/reading").json()
    original = client.get(
        f"/documents/{doc_id}/reading", params={"snapshot": first["snapshot_id"]}
    ).json()

    assert "a great deal more" in latest["text"]
    assert "a great deal more" not in original["text"]
    assert len(latest["placed"]) == 2
    assert len(original["placed"]) == 1
    # Made on the later snapshot and found there, so it is not an orphan.
    assert original["orphans"] == []
    assert [a["id"] for a in original["elsewhere"]] == ["ann-2"]
    prompt = client.get(
        f"/documents/{doc_id}/prompt", params={"snapshot": first["snapshot_id"]}
    ).text
    assert "a great deal more" not in prompt


def test_asking_for_a_snapshot_that_does_not_exist_is_a_404(client):
    stored = stock(client)
    assert client.get(
        f"/documents/{stored['document_id']}/reading", params={"snapshot": "nope"}
    ).status_code == 404


def test_the_prompt_carries_the_page_and_the_notes_marked_in_place(client):
    stored = stock(client, quote="forty times", prefix="appear ", note="the core problem")
    prompt = client.get(f"/documents/{stored['document_id']}/prompt").text

    assert "⟦1⟧forty times⟦/1⟧" in prompt
    assert "the core problem" in prompt
    assert "https://ex.com/a" in prompt
    assert "Rewrite the whole page" in prompt


def test_search_finds_a_note_by_what_was_written_about_it(client):
    stock(client, note="the core problem with anchoring")
    stock(client, url="https://ex.com/b", ident="ann-2", note="something else entirely")

    hits = client.get("/search", params={"q": "core problem"}).json()
    assert len(hits["annotations"]) == 1
    assert hits["annotations"][0]["document_title"] == "Anchoring"


def test_search_finds_a_note_by_the_passage_it_points_at(client):
    stock(client, quote="forty times")
    hits = client.get("/search", params={"q": "FORTY"}).json()
    assert len(hits["annotations"]) == 1


def test_search_finds_a_page_by_its_address(client):
    stock(client, url="https://example.org/deep/article")
    hits = client.get("/search", params={"q": "example.org"}).json()
    assert len(hits["documents"]) == 1


def test_an_empty_search_returns_nothing_rather_than_everything(client):
    stock(client)
    hits = client.get("/search", params={"q": "  "}).json()
    assert hits == {"documents": [], "annotations": []}


def test_a_deleted_note_leaves_the_search_and_the_prompt(client):
    stored = stock(client, quote="forty times", note="the core problem")
    client.patch("/annotations/ann-1", json={"status": "deleted"})

    assert client.get("/search", params={"q": "core problem"}).json()["annotations"] == []
    prompt = client.get(f"/documents/{stored['document_id']}/prompt").text
    assert "the core problem" not in prompt
    assert "Nothing on this page is marked" in prompt


def test_the_review_page_is_served_and_carries_the_token(client):
    page = client.get("/")
    assert page.status_code == 200
    assert TOKEN in page.text
    assert "__TOKEN__" not in page.text


def test_the_reading_and_prompt_still_need_the_token(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(Library(tmp_path / "library"), TOKEN)
    with TestClient(app) as bare:
        assert bare.get("/documents/whatever/reading").status_code == 401
        assert bare.get("/documents/whatever/prompt").status_code == 401
        assert bare.get("/search", params={"q": "x"}).status_code == 401
