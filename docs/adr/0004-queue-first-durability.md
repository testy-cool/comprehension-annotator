# Annotations are written to the local queue before they are sent

An annotation is saved into chrome.storage.local first and only then flushed to
the sink, rather than being sent directly with the queue as a fallback. Reading
happens for months and the sink will not always be running; the failure mode
that matters is losing a note you already typed, not delaying its arrival on
disk. The queue is drained on every new annotation, on a periodic alarm, and
whenever the sink comes back, and the pending count is shown on the toolbar
badge so a silently dead sink cannot hide.

## Consequences

The extension needs unlimitedStorage, because a queued item carries the page
HTML. An annotation can exist in two places at once, so every queued item
carries a client-generated id and the sink treats submissions as idempotent.
