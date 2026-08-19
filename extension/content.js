/**
 * What the reader touches: the bubble, the highlights and the status pill.
 *
 * Injected only when a tab is switched into annotation mode. All of its
 * interface lives inside a shadow root marked data-annotator-ui, so page CSS
 * cannot reach in and the anchor index does not read it back out as page text.
 */
(function () {
  if (window.__comprehensionAnnotator) return;

  var A = AnnotatorAnchor;
  var state = {
    on: false,
    host: null,
    shadow: null,
    bubble: null,
    pill: null,
    draft: null,
    editing: null,
    annotations: [],
    orphans: 0,
    pending: 0,
    message: "",
  };
  window.__comprehensionAnnotator = state;

  var STYLE = [
    ":host{all:initial}",
    ".card,.pill{font:13px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;",
    "color:#f2f4f7;background:#1c1f24;border:1px solid #3a4048;border-radius:10px;",
    "box-shadow:0 10px 30px rgba(0,0,0,.35);position:fixed;z-index:2147483647;}",
    ".card{width:340px;padding:12px;}",
    ".pill{bottom:16px;right:16px;padding:6px 10px;opacity:.9;cursor:default;}",
    ".head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;",
    "font-weight:600;letter-spacing:.02em;}",
    ".sub{font-weight:400;color:#98a2b3;font-size:11px;}",
    "blockquote{margin:0 0 8px;padding:6px 8px;background:#262b31;border-left:3px solid #e0b400;",
    "border-radius:4px;color:#e6e9ee;max-height:88px;overflow:auto;white-space:pre-wrap;}",
    "textarea{width:100%;box-sizing:border-box;min-height:74px;resize:vertical;padding:8px;",
    "border-radius:6px;border:1px solid #3a4048;background:#12151a;color:#f2f4f7;",
    "font:inherit;outline:none;}",
    "textarea:focus{border-color:#6aa6ff}",
    ".row{display:flex;gap:8px;align-items:center;margin-top:8px;}",
    "button{font:inherit;padding:5px 10px;border-radius:6px;border:1px solid #3a4048;",
    "background:#2b313a;color:#f2f4f7;cursor:pointer;}",
    "button.primary{background:#2f6fd0;border-color:#2f6fd0;}",
    "button.danger{background:transparent;color:#ff9b9b;border-color:#5a3a3a;}",
    ".spacer{flex:1}",
    ".hint{color:#98a2b3;font-size:11px;margin-top:6px;}",
    ".warn{color:#ffcf7a;}",
  ].join("");

  // ------------------------------------------------------------------ mount

  function mount() {
    if (state.host) return;
    var host = document.createElement("div");
    host.setAttribute("data-annotator-ui", "1");
    host.style.cssText = "all:initial;position:static;";
    var shadow = host.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = STYLE;
    shadow.appendChild(style);
    (document.body || document.documentElement).appendChild(host);

    state.host = host;
    state.shadow = shadow;
    renderPill();
  }

  function unmount() {
    if (state.host && state.host.parentNode) state.host.parentNode.removeChild(state.host);
    state.host = null;
    state.shadow = null;
    state.bubble = null;
    state.pill = null;
  }

  // ------------------------------------------------------------------- pill

  function renderPill() {
    if (!state.shadow) return;
    if (!state.pill) {
      state.pill = document.createElement("div");
      state.pill.className = "pill";
      state.shadow.appendChild(state.pill);
    }
    var parts = ["Annotating"];
    parts.push(state.annotations.length + " here");
    if (state.orphans) parts.push(state.orphans + " orphaned");
    if (state.pending) parts.push(state.pending + " queued");
    if (state.message) parts.push(state.message);
    state.pill.textContent = parts.join(" · ");
    state.pill.className = "pill" + (state.message || state.orphans ? " warn" : "");
  }

  function say(message) {
    state.message = message || "";
    renderPill();
    if (message) {
      setTimeout(function () {
        if (state.message === message) {
          state.message = "";
          renderPill();
        }
      }, 4000);
    }
  }

  // ----------------------------------------------------------------- bubble

  function closeBubble() {
    if (state.bubble && state.bubble.parentNode) state.bubble.parentNode.removeChild(state.bubble);
    state.bubble = null;
    state.draft = null;
    state.editing = null;
  }

  function openBubble(options) {
    closeBubble();
    mount();

    var card = document.createElement("div");
    card.className = "card";

    var head = document.createElement("div");
    head.className = "head";
    var title = document.createElement("span");
    title.textContent = options.editing ? "Edit annotation" : "New annotation";
    var sub = document.createElement("span");
    sub.className = "sub";
    sub.textContent = options.subtitle || "";
    head.appendChild(title);
    head.appendChild(sub);

    var quote = document.createElement("blockquote");
    quote.textContent = options.quote;

    var note = document.createElement("textarea");
    note.value = options.note || "";
    note.placeholder = "What made you stop here?";

    var row = document.createElement("div");
    row.className = "row";
    var save = document.createElement("button");
    save.className = "primary";
    save.textContent = "Save";
    var cancel = document.createElement("button");
    cancel.textContent = "Cancel";
    row.appendChild(save);
    row.appendChild(cancel);

    if (options.editing) {
      var spacer = document.createElement("span");
      spacer.className = "spacer";
      var remove = document.createElement("button");
      remove.className = "danger";
      remove.textContent = "Delete";
      remove.addEventListener("click", function () {
        options.onDelete();
        closeBubble();
      });
      row.appendChild(spacer);
      row.appendChild(remove);
    }

    var hint = document.createElement("div");
    hint.className = "hint";
    hint.textContent = "Enter saves · Shift+Enter adds a line · Esc closes";

    card.appendChild(head);
    card.appendChild(quote);
    card.appendChild(note);
    card.appendChild(row);
    card.appendChild(hint);
    state.shadow.appendChild(card);
    state.bubble = card;

    place(card, options.rect);

    save.addEventListener("click", function () {
      options.onSave(note.value.trim());
      closeBubble();
    });
    cancel.addEventListener("click", closeBubble);
    note.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        options.onSave(note.value.trim());
        closeBubble();
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeBubble();
      }
    });
    note.focus();
  }

  function place(card, rect) {
    var width = 340;
    var height = card.offsetHeight || 220;
    var margin = 10;
    var left = rect ? rect.left : window.innerWidth / 2 - width / 2;
    var top = rect ? rect.bottom + margin : 80;

    if (left + width > window.innerWidth - margin) left = window.innerWidth - width - margin;
    if (left < margin) left = margin;
    if (top + height > window.innerHeight - margin) {
      top = rect ? Math.max(margin, rect.top - height - margin) : margin;
    }
    card.style.left = Math.round(left) + "px";
    card.style.top = Math.round(top) + "px";
  }

  // ------------------------------------------------------------ annotating

  function newId() {
    var bytes = new Uint8Array(6);
    crypto.getRandomValues(bytes);
    var random = Array.prototype.map
      .call(bytes, function (b) {
        return b.toString(16).padStart(2, "0");
      })
      .join("");
    return "ann-" + Date.now().toString(36) + "-" + random;
  }

  function onSelection() {
    if (!state.on) return;
    var selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return;
    if (state.host && state.host.contains(selection.anchorNode)) return;

    var range = selection.getRangeAt(0);
    if (String(range).trim().length < 3) return;

    var index = A.buildIndex();
    var made = A.fromSelection(index, range);
    if (!made) return;

    var rect = range.getBoundingClientRect();
    openBubble({
      quote: made.quote,
      rect: rect,
      subtitle: made.quote.length + " chars",
      onSave: function (note) {
        save(made, note, index);
      },
    });
  }

  function save(made, note, index) {
    var annotation = {
      id: newId(),
      quote: made.quote,
      prefix: made.prefix,
      suffix: made.suffix,
      text_position: made.text_position,
      note: note,
      created_at: new Date().toISOString(),
    };

    // Paint it now. Whether it reached disk is the queue's problem, not the
    // reader's, and the badge says so if the sink is down.
    A.highlight(index, made.start, made.end, annotation.id);
    state.annotations.push(annotation);
    window.getSelection().removeAllRanges();
    renderPill();

    chrome.runtime.sendMessage(
      {
        type: "annotator:save",
        url: location.href,
        title: document.title,
        html: A.capture(),
        annotation: annotation,
      },
      function (response) {
        report(response, "saved");
      }
    );
  }

  function report(response, verb) {
    if (!response || !response.ok) {
      say("not saved: " + ((response && response.error) || "extension error"));
      return;
    }
    state.pending = response.pending || 0;
    if (!response.flushed) say("queued, sink unreachable");
    else say(verb);
  }

  function onClick(event) {
    if (!state.on) return;
    var mark = event.target.closest ? event.target.closest("mark[data-annotator-id]") : null;
    if (!mark) return;
    var id = mark.getAttribute("data-annotator-id");
    var record = state.annotations.filter(function (a) {
      return a.id === id;
    })[0];
    if (!record) return;

    event.preventDefault();
    event.stopPropagation();
    openBubble({
      editing: true,
      quote: record.quote,
      note: record.note,
      rect: mark.getBoundingClientRect(),
      subtitle: record.snapshot_id ? "on disk" : "this session",
      onSave: function (note) {
        record.note = note;
        patch(id, { note: note }, "updated");
      },
      onDelete: function () {
        A.unhighlight(id);
        state.annotations = state.annotations.filter(function (a) {
          return a.id !== id;
        });
        renderPill();
        patch(id, { status: "deleted" }, "deleted");
      },
    });
  }

  function patch(id, body, verb) {
    chrome.runtime.sendMessage({ type: "annotator:patch", id: id, patch: body }, function (r) {
      report(r, verb);
    });
  }

  function onKeydown(event) {
    if (event.key === "Escape" && state.bubble) closeBubble();
  }

  // --------------------------------------------------------------- redrawing

  function redraw() {
    return new Promise(function (resolve) {
      chrome.runtime.sendMessage(
        { type: "annotator:fetch", url: location.href },
        function (response) {
          if (!response || !response.ok) {
            say("sink unreachable, new notes will queue");
            resolve();
            return;
          }
          state.annotations = response.annotations || [];
          apply(state.annotations);
          resolve();
        }
      );
    });
  }

  /**
   * Resolve every annotation against one index, then paint from the end
   * backwards so that splitting a text node cannot invalidate an earlier match.
   */
  function apply(annotations) {
    var index = A.buildIndex();
    var placed = [];
    state.orphans = 0;

    annotations.forEach(function (annotation) {
      var found = A.resolve(index, annotation);
      if (!found) {
        state.orphans++;
        return;
      }
      placed.push({ annotation: annotation, found: found });
    });

    placed.sort(function (a, b) {
      return b.found.start - a.found.start;
    });
    placed.forEach(function (item) {
      A.highlight(index, item.found.start, item.found.end, item.annotation.id);
    });
    renderPill();
  }

  // ------------------------------------------------------------------ modes

  function enable() {
    if (state.on) return Promise.resolve();
    state.on = true;
    mount();
    document.addEventListener("mouseup", onSelection, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKeydown, true);
    return redraw();
  }

  function disable() {
    state.on = false;
    closeBubble();
    document.removeEventListener("mouseup", onSelection, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKeydown, true);
    state.annotations.forEach(function (annotation) {
      A.unhighlight(annotation.id);
    });
    state.annotations = [];
    state.orphans = 0;
    unmount();
  }

  chrome.runtime.onMessage.addListener(function (message, sender, reply) {
    if (message.type === "annotator:on") {
      enable().then(function () {
        reply({ ok: true });
      });
      return true;
    }
    if (message.type === "annotator:off") {
      disable();
      reply({ ok: true });
    }
    return false;
  });
})();
