const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const SOURCE = fs.readFileSync(path.join(__dirname, "../../extension/anchor.js"), "utf8");

/** Load anchor.js against a fresh page, the way a content script would see it. */
function load(html) {
  const dom = new JSDOM(html, { runScripts: "outside-only" });
  const context = dom.getInternalVMContext();
  vm.runInContext(SOURCE, context);
  return { dom, anchor: context.AnnotatorAnchor, document: dom.window.document };
}

const ARTICLE = `<html><body><article>
<p id="one">A phrase can appear forty times on one page, so the quote alone is not enough.</p>
<p id="two">The surrounding words settle it, and the quote alone is not enough without them.</p>
</article></body></html>`;

function selectWithin(document, id, needle) {
  const node = document.getElementById(id).firstChild;
  const at = node.nodeValue.indexOf(needle);
  const range = document.createRange();
  range.setStart(node, at);
  range.setEnd(node, at + needle.length);
  return range;
}

test("a selection becomes a quote with the words either side of it", () => {
  const { anchor, document } = load(ARTICLE);
  const index = anchor.buildIndex(document.body);
  const made = anchor.fromSelection(index, selectWithin(document, "one", "forty times"));

  assert.equal(made.quote, "forty times");
  assert.ok(made.prefix.endsWith("can appear "));
  assert.ok(made.suffix.startsWith(" on one page"));
  assert.equal(typeof made.text_position, "number");
});

test("whitespace dragged in at the edges is trimmed off the quote", () => {
  const { anchor, document } = load(ARTICLE);
  const index = anchor.buildIndex(document.body);
  const made = anchor.fromSelection(index, selectWithin(document, "one", " forty times "));
  assert.equal(made.quote, "forty times");
});

test("a repeated phrase resolves to the occurrence the reader meant", () => {
  const { anchor, document } = load(ARTICLE);
  const index = anchor.buildIndex(document.body);
  const second = anchor.fromSelection(
    index,
    selectWithin(document, "two", "the quote alone is not enough")
  );

  const found = anchor.resolve(anchor.buildIndex(document.body), second);
  assert.equal(found.start, second.start);
  assert.equal(found.exact, true);
  assert.equal(found.ambiguous, false);
});

test("without context a repeated phrase is reported as ambiguous", () => {
  const { anchor, document } = load(ARTICLE);
  const index = anchor.buildIndex(document.body);
  const found = anchor.resolve(index, { quote: "the quote alone is not enough" });
  assert.equal(found.ambiguous, true);
});

test("an anchor survives the page being re-rendered around it", () => {
  const { anchor, document } = load(ARTICLE);
  const made = anchor.fromSelection(
    anchor.buildIndex(document.body),
    selectWithin(document, "one", "forty times")
  );

  const rebuilt = load(`<html><body><div class="ad">buy things</div><main><section>
<h2>Anchoring</h2>
<p>A phrase can appear forty times on one page, so the quote alone is not enough.</p>
</section></main></body></html>`);
  const found = rebuilt.anchor.resolve(
    rebuilt.anchor.buildIndex(rebuilt.document.body),
    made
  );
  assert.ok(found);
  assert.equal(rebuilt.anchor.buildIndex(rebuilt.document.body).text.slice(found.start, found.end),
    "forty times");
});

test("an anchor survives the whitespace changing", () => {
  const { anchor, document } = load(ARTICLE);
  const made = anchor.fromSelection(
    anchor.buildIndex(document.body),
    selectWithin(document, "one", "quote alone is not enough")
  );

  const reflowed = load(`<html><body><p>A phrase can appear forty times on one page,
      so the      quote
      alone is not     enough.</p></body></html>`);
  const index = reflowed.anchor.buildIndex(reflowed.document.body);
  const found = reflowed.anchor.resolve(index, made);
  assert.ok(found, "expected the reflowed page to still match");
  assert.equal(found.exact, false);
  assert.equal(
    reflowed.anchor.collapseString(index.text.slice(found.start, found.end)),
    "quote alone is not enough"
  );
});

test("a passage that was deleted becomes an orphan rather than a wrong match", () => {
  const { anchor, document } = load(ARTICLE);
  const made = anchor.fromSelection(
    anchor.buildIndex(document.body),
    selectWithin(document, "one", "forty times")
  );

  const rewritten = load("<html><body><p>Everything here was rewritten by an editor.</p></body></html>");
  const found = rewritten.anchor.resolve(rewritten.anchor.buildIndex(rewritten.document.body), made);
  assert.equal(found, null);
});

test("highlighting wraps the passage and leaves the text alone", () => {
  const { anchor, document } = load(ARTICLE);
  const index = anchor.buildIndex(document.body);
  const made = anchor.fromSelection(index, selectWithin(document, "one", "forty times"));

  const marks = anchor.highlight(index, made.start, made.end, "ann-1");
  assert.equal(marks.length, 1);
  assert.equal(marks[0].textContent, "forty times");
  assert.match(document.getElementById("one").textContent, /appear forty times on one page/);
});

test("a passage crossing element boundaries gets one mark per piece", () => {
  const { anchor, document } = load(
    "<html><body><p>plain <em>emphasised</em> tail</p></body></html>"
  );
  const index = anchor.buildIndex(document.body);
  const start = index.text.indexOf("plain");
  const end = index.text.indexOf("tail") + 4;

  const marks = anchor.highlight(index, start, end, "ann-2");
  assert.equal(marks.length, 3);
  assert.equal(document.body.textContent, "plain emphasised tail");
});

test("removing a highlight puts the page back as it was", () => {
  const { anchor, document } = load(ARTICLE);
  const before = document.getElementById("one").innerHTML;
  const index = anchor.buildIndex(document.body);
  const made = anchor.fromSelection(index, selectWithin(document, "one", "forty times"));

  anchor.highlight(index, made.start, made.end, "ann-3");
  assert.ok(document.querySelector('mark[data-annotator-id="ann-3"]'));
  anchor.unhighlight("ann-3");

  assert.equal(document.querySelectorAll("mark").length, 0);
  assert.equal(document.getElementById("one").innerHTML, before);
});

test("the extension's own interface is never part of the page text", () => {
  const { anchor, document } = load(
    '<html><body><p>real text</p><div data-annotator-ui="1"><textarea>my note</textarea>' +
      "<span>Save</span></div></body></html>"
  );
  const index = anchor.buildIndex(document.body);
  assert.ok(index.text.includes("real text"));
  assert.ok(!index.text.includes("Save"));
  assert.ok(!index.text.includes("my note"));
});

test("script and style contents are never part of the page text", () => {
  const { anchor, document } = load(
    "<html><body><script>var tracking = 1</script><style>.a{color:red}</style>" +
      "<p>real text</p></body></html>"
  );
  const index = anchor.buildIndex(document.body);
  assert.equal(index.text.trim(), "real text");
});
