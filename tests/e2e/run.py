"""Drive the real extension in a real Chrome, against the real sink.

Launches an isolated Chrome with the extension loaded, walks through the gesture
a reader actually performs, and then checks the library on disk. Nothing here
touches the browser you use every day: it runs on its own profile and its own
debugging port.

    uv run python tests/e2e/run.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

REPO = Path(__file__).resolve().parent.parent.parent
CDP_PORT = 9333
SINK_PORT = 8792
PAGE_PORT = 8793

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Anchoring</title></head>
<body><article>
<p id="one">A phrase can appear forty times on one page, so the quote alone is not enough.</p>
<p id="two">The surrounding words settle it, and the quote alone is not enough without them.</p>
</article></body></html>"""


def find_browser() -> str:
    """A Chromium that will still load an unpacked extension from the command line.

    Google Chrome refuses --load-extension and --disable-extensions-except as of
    151, printing "not allowed in Google Chrome" and carrying on without the
    extension, so the end-to-end run uses another Chromium build. The extension
    platform under test is the same one.
    """
    for candidate in ("brave-browser", "chromium", "chromium-browser", "google-chrome-unstable"):
        found = shutil.which(candidate)
        if found:
            return found
    raise RuntimeError("no Chromium found that still accepts --load-extension")


class Chrome:
    def __init__(self, profile: Path, extension: Path):
        self.free_the_port()
        self.process = subprocess.Popen(
            [
                find_browser(),
                "--headless=new",
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={profile}",
                f"--load-extension={extension}",
                f"--disable-extensions-except={extension}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=DialMediaRouteProvider",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.await_ready()

    @staticmethod
    def free_the_port() -> None:
        """Clear a browser an interrupted run left behind, and wait until it is gone.

        Killing without waiting is what makes this suite look flaky: the next
        browser starts, finds the port taken, and quietly runs without its
        debugging endpoint.
        """
        import socket

        subprocess.run(["fuser", "-k", f"{CDP_PORT}/tcp"], capture_output=True)
        for _ in range(50):
            with socket.socket() as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(("127.0.0.1", CDP_PORT)) != 0:
                    return
            time.sleep(0.2)
        raise RuntimeError(f"port {CDP_PORT} is still held by something")

    def await_ready(self) -> None:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=1)
                return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("chrome never opened its debugging port")

    def targets(self) -> list[dict]:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list") as response:
            return json.load(response)

    def wait_for_target(self, predicate, what: str, timeout: float = 25) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for target in self.targets():
                if predicate(target):
                    return target
            time.sleep(0.3)
        raise RuntimeError(f"never saw {what}; targets were {[t['type'] for t in self.targets()]}")

    def open(self, url: str) -> dict:
        request = urllib.request.Request(
            f"http://127.0.0.1:{CDP_PORT}/json/new?{url}", method="PUT"
        )
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()


class Session:
    """One CDP connection, with just enough of the protocol to evaluate code."""

    def __init__(self, websocket_url: str):
        self.socket = websocket.create_connection(websocket_url, timeout=30)
        self.next_id = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        message_id = self.next_id
        self.socket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
                return message.get("result", {})

    def evaluate(self, expression: str):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(json.dumps(result["exceptionDetails"])[:400])
        return result["result"].get("value")

    def wait_until(self, expression, what: str, timeout: float = 20):
        """Poll until the page is actually ready to be talked to."""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                value = expression() if callable(expression) else self.evaluate(expression)
                if value:
                    return value
                last = value
            except RuntimeError as error:
                last = str(error)[:120]
            time.sleep(0.3)
        raise RuntimeError(f"timed out waiting for {what}; last saw {last}")

    def close(self) -> None:
        self.socket.close()


def sink_call(path: str, token: str):
    request = urllib.request.Request(
        f"http://127.0.0.1:{SINK_PORT}{path}", headers={"X-Annotator-Token": token}
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


CHECKS: list[tuple[str, bool]] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    CHECKS.append((description, bool(condition)))
    mark = "ok  " if condition else "FAIL"
    print(f"{mark} {description}" + (f"  [{detail}]" if detail and not condition else ""))


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="annotator-e2e-"))
    library = workspace / "library"
    token_file = workspace / "token"
    site = workspace / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE, encoding="utf-8")

    sink = subprocess.Popen(
        [sys.executable, "-m", "sink", "--port", str(SINK_PORT)],
        cwd=REPO,
        env={
            "PATH": "/usr/bin:/bin",
            "ANNOTATOR_LIBRARY": str(library),
            "ANNOTATOR_TOKEN_FILE": str(token_file),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PAGE_PORT), "--bind", "127.0.0.1"],
        cwd=site,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    browser = None
    try:
        for _ in range(60):
            if token_file.exists():
                break
            time.sleep(0.2)
        token = token_file.read_text().strip()

        browser = Chrome(workspace / "profile", REPO / "extension")
        worker = browser.wait_for_target(
            lambda t: t["type"] == "service_worker" and t["url"].startswith("chrome-extension://"),
            "the extension's service worker",
        )
        extension_id = worker["url"].split("/")[2]
        print(f"extension {extension_id}")

        # Everything is driven from the extension's own options page rather than
        # from the service worker, which Chrome is free to stop between steps.
        # Messaging it from a page is also what wakes it back up.
        options = Session(
            browser.open(f"chrome-extension://{extension_id}/options.html")["webSocketDebuggerUrl"]
        )
        options.call("Runtime.enable")
        options.wait_until(
            "typeof chrome !== 'undefined' && !!chrome.storage && !!chrome.tabs",
            "the options page to finish loading with its extension apis",
        )
        options.evaluate(
            "chrome.storage.local.set({settings:{sinkUrl:'http://127.0.0.1:%d',token:'%s'}})"
            % (SINK_PORT, token)
        )

        def tab_id():
            return options.evaluate(
                "(async()=>{const [t]=await chrome.tabs.query"
                "({url:'http://127.0.0.1:%d/*'});return t?t.id:null})()" % PAGE_PORT
            )

        def mode_is_on(target: int) -> bool:
            return bool(
                options.evaluate(
                    "(async()=>{const s=await chrome.storage.session.get('modes');"
                    "return !!(s.modes||{})[%d]})()" % target
                )
            )

        def set_mode(want: bool) -> bool:
            """Alt+A, as far as the extension is concerned.

            Reads the mode before touching it rather than firing the toggle and
            hoping. A service worker Chrome has stopped can drop the first
            message it is sent, and a blind retry would just toggle back.
            """
            target = options.wait_until(tab_id, "the page to appear in the tab list")
            for _ in range(12):
                if mode_is_on(target) == want:
                    return True
                options.evaluate(
                    "chrome.runtime.sendMessage({type:'annotator:toggle',tabId:%d})" % target
                )
                time.sleep(0.5)
            return mode_is_on(target) == want

        tab = browser.open(f"http://127.0.0.1:{PAGE_PORT}/index.html")
        page = Session(tab["webSocketDebuggerUrl"])
        page.call("Runtime.enable")
        page.call("Page.enable")
        page.wait_until("document.readyState === 'complete'", "the test page to load")

        check("arming the tab reports the mode is on", set_mode(True))
        page.wait_until("!!document.querySelector('[data-annotator-ui]')", "the interface to mount")

        check(
            "the extension mounts its interface only after the tab is armed",
            page.evaluate("!!document.querySelector('[data-annotator-ui]')"),
        )
        check(
            "the status pill says what is going on",
            "Annotating" in (page.evaluate(
                "document.querySelector('[data-annotator-ui]').shadowRoot"
                ".querySelector('.pill').textContent") or ""),
        )

        # Select a passage the way a reader would, then let go of the mouse.
        page.evaluate("""
          (() => {
            const node = document.getElementById('two').firstChild;
            const at = node.nodeValue.indexOf('the quote alone is not enough');
            const range = document.createRange();
            range.setStart(node, at);
            range.setEnd(node, at + 'the quote alone is not enough'.length);
            const selection = getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
            return true;
          })()
        """)
        shadow = "document.querySelector('[data-annotator-ui]').shadowRoot"
        page.wait_until(f"!!{shadow}.querySelector('.card')", "the bubble to open")
        check("a bubble opens beside the selection", page.evaluate(f"!!{shadow}.querySelector('.card')"))
        check(
            "the bubble shows the passage that was selected",
            page.evaluate(f"{shadow}.querySelector('blockquote').textContent")
            == "the quote alone is not enough",
        )

        page.evaluate(f"""
          (() => {{
            const note = {shadow}.querySelector('textarea');
            note.value = 'this is the whole argument';
            note.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}}));
            return true;
          }})()
        """)
        page.wait_until("document.querySelectorAll('mark[data-annotator-id]').length > 0",
                        "the passage to be highlighted")
        time.sleep(1.5)  # the note travels to the sink after the highlight appears

        check("the bubble closes once the note is saved",
              not page.evaluate(f"!!{shadow}.querySelector('.card')"))
        check("the passage is highlighted straight away",
              page.evaluate("document.querySelectorAll('mark[data-annotator-id]').length") == 1)
        check(
            "the highlight lands on the second occurrence, not the first",
            page.evaluate(
                "document.getElementById('two').querySelector('mark') !== null && "
                "document.getElementById('one').querySelector('mark') === null"
            ),
        )
        check("the page text is unchanged by highlighting",
              page.evaluate("document.getElementById('two').textContent")
              == "The surrounding words settle it, and the quote alone is not enough without them.")

        documents = sink_call("/documents", token)["documents"]
        check("the sink now holds the document", len(documents) == 1,
              detail=json.dumps(documents)[:200])

        stored = sink_call(
            f"/documents?url=http://127.0.0.1:{PAGE_PORT}/index.html", token
        )
        annotations = stored["annotations"]
        check("the note is on disk", len(annotations) == 1)
        if annotations:
            first = annotations[0]
            check("the quote was stored verbatim", first["quote"] == "the quote alone is not enough")
            check("the note was stored", first["note"] == "this is the whole argument")
            check("the surrounding words were stored too",
                  first["prefix"].endswith("and ") and first["suffix"].startswith(" without"))
            check("it records which snapshot it was made against", bool(first["snapshot_id"]))

        snapshots = list((library / "documents").glob("*/snapshots/*.html"))
        markdown = list((library / "documents").glob("*/snapshots/*.md"))
        check("the page itself was captured", len(snapshots) == 1)
        check("readable text was derived from it", len(markdown) == 1)
        if markdown:
            check("the derived text contains the article",
                  "forty times" in markdown[0].read_text())

        # Reload, arm again, and see whether the note comes back.
        page.call("Page.reload")
        page.wait_until("document.readyState === 'complete'", "the reload to finish")
        page.wait_until("!document.querySelector('[data-annotator-ui]')",
                        "the reload to take the interface with it")
        check("a reloaded page can be armed again with one press", set_mode(True))
        try:
            page.wait_until("document.querySelectorAll('mark[data-annotator-id]').length > 0",
                            "the notes to be painted back on", timeout=15)
        except RuntimeError:
            pass

        check("returning to the page paints the note back on",
              page.evaluate("document.querySelectorAll('mark[data-annotator-id]').length") == 1)
        check("and paints it in the right place",
              page.evaluate("document.getElementById('two').querySelector('mark') !== null"))
        pill = page.evaluate(
            "(document.querySelector('[data-annotator-ui]')||{shadowRoot:null}).shadowRoot"
            " ? document.querySelector('[data-annotator-ui]').shadowRoot"
            ".querySelector('.pill').textContent : ''"
        )
        check("the pill reports no orphans", "orphaned" not in (pill or ""), detail=str(pill))

        # The review surface, in the same browser, against the same library.
        review = Session(browser.open(f"http://127.0.0.1:{SINK_PORT}/")["webSocketDebuggerUrl"])
        review.call("Runtime.enable")
        review.wait_until("document.querySelectorAll('.doc').length > 0",
                          "the library list to load")
        check("the review page lists the page that was annotated",
              "Anchoring" in (review.evaluate("document.querySelector('.doc .t').textContent") or ""))

        review.evaluate("document.querySelector('.doc').click()")
        review.wait_until("document.querySelectorAll('mark').length > 0",
                          "the captured text to render with its note")
        check("the note is painted onto the captured text too",
              review.evaluate("document.querySelector('mark').textContent")
              == "the quote alone is not enough")
        check("the note itself is in the rail",
              "this is the whole argument" in
              (review.evaluate("document.querySelector('.note .n').textContent") or ""))
        check("nothing is orphaned in the snapshot it was made against",
              review.evaluate("document.querySelectorAll('.note .tag').length") == 0)

        review.evaluate("document.querySelector('#prompt').click()")
        review.wait_until("!!document.querySelector('pre.prompt')", "the rewrite prompt to build")
        prompt_text = review.evaluate("document.querySelector('pre.prompt').textContent")
        check("the prompt marks the passage in place",
              "⟦1⟧the quote alone is not enough⟦/1⟧" in (prompt_text or ""))
        check("the prompt carries the reader's note",
              "this is the whole argument" in (prompt_text or ""))
        check("the prompt carries the page itself",
              "The surrounding words settle it" in (prompt_text or ""))

        # Turning the mode off should leave no trace on the page.
        set_mode(False)
        try:
            page.wait_until("!document.querySelector('[data-annotator-ui]')",
                            "the interface to be removed", timeout=10)
        except RuntimeError:
            pass
        check("switching off removes every highlight",
              page.evaluate("document.querySelectorAll('mark[data-annotator-id]').length") == 0)
        check("switching off removes the interface",
              not page.evaluate("!!document.querySelector('[data-annotator-ui]')"))

    finally:
        if browser:
            browser.stop()
        sink.terminate()
        server.terminate()
        shutil.rmtree(workspace, ignore_errors=True)

    failed = [name for name, passed in CHECKS if not passed]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
