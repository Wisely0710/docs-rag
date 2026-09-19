# docs-rag

Local, dependency-light retrieval over a repository's **current** documentation, exposed
to coding agents as an MCP server.

The design premise is simple: an agent that greps a repository finds whatever is on disk —
including archived plans and superseded designs. A docs-RAG corpus instead indexes a
*declared scope* (which files, which trees), and re-indexes incrementally so that removing
or archiving a document removes it from retrieval too. The index is a single SQLite file
per corpus; there is no vector database, no framework and no service dependency beyond an
embeddings endpoint.

```
corpus/            markdown (mirrored or git-cloned — see "Corpus config")
data-<corpus>/     index.sqlite  (+ .index.lock)
```

## What it does

- **Declared corpus scope** — a corpus is data (`corpora.json`): top files, docs-root files,
  recursive trees, and directory names to exclude. Nothing tenant-specific lives in code.
- **Incremental indexing** — sha256 per file; only changed files are re-chunked and
  re-embedded, deleted files are purged from the index.
- **Section-aware chunking** — markdown headings start sections; paragraphs are atomic;
  sections merge up to a character budget and oversized ones are split on line boundaries
  with a sliding overlap.
- **Hybrid retrieval** — vector KNN (`sqlite-vec`, with a numpy brute-force fallback) is
  fused with FTS5 trigram full-text search via reciprocal rank fusion (k=60). RRF needs no
  score calibration between the two rankers.
- **MCP tools** — `retrieve(query, k)` and `corpus_status()` over streamable HTTP, so any
  MCP-capable agent can query the corpus; `ragquery.py` does the same from a shell.
- **Query metering** — every tool call appends one line to `logs/queries-<corpus>.log`
  (best-effort; never blocks retrieval).

## Quickstart (no model server required)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
bash demo.sh          # builds a synthetic corpus in a temp dir, indexes it, queries it
```

> Intel (x86_64) macOS: the latest `cryptography` wheel release has no x86_64 build;
> pin it explicitly — `pip install 'cryptography==48.0.1' -r requirements.txt -r requirements-dev.txt`.

`demo.sh` sets `RAG_EMBED_BACKEND=stub`, a deterministic hashed bag-of-tokens embedding, so
the whole pipeline runs offline. It writes nothing outside a `mktemp` directory.

For real use, point the service at an OpenAI-compatible embeddings endpoint (LM Studio by
default) and create a corpus config:

```bash
cp corpora.example.json corpora.json          # edit scope/paths; keep it untracked
export RAG_CORPUS=example                     # mandatory: the service refuses to guess
.venv/bin/python indexer.py                   # build/refresh the index
.venv/bin/python ragquery.py -k 4 <<< "how does retrieval fuse the two rankers?"
.venv/bin/python serve.py                     # MCP server (RAG_PORT, default 8765)
```

Environment: `RAG_DIR` (default `~/rag-service`; override per deployment) positions `corpora.json`, `.env`, corpora and
indexes; `RAG_CORPUS` selects the corpus; `RAG_CORPUS_DIR`, `RAG_HOST`, `RAG_PORT`,
`RAG_SERVER_NAME`, `RAG_SYSTEM_NOTE`, `RAG_MCP_TRANSPORT` and `RAG_EMBED_BACKEND` override
defaults. `.env` may hold `LMSTUDIO_API_KEY` / `LMSTUDIO_BASE_URL` / `EMBED_MODEL`.

## Corpus config

`corpora.example.json` documents the schema; the keys that matter:

| Key | Meaning |
|-----|---------|
| `corpus_dir` | where the markdown lives |
| `data_dir` | where `index.sqlite` is written |
| `top_files` | markdown at the corpus root (`AGENTS.md`) |
| `doc_root_files` | markdown at the root of the **docs tree**, i.e. `<corpus_dir>/docs/<name>` |
| `roots` | directories scanned recursively for `*.md` |
| `exclude_dirs` | directory names skipped anywhere inside `roots` (`archive`) |
| `server_name`, `system_note` | optional MCP presentation |
| `git_origin_repo` | optional: a local checkout whose git origin `refresh.sh` clones from |

Only `*.md` is indexed. A missing entry is skipped rather than failing, so a typo shrinks the
corpus silently — check `corpus_status()` after editing the config.

## Refresh and deployment

`refresh.sh <corpus> [git-ref]` re-fetches a git-backed corpus (when `git_origin_repo` is
set) and re-indexes; for a mirror-style corpus the content is pushed by the owning
repository, so nothing is fetched here. Run it per corpus from cron, e.g.

```
0 * * * * /path/to/docs-rag/refresh.sh example >/dev/null 2>&1
```

`deploy/com.example.docs-rag.plist` is a launchd template for one corpus instance; replace
the placeholders and bootstrap it per corpus (`RAG_CORPUS` and `RAG_PORT` differ per agent).

## Clients

Two shell clients ship with the service so a consuming repository does not have to
re-implement the protocol, plus the QA entry point:

| Script | Purpose |
|--------|---------|
| `client/sync_corpus.sh` | push a local documentation tree into a corpus mirror and re-index it |
| `client/query.sh` | run a retrieval from the shell (read-only; same path as the MCP tool) |
| `qa/ask.py` | ask a question and print a cited answer built on the retrieval path (needs a chat endpoint; measured by [`eval/qa/`](eval/qa/README.md)) |

The two client scripts read the corpus scope from the **service's** config at run time, so
they keep no second copy of it — a scope change on the service side cannot silently drift
from what is pushed.
`sync_corpus.sh` also guards its target: it refuses any `--remote-dir` that is not exactly
`<service-dir>/corpus/<corpus>`, because the transfer uses `--delete` and a typo must not be
able to overwrite another corpus. `--dry-run` prints the payload and changes nothing (it
still reads the scope from the service, so the host must be reachable). If another indexer
holds the lock — e.g. the service-side cron — `sync_corpus.sh` retries for up to a minute
and then exits non-zero instead of reporting success: the corpus is synced, the index
catches up on the next run.

```bash
./client/sync_corpus.sh --corpus example --source ~/src/my-repo \
    --host rag-host --service-dir /srv/docs-rag
./client/query.sh --corpus example --query "how does retrieval fuse the two rankers?" \
    --host rag-host --service-dir /srv/docs-rag
```

## Evaluation

`eval/` measures retrieval quality against a labelled query set: the real indexer
builds the index, the real `retrieve` path answers, and the harness reports recall@k,
MRR and latency. The published run uses [`rust-lang/book`](https://github.com/rust-lang/book)
(112 markdown files, commit pinned in the report) with `text-embedding-nomic-embed-text-v1.5`:

| family | queries | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|
| en | 41 | 0.8537 | 0.9756 | 1.0 | 0.9154 |
| zh (informational) | 6 | 0.1667 | 0.1667 | 0.3333 | 0.2083 |
| all | 47 | 0.766 | 0.8723 | 0.9149 | 0.8252 |

Cross-lingual retrieval (Chinese question, English corpus) is the clear weak spot. The
per-query table, the misses and the error analysis live in [`eval/report-book.md`](eval/report-book.md)
and [`eval/README.md`](eval/README.md); reproduce with:

```bash
./eval/fetch_corpus.sh
.venv/bin/python eval/run_eval.py --rag-dir eval/.work --corpus book \
    --golden eval/golden/book.jsonl --k 10 --backend lmstudio --fresh --report eval/report-book.md
```

CI runs the harness offline on a fixture corpus (stub embeddings) with a `--min-recall`
gate, so a metric computation or label-loading regression fails the build without a
model server.

### Answer quality (2026-09-19)

The QA layer answers from the retrieved excerpts with citations and is scored by two
judges — `deepseek-v4-pro` and, cross-family, `qwen3-14b-mlx@8bit` — against a 36-question
labelled set over the portfolio's own public documentation. Method and error analysis:
[`eval/qa/README.md`](eval/qa/README.md); full report: [`eval/qa/report-portfolio.md`](eval/qa/report-portfolio.md).

| metric | value |
|---|---|
| answer accuracy — strict / correct+partial | 0.5938 / 0.8438 |
| off-corpus questions answered by abstention | 4/4 |
| retrieval hit@6 (answerable) | 1.0 |
| judge agreement (kappa) | 0.7778 (0.5152) |
| cited paths that exist in the corpus | 0.9565 |

The gap between the two accuracies is the story: the right *documents* were always
retrieved, but for 5 of 32 questions the answer-bearing *passage* was not among the
top-6 excerpts, so the model declined instead of guessing; a k=10 diagnostic does not
recover them (chunk boundaries, and en→zh / zh→en cross-lingual cases). CI runs the same
harness offline with stub chat backends and `--min-accuracy` / `--min-citation-validity`
gates.

## What it does not do

- No reranking, no query rewriting, no LLM in the retrieval path — ranking is deterministic.
  (The QA layer adds an LLM *on top* of retrieval — answers and their evaluation live in
  `qa/` and `eval/qa/` and never feed back into ranking.)
- Markdown only: no PDF, HTML, code-symbol or image ingestion.
- The MCP endpoint has **no authentication**: expose it only on a trusted network or overlay.
- Single-host, single-writer: the indexer takes a lock; concurrent indexing of one corpus is
  skipped rather than queued.
- No deletion of corpora, no index migration between schema versions (delete `index.sqlite`
  and re-index when the schema changes).

## Development

```bash
.venv/bin/ruff check .            # lint
.venv/bin/mypy                    # type check (config in pyproject.toml)
.venv/bin/python -m pytest        # tests (unit + end-to-end, no network)
.venv/bin/shellcheck client/*.sh  # shell check for the clients
.venv/bin/pre-commit run --all-files  # secret scan (baseline: .secrets.baseline)
```

CI runs the same gates, plus `shellcheck` on the client scripts and the `detect-secrets` scan
(`.github/workflows/ci.yml`); install the commit hook once with `pre-commit install`.
Licensed under MIT.
