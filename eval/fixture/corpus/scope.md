# Corpus scope

A corpus is data: corpora.json declares which files and trees are indexed and which
directory names are excluded. Nothing tenant-specific lives in code, RAG_CORPUS is
mandatory, and a missing required key fails loudly instead of serving some other corpus.
