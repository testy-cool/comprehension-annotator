"""The library on disk, and the only code that writes to it.

Every write goes through a temporary file and a rename, so a reader that opens a
file at the wrong moment sees the previous version rather than half of the next
one. One process owns all of this, which is what lets it stay that simple.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .extract import extract
from .urls import document_id, normalize_url

ACTIVE = "open"
DELETED = "deleted"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_atomic(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _write_json(path: Path, payload) -> None:
    _write_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


@dataclass
class StoreResult:
    document_id: str
    snapshot_id: str
    deduped: bool
    annotation: dict
    created: bool


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.documents_dir = self.root / "documents"
        self.index_path = self.root / "index.json"

    # paths -----------------------------------------------------------------

    def document_dir(self, doc_id: str) -> Path:
        return self.documents_dir / doc_id

    def _document_path(self, doc_id: str) -> Path:
        return self.document_dir(doc_id) / "document.json"

    def _annotations_path(self, doc_id: str) -> Path:
        return self.document_dir(doc_id) / "annotations.json"

    # documents -------------------------------------------------------------

    def load_document(self, doc_id: str) -> dict | None:
        return _read_json(self._document_path(doc_id), None)

    def document_for_url(self, url: str) -> dict | None:
        return self.load_document(document_id(url))

    def _new_document(self, doc_id: str, url: str, title: str | None, now: datetime) -> dict:
        return {
            "id": doc_id,
            "url": url,
            "normalized_url": normalize_url(url),
            "title": title or "",
            "created_at": _iso(now),
            "updated_at": _iso(now),
            "snapshots": [],
        }

    def latest_snapshot(self, document: dict) -> dict | None:
        snapshots = document.get("snapshots") or []
        return snapshots[-1] if snapshots else None

    def snapshot_text(self, doc_id: str, snapshot_id: str) -> str:
        """The readable text derived from one Snapshot, which is what a rewrite reads."""
        path = self.document_dir(doc_id) / "snapshots" / f"{snapshot_id}.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def snapshot_html(self, doc_id: str, snapshot_id: str) -> str:
        path = self.document_dir(doc_id) / "snapshots" / f"{snapshot_id}.html"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def snapshot_with_hash(self, document: dict, dom_hash: str) -> dict | None:
        """A page can be revisited unchanged, or revert to a shape we already hold."""
        for snapshot in document.get("snapshots", []):
            if snapshot["hash"] == dom_hash:
                return snapshot
        return None

    # writing ---------------------------------------------------------------

    def store(
        self,
        *,
        url: str,
        title: str | None,
        dom_hash: str,
        html: str | None,
        annotation: dict,
        now: datetime | None = None,
    ) -> StoreResult | None:
        """Record one Annotation, capturing a Snapshot only if this DOM is new.

        Returns None when the DOM is unknown and no HTML came with the request,
        which is the sink asking the extension to resend with the page attached.
        """
        now = now or utcnow()
        doc_id = document_id(url)
        document = self.load_document(doc_id) or self._new_document(doc_id, url, title, now)

        existing = self.snapshot_with_hash(document, dom_hash)
        if existing is None:
            if html is None:
                return None
            snapshot = self._write_snapshot(doc_id, url, html, now)
            document["snapshots"].append(snapshot)
            deduped = False
        else:
            snapshot = existing
            deduped = True

        document["url"] = url
        if title:
            document["title"] = title
        document["updated_at"] = _iso(now)

        record, created = self._upsert_annotation(
            doc_id, annotation, snapshot_id=snapshot["id"], url=url, now=now
        )

        _write_json(self._document_path(doc_id), document)
        self._reindex(document, now)
        return StoreResult(doc_id, snapshot["id"], deduped, record, created)

    def _write_snapshot(self, doc_id: str, url: str, html: str, now: datetime) -> dict:
        # The hash is recomputed here rather than trusted, so what is on disk and
        # what the hash claims can never drift apart.
        digest = sha256(html)
        snapshot_id = f"{now.astimezone(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{digest[:12]}"
        directory = self.document_dir(doc_id) / "snapshots"

        markdown, meta = extract(html, url=url)
        meta.update({"id": snapshot_id, "hash": digest, "url": url, "captured_at": _iso(now)})

        _write_atomic(directory / f"{snapshot_id}.html", html)
        _write_atomic(directory / f"{snapshot_id}.md", markdown)
        _write_json(directory / f"{snapshot_id}.meta.json", meta)

        return {
            "id": snapshot_id,
            "hash": digest,
            "captured_at": _iso(now),
            "html_bytes": len(html.encode("utf-8")),
            "word_count": meta.get("word_count", 0),
            "extractor": meta.get("extractor"),
        }

    # annotations -----------------------------------------------------------

    def annotations(self, doc_id: str, include_deleted: bool = False) -> list[dict]:
        records = _read_json(self._annotations_path(doc_id), [])
        if include_deleted:
            return records
        return [r for r in records if r.get("status") != DELETED]

    def _upsert_annotation(
        self, doc_id: str, annotation: dict, *, snapshot_id: str, url: str, now: datetime
    ) -> tuple[dict, bool]:
        records = _read_json(self._annotations_path(doc_id), [])
        incoming = dict(annotation)
        incoming.update(
            {
                "document_id": doc_id,
                "snapshot_id": snapshot_id,
                "url": url,
                "updated_at": _iso(now),
            }
        )
        incoming.setdefault("category", None)
        incoming.setdefault("source", "human")
        incoming.setdefault("status", ACTIVE)
        incoming.setdefault("created_at", _iso(now))

        for position, record in enumerate(records):
            if record["id"] == incoming["id"]:
                # A replayed queue item must not become a second Annotation, and
                # must not rewrite when the reader first wrote it.
                incoming["created_at"] = record.get("created_at", incoming["created_at"])
                incoming["snapshot_id"] = record.get("snapshot_id", snapshot_id)
                records[position] = record | incoming
                _write_json(self._annotations_path(doc_id), records)
                return records[position], False

        records.append(incoming)
        _write_json(self._annotations_path(doc_id), records)
        return incoming, True

    def patch_annotation(
        self, annotation_id: str, patch: dict, doc_id: str | None = None, now: datetime | None = None
    ) -> dict | None:
        now = now or utcnow()
        candidates = [doc_id] if doc_id else self._document_ids()
        allowed = {"note", "status", "category"}

        for candidate in candidates:
            records = _read_json(self._annotations_path(candidate), [])
            for position, record in enumerate(records):
                if record["id"] != annotation_id:
                    continue
                for key, value in patch.items():
                    if key in allowed and value is not None:
                        record[key] = value
                record["updated_at"] = _iso(now)
                records[position] = record
                _write_json(self._annotations_path(candidate), records)
                return record
        return None

    # index -----------------------------------------------------------------

    def _document_ids(self) -> list[str]:
        if not self.documents_dir.exists():
            return []
        return sorted(p.name for p in self.documents_dir.iterdir() if p.is_dir())

    def _reindex(self, document: dict, now: datetime) -> None:
        index = _read_json(self.index_path, {"documents": {}})
        index.setdefault("documents", {})
        doc_id = document["id"]
        index["documents"][doc_id] = {
            "url": document["url"],
            "normalized_url": document["normalized_url"],
            "title": document["title"],
            "snapshot_count": len(document["snapshots"]),
            "annotation_count": len(self.annotations(doc_id)),
            "created_at": document["created_at"],
            "updated_at": document["updated_at"],
        }
        index["updated_at"] = _iso(now)
        _write_json(self.index_path, index)

    def list_documents(self) -> list[dict]:
        index = _read_json(self.index_path, {"documents": {}})
        entries = [{"id": k, **v} for k, v in index.get("documents", {}).items()]
        return sorted(entries, key=lambda e: e.get("updated_at", ""), reverse=True)
