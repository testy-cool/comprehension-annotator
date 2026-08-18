# Comprehension Annotator

A Chrome extension and local sink for marking up pages while reading them, so
the marked-up material can later be fed to an agent that rewrites the text into
something faster to comprehend.

## Language

**Document**:
Everything captured for one URL over time, including all its snapshots and all
annotations made against it.
_Avoid_: Page, article, entry

**Snapshot**:
The captured bytes of a Document at one moment, as rendered in the browser.
Deduplicated by content hash, so revisiting an unchanged page adds no new one.
_Avoid_: Save, copy, version, capture

**Annotation**:
One passage the reader marked plus the note they wrote about it. Belongs to a
Document and records which Snapshot it was made against.
_Avoid_: Highlight, comment, quote, markup

**Sink**:
The local process the extension sends captures and annotations to, and the only
writer of files on disk.
_Avoid_: Server, backend, daemon, API

**Annotation mode**:
The state of a single tab in which the extension is injected and text
selections raise the note bubble. Off by default in every tab.
_Avoid_: Enabled, active, recording

**Anchor**:
The record of where an Annotation points: the exact quoted text, its
surrounding prefix and suffix, and a position hint. Resolving one is a search
that may find nothing or find several candidates.
_Avoid_: Selector, range, location, position

**Library**:
The directory on disk holding every Document, Snapshot and Annotation. Personal
data, never committed.
_Avoid_: Store, database, archive, vault

**Orphan**:
An Annotation whose Anchor no longer resolves against the page in front of the
reader, because the wording changed or the passage was removed.
_Avoid_: Broken, stale, lost, unmatched

**Rewrite prompt**:
The text handed to an agent to rewrite one Snapshot, carrying the page, the
reader's Annotations marked in place, and the instructions for the rewrite.
_Avoid_: Export, bundle, payload
