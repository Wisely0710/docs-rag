# Answer-quality evaluation

The [retrieval harness](../README.md) measures whether the right documents are found.
This one measures whether the answers built on top of them are *right*: `qa/answer.py`
answers from the retrieved excerpts with citations, and this harness scores every answer
with one or two LLM judges against a reference answer.

Two ideas shape the design:

- **The reference answers are the golden set.** Each row names the documents that should
  answer it, and the reference answer was written from those documents (the label check
  in `--golden` loading makes a typo visible instead of silently scoring it).
- **Judges are measured, not trusted.** The primary judge grades every row; an optional
  second judge from a *different model family* grades the same rows, and the report
  includes their agreement (percent + Cohen's kappa). A human spot-check of a sample can
  be embedded in the report afterwards (`--spotcheck`), because judges agreeing with each
  other is not the same thing as judges agreeing with a person.

## Corpus

The published results use the **portfolio corpus**: the public documentation of the four
public repositories — `x402-agent-payments`, `grounding-guard`, `llm-toolbox` and
`docs-rag` itself — 9 markdown files / 128 chunks. `fetch_corpus.sh` mirrors each
repository's `*.md` tree (excluding virtualenvs, caches, eval fixtures and generated
reports) under `corpus/portfolio/docs/<repo>/`, and records the resolved commit of every
repository in `.corpus_source.json`, so a report is tied to the revisions it ran against.

```bash
./eval/qa/fetch_corpus.sh                # -> eval/qa/.work (corpus + corpora.json)
```

`eval/qa/.work/` is gitignored: the checkouts and the index are build artefacts, not
repository content. Re-running the script re-clones the repositories, so a later run can
drift to newer commits — the report's `.corpus_source.json` marker is the record of what
a given run saw.

## Golden set

`golden/portfolio.jsonl` — one JSON object per line:

| field | meaning |
|---|---|
| `id` | stable identifier used in results |
| `family` | language of the question (`en`, `zh`) |
| `question` | the question handed to the system |
| `reference` | the answer the judges compare against |
| `expected_docs` | corpus documents that should answer it (retrieval hit rate is reported) |
| `evidence` | optional string that must occur in an expected document — a label sanity check |
| `unanswerable` | `true` for questions deliberately outside the corpus: no reference; the correct behaviour is abstention |

`unanswerable` rows measure the behaviour documentation systems most often get wrong:
inventing an answer. They are graded on whether the system declines instead.

Reference answers were written from the cited documents and live in the repository, so
anyone can check them against the corpus. They are a labelled yardstick, not an
authority: disagreements between the reference and a better answer surface in the
report as judge verdicts, not as hidden truth.

## Running

With real models (the published configuration): responses from the DeepSeek API, the
secondary judge on a local LM Studio server.

```bash
export LMSTUDIO_BASE_URL=http://<host>:1234/v1 LMSTUDIO_API_KEY=<token>   # embeddings + judge 2
export DEEPSEEK_API_KEY=<key>                                            # answerer + judge 1
.venv/bin/python eval/qa/run_qa_eval.py --rag-dir eval/qa/.work --corpus portfolio \
    --golden eval/qa/golden/portfolio.jsonl --k 6 --embed-backend lmstudio \
    --answer-backend deepseek --answer-model deepseek-flash --answer-max-tokens 800 \
    --judge-backend deepseek --judge-model deepseek-v4-pro --judge-max-tokens 2000 \
    --judge2-backend lmstudio --judge2-model qwen3-14b-mlx@8bit --judge2-max-tokens 2500 \
    --report eval/qa/report-portfolio.md --json eval/qa/report-portfolio.json
```

Fully offline (stub chat backends — plumbing checks only, the numbers are not
meaningful; this is what CI runs on the `fixture/` corpus):

```bash
rm -rf /tmp/qa-fixture && cp -r eval/qa/fixture /tmp/qa-fixture
.venv/bin/python eval/qa/run_qa_eval.py --rag-dir /tmp/qa-fixture --corpus qa-fixture \
    --golden eval/qa/fixture/golden.jsonl --k 3 --embed-backend stub \
    --answer-backend stub --judge-backend stub --min-accuracy 0.9 --min-citation-validity 0.9
```

Notes:

- The indexer runs with the rest of the harness unless `--no-reindex` is given; switching
  embedding backends needs `--fresh`.
- Reasoning models emit reasoning tokens *before* any content, so every budget matters:
  `--answer-max-tokens` (default 800), `--judge-max-tokens` (default 2000) and
  `--judge2-max-tokens` (default 2500). A reply that contains only reasoning is recorded
  as a failed row (never as an empty answer), so one serving hiccup cannot throw away a run.
- `--render-from <json>` re-renders the report (and attaches a `--spotcheck` file)
  without re-running the models.
- `--min-accuracy` / `--min-citation-validity` turn the run into a gate (non-zero exit).

## Metrics

| metric | meaning |
|---|---|
| retrieval hit@k | share of answerable questions whose expected document is in the top-k excerpts |
| accuracy (primary, strict / lenient) | share of judged rows graded `correct` / `correct`+`partial` |
| accuracy (secondary) | the same by the cross-family judge |
| judge agreement | rows both judges scored, agreement share and Cohen's kappa |
| abstention on unanswerable | share of unanswerable rows the system declined (marker) / the primary judge accepted the refusal |
| over-abstention on answerable | share of answerable rows the system wrongly declined |
| citations | answers with ≥1 citation; cited paths that exist in the corpus; cited paths that were retrieved; answers whose every citation is valid |
| judge failures | rows whose judge reply could not be parsed (or the call failed) |
| latency, tokens | answer latency percentiles; prompt/completion tokens per role |

Retrieval hit@k is the bridge to the retrieval report: an answer can only be as good as
the excerpts it saw, so the report keeps both numbers side by side.

## Results (2026-09-19)

One run: answerer `deepseek-flash`, primary judge `deepseek-v4-pro`, secondary judge
`qwen3-14b-mlx@8bit` on a local LM Studio server (cross-family), k=6, temperature 0.
Per-question detail, the judge disagreements and the spot-check: [`report-portfolio.md`](report-portfolio.md).

| metric | value |
|---|---|
| questions | 36 (32 answerable, 4 unanswerable) |
| answer failures (not judged) | 0 |
| retrieval hit@6 (answerable) | 1.0 |
| accuracy — primary (strict) | 0.5938 |
| accuracy — primary (correct+partial) | 0.8438 |
| accuracy — secondary (cross-family, strict) | 0.75 |
| judge agreement | 36 rows, 0.7778 agreement, kappa 0.5152 |
| abstention on unanswerable | 1.0 (4/4) |
| over-abstention on answerable | 0.1562 (5/32) |
| citations: answers with / all paths valid / paths retrieved | 0.8611 / 0.9565 / 0.9565 |
| answer latency p50 / p95 (ms) | 1569.9 / 2140.1 |
| tokens prompt+completion (answer / judge 1 / judge 2) | 28451+6835 / 37451+17147 / 35242+13639 |

### Reading the numbers

- **Every expected document was retrieved; 19/32 answers were strictly right.** The gap is
  not the retriever's top-k: five questions were answered *by abstention* because the
  passage holding the answer was not among the six excerpts, and eight more answers were
  `partial` — typically the right topic with some of the reference's specifics missing.
  Lenient scoring (correct+partial) is 0.8438.
- **Off-corpus questions were never hallucinated.** All four `unanswerable` rows were
  declined, including one that names a real project from the corpus (`out-en-2`) — the
  tempting shape.
- **The judges disagree systematically, and the report shows where.** Agreement 0.7778,
  kappa 0.5152. The cross-family judge is lenient exactly where the candidate abstained on
  an answerable question (x402-2, x402-11, docsrag-2, lt-5) or listed topics without the
  reference's mechanics (lt-1), and harsh on one partial that misstated a detail
  (docsrag-4) — it grades faithfulness to the excerpts where the primary judge grades
  agreement with the reference. The spot-check of eight rows sided with the primary judge
  in 8/8.
- **Citations hold up.** 31/36 answers carry citations; 44/46 cited paths exist in the
  corpus (the two exceptions quote schema examples, `AGENTS.md` and `eval/report-book.md`),
  and every cited path was among the retrieved excerpts.
- **zh rows scored higher than en rows** (0.8 vs 0.5556): four of the five zh questions
  target documents whose own text is Chinese (grounding-guard's summary, llm-toolbox's
  README), so retrieval had lexical overlap — the reverse of the cross-lingual weakness
  the retrieval report flags.

### Error analysis

**Passage-level retrieval misses (5 abstentions — the answers were right to decline):**

| id | what the excerpts lacked | why |
|---|---|---|
| x402-2 | the header table (`mcp/DESIGN.md`); only two of three headers surfaced | the table chunk does not rank in this query's top 10 |
| x402-11 | the "stateless verification / no cache" paragraph | Chinese question over an English document (the known cross-lingual weakness) |
| docsrag-2 | the RRF sentence | a chunk boundary splits it — only its tail surfaced |
| lt-3 | the CI-gates section | English question over a Chinese document: en→zh, the direction the retrieval report never measured |
| lt-5 | the pitfalls section | same en→zh pattern |

A k=10 diagnostic recovered none of the five: the fix is ranking and chunking, not a
larger k. It is also the sharpest evidence yet for the retrieval report's own caveat —
*file-level labels: a hit means the right document, not the right passage*.

**Incomplete answers (8 partials)** — one consistent shape: the topic is covered but the
reference's specifics are dropped (gg-1 omits the "does not do" list; lt-1 lists topics
without the per-example mechanics; cmp-1 covers 2 of 4 projects; x402-5 omits the
`.demo/venv` setup). Two answers switched to Chinese for English questions (docsrag-1,
lt-1) despite the prompt's language rule, and two asserted claims the excerpts do not
support (`docsrag-8`: "the corpus is versioned by name").

## Limits

- **One run, one configuration.** Temperature 0, no averaging over repetitions, one
  answerer and one judge pair as recorded in the report header. Treat the numbers as a
  snapshot, not a benchmark.
- **Strict accuracy counts system failures as answer failures.** When the answer-bearing
  passage is not retrieved, a well-behaved model declines and the primary judge grades the
  row `incorrect` — the question *was* answerable. `over-abstention` and the failure
  analysis exist to separate those rows from genuine answer-quality problems; the
  secondary judge sometimes grades the same rows `correct` by an excerpts-only rubric,
  which is itself part of what the agreement number measures.
- **The reference answers are the measuring stick.** They were written from the cited
  documents, but a reference answer that is itself incomplete would penalise a *better*
  answer; the judge rubrics reduce this (a more precise answer still reads as `correct`)
  but do not remove it.
- **Judge noise is real.** Same-family judges share failure modes; the cross-family judge
  and the kappa statistic make the noise visible rather than removing it. The kappa value
  is computed over the verdict labels, so a run that is uniformly graded `correct` shows
  kappa 1.0 by construction — a high kappa with degenerate labels is not evidence of a
  good judge.
- **Small corpus, small golden set.** Nine documents and 36 questions say nothing about
  behaviour on large or adversarial corpora.
- **`zh` rows are informational.** The corpus is mostly English; Chinese questions
  exercise the cross-lingual path that the retrieval report already flags as weak.
