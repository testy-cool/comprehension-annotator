# Comprehension Annotator — v1 design

Read `CONTEXT.md` for the vocabulary and `docs/adr/` for the decisions behind
the shape below.

## What v1 does

You press Alt+A on a page you are reading seriously. The tab enters annotation
mode. You select a passage, a small box appears next to it, you type why it
matters, you press Enter. The passage highlights, the note and the page both
land on disk, and when you come back to that page in annotation mode your old
highlights are drawn again.

That is the whole of v1. The rewrite pass is the point of the project but it is
not built yet; the file layout exists so that it can be written later without
touching anything else.

## Shape

    Chrome tab ──Alt+A──▶ content script (shadow root bubble)
                              │  annotation + page HTML
                              ▼
                      service worker queue  (chrome.storage.local)
                              │  HTTP, token in header
                              ▼
                          sink (Python)
                              │  sole writer
                              ▼
                            library/

## Library layout

    library/
      index.json                     url → document id, title, counts, last activity
      documents/<doc-id>/
        document.json                url, title, created_at, list of snapshots
        annotations.json             every Annotation for this Document
        snapshots/
          <ts>-<hash12>.html         raw DOM as rendered, post-JavaScript
          <ts>-<hash12>.md           readable text derived by the sink
          <ts>-<hash12>.meta.json    title, byline, word count, hash, extractor version

`doc-id` is the first 16 hex characters of the sha256 of the normalised URL.
Normalising means lowercasing the host, dropping the fragment, dropping tracking
parameters (utm_*, fbclid, gclid, mc_cid) and trimming a trailing slash. The
exact URL as visited is kept on both the Document and every Annotation.

The library is personal data. It is gitignored and lives under the repo only for
convenience; the path is configurable.

## Annotation record

    {
      "id":            "ann-01J...",        client generated, makes retries idempotent
      "document_id":   "9f2c...",
      "snapshot_id":   "20260818-143012-a1b2c3d4e5f6",
      "url":           "https://...",       exact url at capture time
      "quote":         "the selected text, verbatim",
      "prefix":        "up to 32 characters before",
      "suffix":        "up to 32 characters after",
      "text_position": 4821,                character offset into the page text, a hint only
      "note":          "why this passage matters",
      "category":      null,                reserved for a later agent pass
      "source":        "human",             or "agent", as in the FAQ annotator
      "status":        "open",              agents write "needs_review"
      "created_at":    "...",
      "updated_at":    "..."
    }

`quote` is copied character for character. Never reflow whitespace, never
straighten curly quotes. The same rule as the FAQ annotator, for the same
reason: the anchor is a search for this exact string.

## Sink API

    GET  /health                      → {ok, library_root, document_count}
    POST /annotate                    → {document_id, snapshot_id, deduped, need_html}
    PATCH /annotations/<id>           → edit the note, or set status "deleted"
    GET  /documents?url=<url>         → the Document and its Annotations, for redrawing highlights
    GET  /documents                   → the list, for a future review tool

`POST /annotate` carries the annotation, the URL, the title and the sha256 of
the current DOM. It carries the HTML itself only when the sink asks for it: if
the hash is already the Document's latest Snapshot the sink answers `deduped`,
and if the hash is unknown it answers `need_html` and the extension resends with
the HTML attached. The second and later annotations on a page therefore cost a
few hundred bytes.

The sink binds 127.0.0.1 only. It generates a token on first run into
`~/.config/comprehension-annotator/token`, requires it in an `X-Annotator-Token`
header, and rejects any request whose Origin is not the extension. The custom
header forces a CORS preflight, so a hostile page cannot post into the library.

## Repository layout

    extension/     MV3, plain JavaScript, loaded unpacked
      manifest.json
      background.js    mode toggle, injection, queue, flush, badge
      content.js       bubble, selection, anchor extraction, highlight drawing
      anchor.js        quote/prefix/suffix extraction and resolution, shared
      options.html/js  sink url, token, library root
    sink/          Python, uv, FastAPI, trafilatura for readable text
    tests/         pytest over the sink: url normalisation, hash dedupe, idempotent retries, anchor resolution
    library/       gitignored

## Interaction detail

- Alt+A toggles annotation mode for the tab. The toolbar icon does the same.
- In annotation mode, a selection longer than three characters raises the bubble.
- Enter saves, Shift+Enter adds a line, Escape cancels.
- Clicking an existing highlight reopens its note for editing or deletion.
- On entering annotation mode the extension fetches the Document and redraws
  every Annotation whose Anchor resolves. Anchors that do not resolve are
  counted as Orphans and reported in the bubble's header. Reviewing and
  repairing Orphans is not in v1.

## Deliberately not in v1

The rewrite prompt and the agent that consumes it. A desktop or web review tool
over the library. Search across Documents. Categories and tagging in the UI.
PDFs and non-HTML documents. Any syncing between machines.
