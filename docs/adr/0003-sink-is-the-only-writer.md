# The sink is the only process that writes to the library

Every file under the library is written by the sink and by nothing else. The
extension sends intents over HTTP and never touches disk; agents and future
review tools read freely but submit changes through the same endpoints. This is
the discipline that already works in the FAQ annotator, where merge_suggestions.py
owns the review files and the agent is forbidden from editing them directly, and
it is what keeps a human annotation and an agent suggestion from racing each
other into the same file.

## Consequences

Writes are serialised through one process, so a temp-file-and-rename is enough
and no locking is needed. The sink must be running for anything to reach disk,
which is why the extension queues locally first.
