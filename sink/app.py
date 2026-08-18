"""The sink's HTTP surface.

Every route here is a request to change or read the library. Nothing else on the
machine writes to it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .anchor import resolve_all
from .auth import EXTENSION_ORIGIN, matches
from .library import Library
from .rewrite import build_prompt
from .urls import document_id

WEB = Path(__file__).parent / "web"

VERSION = "0.1.0"


class AnnotationIn(BaseModel):
    id: str
    quote: str
    note: str = ""
    prefix: str = ""
    suffix: str = ""
    text_position: int | None = None
    created_at: str | None = None
    source: str = "human"
    category: str | None = None


class AnnotateRequest(BaseModel):
    url: str
    title: str | None = None
    dom_hash: str = Field(min_length=8)
    html: str | None = None
    annotation: AnnotationIn


class AnnotationPatch(BaseModel):
    note: str | None = None
    status: str | None = None
    category: str | None = None
    document_id: str | None = None


def create_app(library: Library, token: str) -> FastAPI:
    app = FastAPI(title="Comprehension Annotator sink", version=VERSION)

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=EXTENSION_ORIGIN,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-Annotator-Token"],
    )

    def authorize(x_annotator_token: str | None = Header(default=None)) -> None:
        if not matches(token, x_annotator_token):
            raise HTTPException(status_code=401, detail="bad or missing token")

    @app.get("/health")
    def health() -> dict:
        # Deliberately unauthenticated, so the options page can tell "sink is
        # down" apart from "token is wrong" before a token has been pasted in.
        return {"ok": True, "service": "comprehension-annotator-sink", "version": VERSION}

    @app.post("/annotate", dependencies=[Depends(authorize)])
    def annotate(request: AnnotateRequest) -> dict:
        result = library.store(
            url=request.url,
            title=request.title,
            dom_hash=request.dom_hash,
            html=request.html,
            annotation=request.annotation.model_dump(exclude_none=True),
        )
        if result is None:
            return {
                "status": "need_html",
                "need_html": True,
                "document_id": document_id(request.url),
            }
        return {
            "status": "stored",
            "need_html": False,
            "document_id": result.document_id,
            "snapshot_id": result.snapshot_id,
            "deduped": result.deduped,
            "created": result.created,
            "annotation": result.annotation,
        }

    @app.patch("/annotations/{annotation_id}", dependencies=[Depends(authorize)])
    def patch(annotation_id: str, body: AnnotationPatch) -> dict:
        record = library.patch_annotation(
            annotation_id,
            body.model_dump(exclude={"document_id"}, exclude_none=True),
            doc_id=body.document_id,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="no such annotation")
        return {"status": "patched", "annotation": record}

    @app.get("/documents", dependencies=[Depends(authorize)])
    def documents(url: str | None = Query(default=None)) -> dict:
        if url is None:
            return {"documents": library.list_documents()}

        doc_id = document_id(url)
        document = library.load_document(doc_id)
        return {
            "document": document,
            "annotations": library.annotations(doc_id) if document else [],
        }

    @app.get("/documents/{doc_id}", dependencies=[Depends(authorize)])
    def document(doc_id: str) -> dict:
        found = library.load_document(doc_id)
        if found is None:
            raise HTTPException(status_code=404, detail="no such document")
        return {"document": found, "annotations": library.annotations(doc_id)}

    def _snapshot_of(doc_id: str, wanted: str | None) -> tuple[dict, dict]:
        found = library.load_document(doc_id)
        if found is None:
            raise HTTPException(status_code=404, detail="no such document")
        snapshots = found.get("snapshots") or []
        if wanted:
            chosen = next((s for s in snapshots if s["id"] == wanted), None)
            if chosen is None:
                raise HTTPException(status_code=404, detail="no such snapshot")
        else:
            chosen = library.latest_snapshot(found)
        if chosen is None:
            raise HTTPException(status_code=409, detail="this document has no snapshot")
        return found, chosen

    @app.get("/documents/{doc_id}/reading", dependencies=[Depends(authorize)])
    def reading(doc_id: str, snapshot: str | None = Query(default=None)) -> dict:
        """One Snapshot's text with every Annotation located inside it."""
        found, chosen = _snapshot_of(doc_id, snapshot)
        text = library.snapshot_text(doc_id, chosen["id"])
        placed, orphans = resolve_all(text, library.annotations(doc_id))
        return {
            "document": found,
            "snapshot": chosen,
            "text": text,
            "placed": [
                {
                    "annotation": annotation,
                    "start": match.start,
                    "end": match.end,
                    "exact": match.exact,
                    "ambiguous": match.ambiguous,
                }
                for annotation, match in placed
            ],
            "orphans": orphans,
        }

    @app.get("/documents/{doc_id}/prompt", response_class=PlainTextResponse,
             dependencies=[Depends(authorize)])
    def prompt(doc_id: str, snapshot: str | None = Query(default=None)) -> str:
        found, chosen = _snapshot_of(doc_id, snapshot)
        text = library.snapshot_text(doc_id, chosen["id"])
        document = dict(found, snapshots=[chosen])
        return build_prompt(document, library.annotations(doc_id), text)

    @app.get("/search", dependencies=[Depends(authorize)])
    def search(q: str = Query(default="")) -> dict:
        return library.search(q)

    @app.get("/", response_class=HTMLResponse)
    def review() -> str:
        # Served without a token because it carries one: anything that can reach
        # loopback is already you, and CORS keeps a page you are visiting from
        # reading this response.
        return (WEB / "review.html").read_text(encoding="utf-8").replace("__TOKEN__", token)

    return app


def build_default_app() -> FastAPI:
    from .auth import ensure_token
    from .config import library_root, token_path

    root = Path(library_root())
    return create_app(Library(root), ensure_token(token_path()))
