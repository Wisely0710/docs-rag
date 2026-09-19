"""QA layer: ask a docs-rag corpus a question and get a cited answer.

`qa.answer` builds the prompt from retrieved excerpts and extracts citations;
`qa.judge` (used by the evaluation harness) scores answers; `qa.ask` is the CLI.
None of it sits in the retrieval path — retrieval stays deterministic and model-free.
"""

from __future__ import annotations
