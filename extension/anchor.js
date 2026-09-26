/**
 * Finding a passage on a page, and finding it again months later.
 *
 * An anchor is the quoted text plus the words either side of it. Resolving one
 * is a search, not a lookup, so it can miss or come back ambiguous. See
 * docs/adr/0001-quote-context-anchoring.md.
 */
var AnnotatorAnchor = (function () {
  var CONTEXT = 32;
  var SKIP = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1, TEMPLATE: 1, SVG: 1, CANVAS: 1 };

  /** The page as one string, with a map back to the text nodes it came from. */
  function buildIndex(root) {
    root = root || document.body || document.documentElement;
    var segments = [];
    var text = "";
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        var parent = node.parentElement;
        if (!parent || SKIP[parent.nodeName.toUpperCase()]) return NodeFilter.FILTER_REJECT;
        if (parent.closest("[data-annotator-ui]")) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    for (var node = walker.nextNode(); node; node = walker.nextNode()) {
      var value = node.nodeValue || "";
      if (!value.length) continue;
      segments.push({ node: node, start: text.length, end: text.length + value.length });
      text += value;
    }
    return { text: text, segments: segments, collapsed: null };
  }

  /** The same text with every run of whitespace flattened, for the fuzzy pass. */
  function collapse(index) {
    if (index.collapsed) return index.collapsed;
    var out = "";
    var map = [];
    var previousWasSpace = false;
    for (var i = 0; i < index.text.length; i++) {
      var ch = index.text[i];
      if (ch === " " || ch === "\n" || ch === "\t" || ch === "\r" || ch === " ") {
        if (previousWasSpace) continue;
        out += " ";
        map.push(i);
        previousWasSpace = true;
      } else {
        out += ch;
        map.push(i);
        previousWasSpace = false;
      }
    }
    index.collapsed = { text: out, map: map };
    return index.collapsed;
  }

  function collapseString(value) {
    return value.replace(/[\s ]+/g, " ").trim();
  }

  function offsetOf(index, container, offset) {
    for (var i = 0; i < index.segments.length; i++) {
      if (index.segments[i].node === container) return index.segments[i].start + offset;
    }
    return null;
  }

  /** Turn what the reader selected into something worth storing. */
  function fromSelection(index, range) {
    var start = offsetOf(index, range.startContainer, range.startOffset);
    var end = offsetOf(index, range.endContainer, range.endOffset);
    if (start === null || end === null || end <= start) return null;

    // Trim the whitespace a drag-select usually picks up at the edges.
    while (start < end && /\s/.test(index.text[start])) start++;
    while (end > start && /\s/.test(index.text[end - 1])) end--;
    if (end - start < 2) return null;

    return {
      quote: index.text.slice(start, end),
      prefix: index.text.slice(Math.max(0, start - CONTEXT), start),
      suffix: index.text.slice(end, Math.min(index.text.length, end + CONTEXT)),
      text_position: start,
      start: start,
      end: end,
    };
  }

  function occurrences(haystack, needle) {
    var found = [];
    if (!needle) return found;
    var at = haystack.indexOf(needle);
    while (at !== -1 && found.length < 200) {
      found.push(at);
      at = haystack.indexOf(needle, at + 1);
    }
    return found;
  }

  function commonSuffixLength(a, b) {
    var n = 0;
    while (n < a.length && n < b.length && a[a.length - 1 - n] === b[b.length - 1 - n]) n++;
    return n;
  }

  function commonPrefixLength(a, b) {
    var n = 0;
    while (n < a.length && n < b.length && a[n] === b[n]) n++;
    return n;
  }

  /**
   * Where this anchor points now, or null if the passage is gone.
   *
   * The quote narrows it down, the surrounding words settle which occurrence,
   * and the stored position only breaks a remaining tie.
   */
  function resolve(index, anchor) {
    var starts = occurrences(index.text, anchor.quote);
    var length = anchor.quote.length;
    var exact = true;

    if (!starts.length) {
      // The wording survived but the whitespace did not, which is the usual
      // shape of a page that was re-rendered rather than rewritten.
      var flat = collapse(index);
      var wanted = collapseString(anchor.quote);
      var flatStarts = occurrences(flat.text, wanted);
      if (!flatStarts.length) return null;
      exact = false;
      starts = flatStarts.map(function (at) {
        return flat.map[at];
      });
      length = null;
      var ends = flatStarts.map(function (at) {
        return flat.map[Math.min(at + wanted.length - 1, flat.map.length - 1)] + 1;
      });
      return best(index, anchor, starts, ends, exact);
    }

    var exactEnds = starts.map(function (at) {
      return at + length;
    });
    return best(index, anchor, starts, exactEnds, exact);
  }

  function best(index, anchor, starts, ends, exact) {
    var scored = starts.map(function (start, i) {
      var end = ends[i];
      var before = index.text.slice(Math.max(0, start - CONTEXT), start);
      var after = index.text.slice(end, end + CONTEXT);
      var score =
        commonSuffixLength(before, anchor.prefix || "") +
        commonPrefixLength(after, anchor.suffix || "");
      if (typeof anchor.text_position === "number") {
        score += Math.max(0, 8 - Math.abs(start - anchor.text_position) / 500);
      }
      return { start: start, end: end, score: score };
    });
    scored.sort(function (a, b) {
      return b.score - a.score;
    });
    var winner = scored[0];
    var ambiguous = scored.length > 1 && scored[1].score >= winner.score - 1;
    return { start: winner.start, end: winner.end, exact: exact, ambiguous: ambiguous };
  }

  /** Paint a resolved range, one mark per text node it crosses. */
  function highlight(index, start, end, annotationId) {
    var touched = index.segments.filter(function (segment) {
      return segment.end > start && segment.start < end;
    });
    var marks = [];
    touched.forEach(function (segment) {
      var node = segment.node;
      if (!node.parentNode) return;
      var from = Math.max(start, segment.start) - segment.start;
      var to = Math.min(end, segment.end) - segment.start;
      if (to <= from) return;
      if (to < (node.nodeValue || "").length) node.splitText(to);
      if (from > 0) node = node.splitText(from);

      var mark = document.createElement("mark");
      mark.setAttribute("data-annotator-id", annotationId);
      mark.style.cssText =
        "background:rgba(224,180,0,.28);color:inherit;border-bottom:2px solid #e0b400;" +
        "border-radius:2px;cursor:pointer;padding:0;";
      node.parentNode.insertBefore(mark, node);
      mark.appendChild(node);
      marks.push(mark);
    });
    return marks;
  }

  function unhighlight(annotationId) {
    var marks = document.querySelectorAll('mark[data-annotator-id="' + annotationId + '"]');
    Array.prototype.forEach.call(marks, function (mark) {
      var parent = mark.parentNode;
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
      parent.removeChild(mark);
      parent.normalize();
    });
  }

  /**
   * The page as it was before we touched it.
   *
   * Painting a highlight rewrites the DOM, so capturing after painting stores
   * our own markup and gives the same unchanged page a different hash on every
   * annotation. Work on a clone: the reader keeps their highlights, and a page
   * that has not changed hashes the same however many notes are on it.
   */
  function capture() {
    var clone = document.documentElement.cloneNode(true);

    var ours = clone.querySelectorAll("[data-annotator-ui]");
    Array.prototype.forEach.call(ours, function (node) {
      node.parentNode.removeChild(node);
    });

    var marks = clone.querySelectorAll("mark[data-annotator-id]");
    Array.prototype.forEach.call(marks, function (mark) {
      var parent = mark.parentNode;
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
      parent.removeChild(mark);
      parent.normalize();
    });

    return clone.outerHTML;
  }

  return {
    CONTEXT: CONTEXT,
    buildIndex: buildIndex,
    fromSelection: fromSelection,
    resolve: resolve,
    highlight: highlight,
    unhighlight: unhighlight,
    capture: capture,
    collapseString: collapseString,
  };
})();

if (typeof module !== "undefined" && module.exports) module.exports = AnnotatorAnchor;
