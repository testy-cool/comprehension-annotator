from sink.anchor import collapse, resolve, resolve_all

TEXT = (
    "A phrase can appear forty times on one page, so the quote alone is not enough.\n"
    "The surrounding words settle it, and the quote alone is not enough without them."
)


def annotation(quote, prefix="", suffix="", position=None, ident="ann-1"):
    return {
        "id": ident,
        "quote": quote,
        "prefix": prefix,
        "suffix": suffix,
        "text_position": position,
    }


def test_a_passage_is_found_where_it_sits():
    found = resolve(TEXT, annotation("forty times"))
    assert TEXT[found.start : found.end] == "forty times"
    assert found.exact is True


def test_the_surrounding_words_choose_between_repeats():
    first = TEXT.index("the quote alone is not enough")
    second = TEXT.index("the quote alone is not enough", first + 1)

    early = resolve(TEXT, annotation("the quote alone is not enough", prefix="page, so "))
    late = resolve(TEXT, annotation("the quote alone is not enough", prefix="settle it, and "))

    assert early.start == first
    assert late.start == second
    assert late.ambiguous is False


def test_a_repeat_with_no_context_is_reported_as_ambiguous():
    found = resolve(TEXT, annotation("the quote alone is not enough"))
    assert found.ambiguous is True


def test_a_passage_survives_the_text_being_reflowed():
    reflowed = "A phrase can appear   forty\n   times on one page."
    found = resolve(reflowed, annotation("forty times"))
    assert found is not None
    assert found.exact is False
    assert collapse(reflowed[found.start : found.end]) == "forty times"


def test_a_rewritten_passage_is_not_matched_to_something_else():
    assert resolve("Everything here was rewritten by an editor.", annotation("forty times")) is None


def test_resolving_a_set_separates_the_orphans_and_orders_the_rest():
    annotations = [
        annotation("without them", ident="ann-late"),
        annotation("forty times", ident="ann-early"),
        annotation("a passage that was deleted", ident="ann-gone"),
    ]
    placed, orphans = resolve_all(TEXT, annotations)

    assert [a["id"] for a, _ in placed] == ["ann-early", "ann-late"]
    assert [a["id"] for a in orphans] == ["ann-gone"]


def test_an_annotation_with_no_quote_is_an_orphan():
    assert resolve(TEXT, annotation("")) is None
