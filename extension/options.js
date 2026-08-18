const fields = { sinkUrl: document.getElementById("sinkUrl"), token: document.getElementById("token") };
const status = document.getElementById("status");

function show(message, good) {
  status.textContent = message;
  status.style.color = good === undefined ? "#5a6472" : good ? "#1f7a4d" : "#c0392b";
}

chrome.storage.local.get("settings").then(({ settings }) => {
  const current = settings || {};
  fields.sinkUrl.value = current.sinkUrl || "http://127.0.0.1:8790";
  fields.token.value = current.token || "";
});

document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({
    settings: { sinkUrl: fields.sinkUrl.value.trim(), token: fields.token.value.trim() },
  });
  show("Saved.", true);
});

// Two separate checks, because "the sink is not running" and "the token is
// wrong" need different fixes and look identical from a single failed request.
document.getElementById("test").addEventListener("click", async () => {
  const base = fields.sinkUrl.value.trim().replace(/\/$/, "");
  show("Checking…");
  try {
    const health = await fetch(base + "/health");
    if (!health.ok) throw new Error("unhealthy");
  } catch (error) {
    show("No sink at that address. Is it running?", false);
    return;
  }
  const listing = await fetch(base + "/documents", {
    headers: { "X-Annotator-Token": fields.token.value.trim() },
  });
  if (listing.status === 401) {
    show("Sink is up, but it rejected the token.", false);
    return;
  }
  const body = await listing.json();
  const { queue = [], deadLetter = [] } = await chrome.storage.local.get(["queue", "deadLetter"]);

  const parts = [`Connected. ${(body.documents || []).length} documents in the library.`];
  if (queue.length) parts.push(`${queue.length} waiting to be sent.`);
  if (deadLetter.length) parts.push(`${deadLetter.length} the sink refused.`);
  show(parts.join(" "), deadLetter.length === 0);
});
