from sink.extract import extract

ARTICLE = """
<html><head><title>Why anchoring is hard</title></head><body>
<nav>home about contact</nav>
<article>
<h1>Why anchoring is hard</h1>
<p>A phrase can appear forty times on one page, so the quote alone is not
enough to say where a reader was looking. The surrounding words settle it.</p>
<p>When the site is redeployed the markup changes but the sentences usually do
not, which is the property the anchor leans on.</p>
</article>
<footer>copyright</footer></body></html>
"""


def test_prose_is_extracted_without_the_chrome_around_it():
    markdown, meta = extract(ARTICLE, url="https://ex.com/a")
    assert "forty times" in markdown
    assert "copyright" not in markdown
    assert meta["word_count"] > 20
    assert meta["fallback"] is False


def test_a_page_with_no_article_still_yields_its_text():
    markdown, meta = extract("<html><body><div>Rate limit: 20 rpm</div></body></html>")
    assert "Rate limit: 20 rpm" in markdown
    assert meta["word_count"] > 0


def test_the_fallback_runs_when_readability_finds_nothing(monkeypatch):
    import trafilatura

    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: None)
    markdown, meta = extract("<html><body><p>bare words</p></body></html>")
    assert "bare words" in markdown
    assert meta["fallback"] is True
    assert meta["extractor"] == "plaintext"


def test_a_crashing_extractor_still_returns_the_text(monkeypatch):
    import trafilatura

    def boom(*a, **k):
        raise RuntimeError("lxml exploded")

    monkeypatch.setattr(trafilatura, "extract", boom)
    markdown, meta = extract("<html><body><p>bare words</p></body></html>")
    assert "bare words" in markdown
    assert "lxml exploded" in meta["error"]


def test_script_content_never_reaches_the_fallback_text():
    html = "<html><body><script>var secret='tracking'</script><p>Visible</p></body></html>"
    markdown, _ = extract(html)
    assert "tracking" not in markdown
    assert "Visible" in markdown
