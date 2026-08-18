# Comprehension Annotator

Mark passages while you read, and keep them, with the page they came from, on
your own disk.

The point of collecting them is what happens later: feeding a page and your
notes on it to an agent that rewrites the text into something you can take in
faster. That part is not built yet. This is the collecting.

Read [CONTEXT.md](CONTEXT.md) for what the words mean, [docs/design.md](docs/design.md)
for how it fits together, and [docs/adr/](docs/adr/) for why.

## Running it

Start the sink. It is the only thing that writes to disk, and the extension
queues everything locally while it is not running, so it does not have to be up
all the time.

```
uv run python -m sink
```

On first run it prints where it put the token. Read it back with:

```
uv run python -m sink --print-token
```

Load the extension in Chrome from `chrome://extensions` with developer mode
turned on, then Load unpacked and pick the `extension/` directory. Open its
options, paste the token, and press Test connection.

Then press `Alt+A` in any tab you want to annotate. Select a passage, type why
it caught you, press Enter. Press `Alt+A` again to switch the tab back to
normal.

## What lands on disk

```
library/
  index.json
  documents/<doc-id>/
    document.json
    annotations.json
    snapshots/
      <timestamp>-<hash>.html        the page as the browser rendered it
      <timestamp>-<hash>.md          readable text derived from that html
      <timestamp>-<hash>.meta.json
```

One directory per URL, however many times you come back to it. The page is only
stored again when it has actually changed. Set `ANNOTATOR_LIBRARY` to keep the
library somewhere other than this repo.

## Tests

```
uv run pytest                 # the sink
pnpm test                     # anchoring and the queue, in jsdom and in node
uv run python tests/e2e/run.py  # the real extension in a real browser
```

The end to end run drives an isolated browser on its own profile and port, so it
will not touch the browser you are using. It runs under Brave rather than
Chrome, because Chrome 151 refuses `--load-extension` from the command line and
carries on without the extension. Loading unpacked from `chrome://extensions` by
hand is unaffected.

## Not built yet

The rewrite pass and its prompt. Anything for reviewing the library outside the
browser. Search. Repairing annotations whose passage has since been rewritten,
which are currently only counted.
