/**
 * The half of the extension that survives the page.
 *
 * It owns three things: which tabs are in annotation mode, the queue that keeps
 * a note safe when the sink is not running, and the only conversation anything
 * here has with the sink. See docs/adr/0004-queue-first-durability.md.
 */

const DEFAULT_SINK = "http://127.0.0.1:8790";
const FLUSH_ALARM = "annotator-flush";
const MAX_ATTEMPTS = 3;

// ---------------------------------------------------------------- settings

async function settings() {
  const stored = await chrome.storage.local.get("settings");
  return Object.assign({ sinkUrl: DEFAULT_SINK, token: "" }, stored.settings || {});
}

// ------------------------------------------------------------------- sink

async function callSink(path, options = {}) {
  const { sinkUrl, token } = await settings();
  const response = await fetch(sinkUrl.replace(/\/$/, "") + path, {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json", "X-Annotator-Token": token },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`sink ${response.status}: ${detail.slice(0, 200)}`);
  }
  return response.json();
}

// ------------------------------------------------------------------ queue
// Every write is written down before it is attempted, so nothing typed is lost
// to a sink that happens to be down. Page HTML is held once per DOM hash rather
// than once per annotation, because several notes usually share a page.

let writing = Promise.resolve();

function serialize(mutator) {
  writing = writing.then(mutator, mutator);
  return writing;
}

async function enqueue(item, html) {
  await serialize(async () => {
    const stored = await chrome.storage.local.get(["queue", "pages"]);
    const queue = stored.queue || [];
    const pages = stored.pages || {};
    queue.push(item);
    if (html && item.domHash && !pages[item.domHash]) pages[item.domHash] = html;
    await chrome.storage.local.set({ queue, pages });
  });
  await refreshBadge();
}

/** Fold an edit into a note that has not reached the sink yet. */
async function amendQueued(annotationId, patch) {
  let amended = false;
  await serialize(async () => {
    const stored = await chrome.storage.local.get("queue");
    const queue = stored.queue || [];
    for (const item of queue) {
      if (item.kind === "annotate" && item.annotation.id === annotationId) {
        Object.assign(item.annotation, patch);
        amended = true;
      }
    }
    if (amended) await chrome.storage.local.set({ queue });
  });
  return amended;
}

/** Record the head's failure so a stuck item cannot hide behind a retry count. */
async function bumpHead(fields) {
  await serialize(async () => {
    const stored = await chrome.storage.local.get("queue");
    const queue = stored.queue || [];
    if (!queue.length) return;
    Object.assign(queue[0], fields);
    await chrome.storage.local.set({ queue });
  });
}

/**
 * Set aside an item the sink will never accept.
 *
 * The queue is strictly ordered, so one permanently rejected item would
 * otherwise block every note written after it, for as long as the extension
 * lives. Being able to inspect the casualty later is worth more than retrying
 * it forever.
 */
async function deadLetter(item, reason) {
  await serialize(async () => {
    const stored = await chrome.storage.local.get("deadLetter");
    const dead = stored.deadLetter || [];
    dead.push({ item: item, reason: reason, at: new Date().toISOString() });
    await chrome.storage.local.set({ deadLetter: dead.slice(-50) });
  });
}

function statusFrom(error) {
  const match = /sink (\d{3})/.exec(String(error));
  return match ? Number(match[1]) : 0;
}

async function dropHead(count, hash) {
  await serialize(async () => {
    const stored = await chrome.storage.local.get(["queue", "pages"]);
    const queue = (stored.queue || []).slice(count);
    const pages = stored.pages || {};
    if (hash && !queue.some((item) => item.domHash === hash)) delete pages[hash];
    await chrome.storage.local.set({ queue, pages });
  });
}

let flushing = false;

async function flush() {
  if (flushing) return { ok: true, skipped: true };
  flushing = true;
  try {
    for (;;) {
      const stored = await chrome.storage.local.get(["queue", "pages"]);
      const queue = stored.queue || [];
      if (!queue.length) return { ok: true, pending: 0 };

      const item = queue[0];
      try {
        if (item.kind === "annotate") {
          await sendAnnotation(item, (stored.pages || {})[item.domHash]);
        } else if (item.kind === "patch") {
          await callSink(`/annotations/${encodeURIComponent(item.id)}`, {
            method: "PATCH",
            body: item.patch,
          });
        }
      } catch (error) {
        const status = statusFrom(error);
        // A rejected token is the user's to fix and will start working the
        // moment they fix it, so it never counts against an item.
        const refused = status >= 400 && status < 500 && status !== 401;
        if (!refused) return { ok: false, error: String(error), pending: queue.length };

        const attempts = (item.attempts || 0) + 1;
        const hopeless = attempts >= MAX_ATTEMPTS || (item.kind === "patch" && status === 404);
        if (!hopeless) {
          await bumpHead({ attempts: attempts });
          return { ok: false, error: String(error), pending: queue.length };
        }
        await deadLetter(item, String(error));
      }
      await dropHead(1, item.domHash);
      await refreshBadge();
    }
  } finally {
    flushing = false;
  }
}

async function sendAnnotation(item, html) {
  const body = {
    url: item.url,
    title: item.title,
    dom_hash: item.domHash,
    html: null,
    annotation: item.annotation,
  };
  const first = await callSink("/annotate", { method: "POST", body });
  if (!first.need_html) return first;
  if (!html) throw new Error("the sink needs this page and the queue no longer holds it");
  return callSink("/annotate", { method: "POST", body: Object.assign({}, body, { html }) });
}

async function pendingCount() {
  const stored = await chrome.storage.local.get("queue");
  return (stored.queue || []).length;
}

// ------------------------------------------------------------------- mode

async function modes() {
  const stored = await chrome.storage.session.get("modes");
  return stored.modes || {};
}

async function setMode(tabId, on) {
  const current = await modes();
  if (on) current[tabId] = true;
  else delete current[tabId];
  await chrome.storage.session.set({ modes: current });
}

async function isOn(tabId) {
  return Boolean((await modes())[tabId]);
}

async function toggle(tab) {
  if (!tab || !tab.id) return;
  if (!/^https?:/.test(tab.url || "")) return;

  if (await isOn(tab.id)) {
    await send(tab.id, { type: "annotator:off" });
    await setMode(tab.id, false);
  } else {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["anchor.js", "content.js"],
    });
    await setMode(tab.id, true);
    await send(tab.id, { type: "annotator:on" });
  }
  await refreshBadge(tab.id);
}

async function send(tabId, message) {
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch (error) {
    return null; // the page navigated away, which is not worth reporting
  }
}

// ------------------------------------------------------------------ badge

async function refreshBadge(tabId) {
  const pending = await pendingCount();
  const target = tabId || (await currentTabId());
  if (target === null) return;

  if (pending > 0) {
    await chrome.action.setBadgeBackgroundColor({ color: "#c0392b" });
    await chrome.action.setBadgeText({ text: String(pending) });
    return;
  }
  const on = await isOn(target);
  await chrome.action.setBadgeBackgroundColor({ color: "#1f7a4d" });
  await chrome.action.setBadgeText({ tabId: target, text: on ? "ON" : "" });
}

async function currentTabId() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab ? tab.id : null;
}

// --------------------------------------------------------------- plumbing

chrome.action.onClicked.addListener(toggle);

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "toggle-annotation-mode") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await toggle(tab);
});

// A navigation takes the content script with it, so the mode goes too.
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status === "loading" && changeInfo.url !== undefined) {
    await setMode(tabId, false);
    await refreshBadge(tabId);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => setMode(tabId, false));
chrome.tabs.onActivated.addListener(({ tabId }) => refreshBadge(tabId));

chrome.alarms.create(FLUSH_ALARM, { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === FLUSH_ALARM) flush();
});

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  handle(message, sender).then(reply, (error) => reply({ ok: false, error: String(error) }));
  return true;
});

async function handle(message, sender) {
  switch (message.type) {
    case "annotator:fetch": {
      const found = await callSink(`/documents?url=${encodeURIComponent(message.url)}`);
      return { ok: true, annotations: found.annotations || [], document: found.document };
    }
    case "annotator:save": {
      await enqueue(
        {
          kind: "annotate",
          url: message.url,
          title: message.title,
          domHash: await sha256(message.html),
          annotation: message.annotation,
        },
        message.html
      );
      const result = await flush();
      return { ok: true, flushed: result.ok, error: result.error, pending: await pendingCount() };
    }
    case "annotator:patch": {
      const folded = await amendQueued(message.id, message.patch);
      if (!folded) {
        await enqueue({ kind: "patch", id: message.id, patch: message.patch });
      }
      const result = await flush();
      return { ok: true, flushed: result.ok, error: result.error, pending: await pendingCount() };
    }
    case "annotator:health": {
      const { sinkUrl } = await settings();
      const response = await fetch(sinkUrl.replace(/\/$/, "") + "/health");
      const stored = await chrome.storage.local.get("deadLetter");
      return {
        ok: response.ok,
        pending: await pendingCount(),
        rejected: (stored.deadLetter || []).length,
      };
    }
    default:
      return { ok: false, error: `unknown message ${message.type}` };
  }
}

async function sha256(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
