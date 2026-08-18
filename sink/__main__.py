"""Run the sink: `uv run python -m sink`."""

from __future__ import annotations

import argparse

import uvicorn

from .app import create_app
from .auth import ensure_token
from .config import DEFAULT_HOST, DEFAULT_PORT, library_root, token_path
from .library import Library


def main() -> None:
    parser = argparse.ArgumentParser(description="Comprehension annotator sink")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--library", default=None, help="override the library root")
    parser.add_argument("--print-token", action="store_true", help="print the token and exit")
    args = parser.parse_args()

    root = args.library or library_root()
    token = ensure_token(token_path())

    if args.print_token:
        print(token)
        return

    print(f"library : {root}")
    print(f"token   : {token_path()}")
    print(f"listening on http://{args.host}:{args.port}")
    uvicorn.run(create_app(Library(root), token), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
