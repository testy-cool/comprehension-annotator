const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "../../extension/background.js"), "utf8");
const TOKEN = "test-token";
const HTML = "<html><body><p>A page worth keeping.</p></body></html>";

/** Enough of the extension platform for the service worker to run under node. */
function fakeChrome() {
  const area = (store) => ({
    async get(keys) {
      if (typeof keys === "string") return { [keys]: store[keys] };
      const out = {};
      (keys || Object.keys(store)).forEach((k) => (out[k] = store[k]));
      return out;
    },
    async set(values) {
      Object.assign(store, values);
    },
    _store: store,
  });
  const listeners = {};
  const on = (name) => ({ addListener: (fn) => (listeners[name] = fn) });

  return {
    _listeners: listeners,
    badge: {},
    storage: { local: area({}), session: area({}) },
    action: {
      onClicked: on("action"),
      async setBadgeText(spec) {
        this._text = spec.text;
      },
      async setBadgeBackgroundColor() {},
    },
    commands: { onCommand: on("command") },
    tabs: {
      onUpdated: on("updated"),
      onRemoved: on("removed"),
      onActivated: on("activated"),
      async query() {
        return [{ id: 1, url: "https://ex.com/a" }];
      },
      async sendMessage() {
        return null;
      },
    },
    scripting: { async executeScript() {} },
    alarms: { create() {}, onAlarm: on("alarm") },
    runtime: { onMessage: on("message") },
  };
}

/** A sink that behaves like the real one: token, need_html, and a switch. */
function fakeSink() {
  const sink = { up: true, pages: new Set(), annotations: new Map(), calls: [], patches: [] };

  sink.fetch = async (url, options = {}) => {
    const target = new URL(url);
    sink.calls.push(target.pathname + target.search);
    if (!sink.up) throw new TypeError("Failed to fetch");

    if (target.pathname === "/health") return json({ ok: true });
    if ((options.headers || {})["X-Annotator-Token"] !== TOKEN) return json({}, 401);

    const body = options.body ? JSON.parse(options.body) : {};
    if (target.pathname === "/annotate") {
      if (!sink.pages.has(body.dom_hash)) {
        if (!body.html) return json({ need_html: true, status: "need_html" });
        sink.pages.add(body.dom_hash);
      }
      sink.annotations.set(body.annotation.id, body.annotation);
      return json({ status: "stored", need_html: false });
    }
    if (target.pathname.startsWith("/annotations/")) {
      const id = decodeURIComponent(target.pathname.split("/")[2]);
      if (!sink.annotations.has(id)) return json({ detail: "no such annotation" }, 404);
      sink.patches.push([id, body]);
      Object.assign(sink.annotations.get(id), body);
      return json({ status: "patched" });
    }
    return json({ documents: [] });
  };

  function json(payload, status = 200) {
    return {
      ok: status < 400,
      status,
      async json() {
        return payload;
      },
      async text() {
        return JSON.stringify(payload);
      },
    };
  }
  return sink;
}

function load() {
  const chrome = fakeChrome();
  const sink = fakeSink();
  const context = vm.createContext({
    chrome,
    fetch: (...args) => sink.fetch(...args),
    crypto,
    TextEncoder,
    URL,
    console,
    setTimeout,
    Promise,
  });
  vm.runInContext(SOURCE, context);
  return { chrome, sink, context };
}

async function ready(context, sink, token = TOKEN) {
  await context.chrome.storage.local.set({
    settings: { sinkUrl: "http://127.0.0.1:8790", token },
  });
}

const save = (id, note = "why") => ({
  type: "annotator:save",
  url: "https://ex.com/a",
  title: "A",
  html: HTML,
  annotation: { id, quote: "worth keeping", prefix: "page ", suffix: ".", note },
});

test("a saved note reaches the sink, uploading the page only when asked", async () => {
  const { context, sink } = load();
  await ready(context, sink);

  const result = await context.handle(save("ann-1"));
  assert.equal(result.ok, true);
  assert.equal(result.pending, 0);
  assert.deepEqual(sink.calls, ["/annotate", "/annotate"]);
  assert.equal(sink.annotations.size, 1);
});

test("a second note on the same page does not upload it again", async () => {
  const { context, sink } = load();
  await ready(context, sink);

  await context.handle(save("ann-1"));
  sink.calls.length = 0;
  await context.handle(save("ann-2"));
  assert.deepEqual(sink.calls, ["/annotate"]);
});

test("a note typed while the sink is down is kept and sent later", async () => {
  const { chrome, context, sink } = load();
  await ready(context, sink);
  sink.up = false;

  const result = await context.handle(save("ann-1"));
  assert.equal(result.flushed, false);
  assert.equal(result.pending, 1);
  assert.equal(sink.annotations.size, 0);

  const stored = await chrome.storage.local.get(["queue", "pages"]);
  assert.equal(stored.queue.length, 1);
  assert.equal(Object.keys(stored.pages).length, 1, "the page is kept with the queued note");

  sink.up = true;
  await context.flush();
  assert.equal(sink.annotations.size, 1);
  assert.equal((await chrome.storage.local.get("queue")).queue.length, 0);
});

test("the stored page is released once nothing needs it", async () => {
  const { chrome, context, sink } = load();
  await ready(context, sink);
  sink.up = false;
  await context.handle(save("ann-1"));
  await context.handle(save("ann-2"));

  let stored = await chrome.storage.local.get(["queue", "pages"]);
  assert.equal(stored.queue.length, 2);
  assert.equal(Object.keys(stored.pages).length, 1, "two notes share one page");

  sink.up = true;
  await context.flush();
  stored = await chrome.storage.local.get(["queue", "pages"]);
  assert.deepEqual(stored.queue, []);
  assert.deepEqual(stored.pages, {});
});

test("queued notes are sent in the order they were written", async () => {
  const { context, sink } = load();
  await ready(context, sink);
  sink.up = false;
  await context.handle(save("ann-1"));
  await context.handle(save("ann-2"));
  await context.handle(save("ann-3"));

  sink.up = true;
  await context.flush();
  assert.deepEqual([...sink.annotations.keys()], ["ann-1", "ann-2", "ann-3"]);
});

test("editing a note that has not been sent yet changes it in place", async () => {
  const { chrome, context, sink } = load();
  await ready(context, sink);
  sink.up = false;
  await context.handle(save("ann-1", "first thought"));
  await context.handle({ type: "annotator:patch", id: "ann-1", patch: { note: "sharper" } });

  const stored = await chrome.storage.local.get("queue");
  assert.equal(stored.queue.length, 1, "no separate patch was queued");
  assert.equal(stored.queue[0].annotation.note, "sharper");

  sink.up = true;
  await context.flush();
  assert.equal(sink.annotations.get("ann-1").note, "sharper");
  assert.deepEqual(sink.patches, []);
});

test("editing a note the sink already has goes over as a patch", async () => {
  const { context, sink } = load();
  await ready(context, sink);
  await context.handle(save("ann-1"));
  await context.handle({ type: "annotator:patch", id: "ann-1", patch: { note: "sharper" } });
  assert.equal(sink.annotations.get("ann-1").note, "sharper");
});

test("a patch for an annotation the sink never got does not wedge the queue", async () => {
  const { chrome, context, sink } = load();
  await ready(context, sink);
  await context.handle({ type: "annotator:patch", id: "ann-missing", patch: { note: "x" } });
  await context.handle(save("ann-1"));

  assert.equal(sink.annotations.size, 1, "the real note still got through");
  assert.deepEqual((await chrome.storage.local.get("queue")).queue, []);
});

test("a wrong token leaves the note queued rather than dropping it", async () => {
  const { chrome, context, sink } = load();
  await ready(context, sink, "wrong-token");

  const result = await context.handle(save("ann-1"));
  assert.equal(result.flushed, false);
  assert.equal((await chrome.storage.local.get("queue")).queue.length, 1);

  await ready(context, sink);
  await context.flush();
  assert.equal(sink.annotations.size, 1);
});

test("annotations for the current page are fetched by url", async () => {
  const { context, sink } = load();
  await ready(context, sink);
  const result = await context.handle({ type: "annotator:fetch", url: "https://ex.com/a?x=1" });
  assert.equal(result.ok, true);
  assert.match(sink.calls[0], /^\/documents\?url=https%3A%2F%2Fex\.com%2Fa%3Fx%3D1$/);
});

test("an item the sink permanently refuses is set aside so the rest get through", async () => {
  const { chrome, context, sink } = load();
  await ready(context, sink);

  const original = sink.fetch;
  sink.fetch = async (url, options) => {
    const body = options && options.body ? JSON.parse(options.body) : {};
    if (body.annotation && body.annotation.id === "ann-bad") {
      sink.calls.push("/annotate(rejected)");
      return { ok: false, status: 422, async text() { return "unprocessable"; },
        async json() { return {}; } };
    }
    return original(url, options);
  };

  sink.up = false;
  await context.handle(save("ann-bad"));
  await context.handle(save("ann-good"));
  sink.up = true;

  await context.flush();
  await context.flush();
  await context.flush();

  const stored = await chrome.storage.local.get(["queue", "deadLetter", "pages"]);
  assert.deepEqual(stored.queue, [], "the queue drained");
  assert.equal(stored.deadLetter.length, 1);
  assert.equal(stored.deadLetter[0].item.annotation.id, "ann-bad");
  assert.ok(sink.annotations.has("ann-good"), "the good note got through");
});

test("a refused item is retried before being given up on", async () => {
  const { chrome, context, sink } = load();
  await ready(context, sink);
  sink.fetch = async () => ({ ok: false, status: 422, async text() { return "no"; },
    async json() { return {}; } });

  await context.handle(save("ann-1"));
  let stored = await chrome.storage.local.get("queue");
  assert.equal(stored.queue.length, 1);
  assert.equal(stored.queue[0].attempts, 1);

  await context.flush();
  stored = await chrome.storage.local.get("queue");
  assert.equal(stored.queue[0].attempts, 2);

  await context.flush();
  stored = await chrome.storage.local.get(["queue", "deadLetter"]);
  assert.deepEqual(stored.queue, []);
  assert.equal(stored.deadLetter.length, 1);
});

test("a rejected token is never counted against a note", async () => {
  const { chrome, context, sink } = load();
  await ready(context, sink, "wrong-token");

  await context.handle(save("ann-1"));
  await context.flush();
  await context.flush();
  await context.flush();
  await context.flush();

  const stored = await chrome.storage.local.get(["queue", "deadLetter"]);
  assert.equal(stored.queue.length, 1, "still waiting for a working token");
  assert.equal(stored.queue[0].attempts, undefined);
  assert.equal(stored.deadLetter, undefined);

  await ready(context, sink);
  await context.flush();
  assert.ok(sink.annotations.has("ann-1"));
});
