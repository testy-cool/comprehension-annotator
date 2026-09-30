from sink.urls import document_id, normalize_url


def test_fragment_and_trailing_slash_are_cosmetic():
    assert normalize_url("https://ex.com/a/#section") == "https://ex.com/a"


def test_host_and_scheme_are_lowercased_but_path_is_not():
    assert normalize_url("HTTPS://Ex.COM/Path/To") == "https://ex.com/Path/To"


def test_default_port_is_dropped_and_other_ports_kept():
    assert normalize_url("https://ex.com:443/a") == "https://ex.com/a"
    assert normalize_url("http://localhost:8000/a") == "http://localhost:8000/a"


def test_tracking_parameters_are_dropped_and_the_rest_sorted():
    url = "https://ex.com/a?utm_source=x&page=2&fbclid=abc&id=7"
    assert normalize_url(url) == "https://ex.com/a?id=7&page=2"


def test_a_meaningful_query_survives():
    assert normalize_url("https://ex.com/s?q=rust") == "https://ex.com/s?q=rust"


def test_a_bare_root_keeps_its_slash():
    assert normalize_url("https://ex.com/") == "https://ex.com/"


def test_the_same_page_reached_two_ways_is_one_document():
    a = document_id("https://Ex.com/post/?utm_campaign=news#top")
    b = document_id("https://ex.com/post")
    assert a == b
    assert len(a) == 16


def test_different_pages_are_different_documents():
    assert document_id("https://ex.com/a") != document_id("https://ex.com/b")


def test_a_local_file_keeps_its_path_and_loses_only_its_fragment():
    assert normalize_url("file:///home/me/notes/a%20b.html#top") == "file:///home/me/notes/a%20b.html"


def test_two_local_files_are_two_documents():
    assert document_id("file:///home/me/a.html") != document_id("file:///home/me/b.html")
