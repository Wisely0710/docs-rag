# Indexing

The indexer compares a sha256 per file against the index and re-chunks only changed
files; documents that left the declared scope are deleted from the index together with
their full-text and vector rows. One indexer at a time runs per corpus — a lock
directory makes a concurrent run skip instead of queueing.
