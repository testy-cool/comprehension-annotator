"""Run the sink, or pull things out of the library from a terminal.

    uv run python -m sink                      start it
    uv run python -m sink token                print the token
    uv run python -m sink list                 what is in the library
    uv run python -m sink prompt <url|id>      the rewrite prompt for one page
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from .app import create_app
from .auth import ensure_token
from .config import DEFAULT_HOST, DEFAULT_PORT, library_root, token_path
from .library import Library
from .rewrite import build_prompt
from .urls import document_id


def resolve_document(library: Library, target: str) -> tuple[str, dict]:
    """Accept whichever of the two things the reader has to hand: a url or an id."""
    found = library.load_document(target)
    if found is not None:
        return target, found

    doc_id = document_id(target)
    found = library.load_document(doc_id)
    if found is not None:
        return doc_id, found

    matches = [d for d in library.list_documents() if target.lower() in (d.get("url", "").lower())]
    if len(matches) == 1:
        return matches[0]["id"], library.load_document(matches[0]["id"])
    if len(matches) > 1:
        raise SystemExit(
            "that matches several pages:\n"
            + "\n".join(f"  {m['id']}  {m['url']}" for m in matches[:10])
        )
    raise SystemExit(f"nothing in the library for {target}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="sink", description="Comprehension annotator sink")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--library", default=None, help="override the library root")
    parser.add_argument(
        "--print-token", action="store_true", help=argparse.SUPPRESS  # kept for older habits
    )

    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="run the sink (the default)")
    commands.add_parser("token", help="print the token the extension needs")
    commands.add_parser("list", help="list what is in the library")
    prompt = commands.add_parser("prompt", help="print the rewrite prompt for one page")
    prompt.add_argument("target", help="a url, a document id, or part of a url")
    prompt.add_argument("--snapshot", default=None, help="which snapshot, newest by default")

    args = parser.parse_args()
    root = args.library or library_root()
    library = Library(root)
    token = ensure_token(token_path())

    if args.print_token or args.command == "token":
        print(token)
        return

    if args.command == "list":
        documents = library.list_documents()
        if not documents:
            print(f"nothing in {root} yet")
            return
        for entry in documents:
            print(
                f"{entry['id']}  {entry.get('annotation_count', 0):>3} notes  "
                f"{(entry.get('updated_at') or '')[:10]}  {entry.get('title') or ''}"
            )
            print(f"{'':>18}{entry.get('url', '')}")
        return

    if args.command == "prompt":
        doc_id, document = resolve_document(library, args.target)
        snapshot = None
        if args.snapshot:
            snapshot = next(
                (s for s in document.get("snapshots", []) if s["id"] == args.snapshot), None
            )
            if snapshot is None:
                raise SystemExit(f"no snapshot {args.snapshot} on that page")
        else:
            snapshot = library.latest_snapshot(document)
        if snapshot is None:
            raise SystemExit("that page has no snapshot to rewrite")

        text = library.snapshot_text(doc_id, snapshot["id"])
        sys.stdout.write(
            build_prompt(dict(document, snapshots=[snapshot]), library.annotations(doc_id), text)
        )
        return

    print(f"library : {root}")
    print(f"token   : {token_path()}")
    print(f"reading : http://{args.host}:{args.port}/")
    uvicorn.run(create_app(library, token), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
