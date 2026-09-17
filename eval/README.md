# Evaluation

The service ships a retrieval-quality harness: `run_eval.py` indexes a corpus through
the real `indexer.py`, answers a labelled query set through the real
`searchlib.retrieve`, and reports recall@k, MRR and query latency. Everything the
report claims can be reproduced with the commands below.

## Corpus

The published results in [`report-book.md`](report-book.md) use
[`rust-lang/book`](https://github.com/rust-lang/book) — 112 markdown files (~1.2 MB),
a real documentation tree that anyone can fetch. `fetch_corpus.sh` clones it, mirrors
the `*.md` tree into a self-contained `RAG_DIR`, and records the resolved commit in
`.corpus_source.json`, so a report is tied to one commit:

```bash
./eval/fetch_corpus.sh                      # -> eval/.work (corpus + corpora.json)
```

`eval/.work/` is gitignored: the corpus checkout and the index are build artefacts,
not repository content.

## Golden set

`golden/book.jsonl` — one JSON object per line:

| field | meaning |
|---|---|
| `id` | stable identifier used in results |
| `query` | the question handed to the retriever |
| `expected` | corpus-relative path of the document that should answer it |
| `family` | grouping for reporting (`en`, `zh`) |
| `evidence` | optional string that must occur in `expected` — a cheap label sanity check |

Labels are file-level, not passage-level: a hit means the right *document* is in the
top-k, not that the right paragraph was ranked first. The harness prints a warning for
any row whose expected file is missing from the corpus or whose `evidence` string is
absent, so a typo cannot silently deflate the scores.

The set covers 41 English queries (one per chapter target across the whole book) and 6
Chinese probes. The probes are informational: they measure the cross-lingual case
(Chinese question, English corpus), not a claim about a Chinese corpus.

## Running

With a model server (OpenAI-compatible embeddings endpoint, the deployment default):

```bash
export LMSTUDIO_BASE_URL=http://<host>:1234/v1 LMSTUDIO_API_KEY=<token>
.venv/bin/python eval/run_eval.py --rag-dir eval/.work --corpus book \
    --golden eval/golden/book.jsonl --k 10 --backend lmstudio --fresh \
    --report eval/report-book.md --json eval/report-book.json
```

Fully offline (stub embeddings, for plumbing checks — the numbers are not meaningful):

```bash
.venv/bin/python eval/run_eval.py --rag-dir eval/.work --corpus book \
    --golden eval/golden/book.jsonl --k 10 --backend stub --fresh
```

`--fresh` deletes the index first; use it whenever the embedding backend changes,
because the indexer only re-embeds files whose content hash changed. `--min-recall`
turns the run into a gate (non-zero exit below the threshold); CI uses it with the
`eval/fixture/` corpus, `--backend stub` and no model server.

## Published results (2026-09-17)

`text-embedding-nomic-embed-text-v1.5`, 768-d, 112 files / 4029 chunks; full per-query
table and misses in [`report-book.md`](report-book.md):

| family | queries | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|
| en | 41 | 0.8537 | 0.9756 | 1.0 | 0.9154 |
| zh (informational) | 6 | 0.1667 | 0.1667 | 0.3333 | 0.2083 |
| all | 47 | 0.766 | 0.8723 | 0.9149 | 0.8252 |

### Reading the numbers

- **English retrieval is solid**: every one of the 41 English queries lands the right
  document inside the top 5 (recall@5 = 1.0); ~85% are already first.
- **Cross-lingual is the weak spot**: Chinese questions against an English corpus hit
  the right document only 2/6 times (one at rank 1, one at rank 4). The FTS ranker
  contributes nothing across languages, so the result rides on the vector model alone —
  and `nomic-embed-text-v1.5` is English-centric. A multilingual embedding model, a
  translation step at ingest or query time, or a Chinese-query-to-English-expansion
  layer would be the fixes; none is implemented.
- **Index-like documents win title-shaped queries**: `SUMMARY.md` (the book's table of
  contents, which contains every chapter title) is the top-1 hit for a query that
  paraphrases a chapter title. Real deployments with a TOC or an index page should
  exclude it from the corpus scope or expect to compete with it.
- **Concepts that span chapters diffuse**: `match` and `if let` rank the general
  patterns chapter (`ch19`) first; `Arc`+`Mutex` ranks the multithreaded-server chapter
  first. The right document is in the top 3, but the top-1 is a neighbouring chapter
  that covers the same language feature with a longer example.
- **Latency is indicative only**: p50 ≈ 0.1–0.2 s per query (one embedding call plus
  two SQLite scans) measured against a shared single model server from a client over a
  private network; treat it as an order of magnitude, not a benchmark.

### Limits

- One corpus and one embedding model; results do not transfer to other corpora or
  models without re-running.
- File-level labels: a hit means the right document, not the right passage.
- No reranker and no query rewriting are in the retrieval path by design, so recall@1
  is bounded by what the two rankers propose; recall@k is the more stable signal.
- The golden set is hand-written; the `evidence` check makes labels plausible, not
  definitive — e.g. “rules for mutable references” legitimately touches more than the
  chapter the label points at.
