# The extension is plain JavaScript with no bundler

The extension is loaded unpacked and edited directly, with no TypeScript, npm
install or build step, which is a deliberate departure from the TypeScript VS
Code annotator this project takes its cues from. It is possible only because the
heavy work sits in the sink: readable-text extraction, markdown conversion and
all file handling are Python, so the content script has no third-party
dependencies to bundle. The cost is no type checking across the three extension
surfaces, which is acceptable while they stay small.
