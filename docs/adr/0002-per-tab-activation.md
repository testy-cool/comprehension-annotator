# The extension is dormant until a tab is switched into annotation mode

Reading happens in every tab, but annotating happens in a few. Rather than
running a content script on every page from a broad host permission, the
extension injects on demand when a tab is switched into annotation mode, using
activeTab and scripting. Nothing runs on banking or mail pages, ordinary
copy-paste selections raise no UI, and the switch into the mode is the natural
moment to take the Snapshot.

## Consequences

Annotating is never a single gesture from cold: noticing something worth
flagging costs one keystroke before the selection. That is the price of not
injecting everywhere, and it is accepted deliberately.
