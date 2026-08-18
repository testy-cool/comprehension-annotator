# Anchor annotations by quote and surrounding context, not by DOM path

An Annotation has to be findable again on a live page months later, after the
markup, the ads and the layout have all changed. We store the exact selected
text, roughly 32 characters of prefix and suffix, and a character offset into
the page text as a hint, following the W3C Web Annotation selector model that
Hypothesis uses. Anchoring by XPath or CSS path would be exact today and broken
on the next deploy of the site, and would also be meaningless against the stored
Snapshot whenever that differs from the live DOM.

## Consequences

Resolving an anchor is a search rather than a lookup, so it can return no match
or an ambiguous match. Both outcomes are expected and must be surfaced to the
reader rather than treated as errors. The exact-substring discipline inherited
from the VS Code FAQ annotator still applies to the quote itself: it is copied
verbatim, never reflowed or re-punctuated.
