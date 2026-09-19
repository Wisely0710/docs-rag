# Answer-quality evaluation — `portfolio` corpus

- Golden set: `eval/qa/golden/portfolio.jsonl` — 36 questions (32 answerable, 4 unanswerable), k=6
- Corpus: `portfolio` under `eval/qa/.work` — 9 files / 128 chunks (head c3970ea)
- Answerer: deepseek / `deepseek-flash`
- Judges: primary deepseek / `deepseek-v4-pro`; secondary (cross-family) lmstudio / `qwen3-14b-mlx@8bit`
- Sampling: one run at temperature 0, no averaging; reference answers were written from the cited documents — method and limits in [`README.md`](README.md)

## Summary

| metric | value |
|---|---|
| questions | 36 (32 answerable, 4 unanswerable) |
| answer failures (not judged) | 0 |
| retrieval hit@6 (answerable) | 1.0 |
| answer accuracy — primary (strict) | 0.5938 |
| answer accuracy — primary (correct+partial) | 0.8438 |
| answer accuracy — secondary (strict) | 0.75 |
| judge agreement | 36 paired rows, 0.7778 agreement, kappa 0.5152 |
| abstention on unanswerable (marker / primary judge) | 1.0 / 1.0 |
| over-abstention on answerable | 0.1562 |
| answers with citations | 0.8611 |
| cited paths that exist in the corpus | 0.9565 |
| cited paths that were retrieved | 0.9565 |
| answers whose citations are all valid | 0.9355 |
| judge failures (primary / secondary) | 0 / 0 |
| answer latency p50 / p95 (ms) | 1569.9 / 2140.1 |
| tokens prompt+completion (answer) | 28451 + 6835 |
| tokens prompt+completion (judge primary) | 37451 + 17147 |
| tokens prompt+completion (judge secondary) | 35242 + 13639 |

By family:

| family | questions | answerable | retrieval hit@k | accuracy (primary) | abstention (unanswerable) |
|---|---|---|---|---|---|
| en | 30 | 27 | 1.0 | 0.5556 | 1.0 |
| zh | 6 | 5 | 1.0 | 0.8 | 1.0 |

## Per question

| id | family | retrieval | abstained | verdict (primary) | verdict (secondary) | citations | question |
|---|---|---|---|---|---|---|---|
| x402-1 | en | 3 | no | correct | correct | `docs/x402-agent-payments/README.md` | Why does the x402 stack not custody keys or send transactions? |
| x402-2 | en | 2 | yes | incorrect | correct | `docs/x402-agent-payments/README.md` | Which three HTTP headers make up the x402 v2 wire flow, and in which direction does each travel? |
| x402-3 | en | 1 | no | correct | correct | `docs/x402-agent-payments/verifier/README.md` | When does the verifier raise authorization_mismatch, and what should the server do about it? |
| x402-4 | en | 1 | no | correct | correct | `docs/x402-agent-payments/mcp/README.md`, `docs/x402-agent-payments/README.md` | How does the MCP payment bridge enforce the agent's spending cap? |
| x402-5 | en | 1 | no | partial | partial | `docs/x402-agent-payments/README.md` | What does scripts/demo.sh prove, and what does it need to run? |
| x402-6 | en | 1 | no | correct | correct | `docs/x402-agent-payments/README.md`, `docs/x402-agent-payments/mcp/README.md` | How many tests does each component of x402-agent-payments have, and what does the mcp suite cover end to end? |
| x402-7 | en | 1 | no | partial | correct | `docs/x402-agent-payments/README.md`, `docs/x402-agent-payments/verifier/README.md` | What happens to x402 v1 payloads in this stack, and why? |
| x402-8 | en | 1 | no | correct | correct | `docs/x402-agent-payments/client/README.md`, `docs/x402-agent-payments/verifier/README.md` | How does the browser client decide which token name and version to use for the EIP-712 domain? |
| x402-9 | en | 1 | no | correct | correct | `docs/x402-agent-payments/mcp/README.md`, `docs/x402-agent-payments/mcp/DESIGN.md` | Does the signature the MCP bridge creates move money? |
| x402-10 | en | 3 | no | correct | correct | `docs/x402-agent-payments/README.md` | Which x402 scheme and which networks does this stack implement? |
| x402-11 | zh | 1 | yes | incorrect | correct | — | verifier 為什麼對每個請求都重新做真正的密碼學驗證，而不是快取簽章？ |
| x402-12 | en | 2 | no | partial | partial | `docs/x402-agent-payments/verifier/README.md`, `docs/x402-agent-payments/README.md` | What boundary does the verifier keep between the x402 SDK and application code? |
| docsrag-1 | en | 1 | no | correct | correct | `docs/docs-rag/README.md`, `AGENTS.md` | How does docs-rag decide which documents belong to a corpus? |
| docsrag-2 | en | 1 | yes | incorrect | correct | `docs/docs-rag/README.md` | How does docs-rag combine its two rankers, and why that method? |
| docsrag-3 | en | 1 | no | correct | correct | `docs/docs-rag/README.md` | What happens to a document that is deleted or archived from a docs-rag corpus? |
| docsrag-4 | en | 1 | no | partial | incorrect | `docs/docs-rag/README.md` | What does the sync client do if another indexer holds the lock? |
| docsrag-5 | en | 3 | no | correct | correct | `docs/docs-rag/eval/README.md`, `eval/report-book.md`, `docs/docs-rag/README.md` | What is the retrieval evaluation's documented weak spot, with numbers? |
| docsrag-6 | en | 3 | no | correct | correct | `docs/docs-rag/README.md`, `docs/docs-rag/eval/README.md` | Why does the retrieval harness run offline in CI, and what does its gate check? |
| docsrag-7 | zh | 1 | no | correct | correct | `docs/docs-rag/README.md` | docs-rag 的 MCP 端點有認證機制嗎？部署時要注意什麼？ |
| docsrag-8 | en | 1 | no | partial | partial | `docs/docs-rag/README.md` | How does docs-rag meter queries, and can that metering fail a retrieval? |
| gg-1 | en | 1 | no | partial | partial | `docs/grounding-guard/README.md` | What exactly does grounding-guard check, and what does it deliberately not do? |
| gg-2 | en | 1 | no | correct | correct | `docs/grounding-guard/README.md` | Why does grounding-guard ground rounded textual forms of numbers on purpose? |
| gg-3 | en | 1 | no | correct | correct | `docs/grounding-guard/README.md` | How do label patterns work in grounding-guard, and why are they opt-in? |
| gg-4 | zh | 1 | no | correct | partial | `docs/grounding-guard/README.md` | grounding-guard 的 identifier 比對為什麼用 ASCII 邊界而不是單詞邊界？ |
| gg-5 | en | 1 | no | correct | correct | `docs/grounding-guard/README.md` | What rule of thumb does grounding-guard state about deterministic versus probabilistic checks? |
| lt-1 | en | 1 | no | partial | correct | `docs/llm-toolbox/README.md` | What do the five llm-toolbox examples teach? |
| lt-2 | zh | 1 | no | correct | correct | `docs/llm-toolbox/README.md` | llm-toolbox 的測試為什麼用 httpx.MockTransport 而不打真實 API？ |
| lt-3 | en | 2 | yes | incorrect | incorrect | `docs/llm-toolbox/README.md` | Which gates run in llm-toolbox CI, and on which Python versions? |
| lt-4 | en | 1 | no | correct | correct | `docs/llm-toolbox/README.md` | What does the hand-rolled agent loop in llm-toolbox demonstrate? |
| lt-5 | en | 1 | yes | incorrect | correct | `docs/llm-toolbox/README.md` | What is the documented limitation of the context-management example? |
| cmp-1 | en | 2 | no | partial | partial | `docs/x402-agent-payments/client/README.md`, `docs/x402-agent-payments/README.md`, `docs/x402-agent-payments/mcp/README.md`, `docs/docs-rag/eval/README.md`, `docs/docs-rag/README.md` | Which projects in this portfolio run offline — demo or tests — and how? |
| cmp-2 | zh | 1 | no | correct | correct | `docs/llm-toolbox/README.md`, `docs/x402-agent-payments/README.md` | 這個作品集哪些專案明講「官方 SDK 優先」？理由是什麼？ |
| out-en-1 | en | n/a | yes | correct | correct | — | How much revenue did the stock engine generate in 2025? |
| out-en-2 | en | n/a | yes | correct | correct | — | Which cloud provider hosts the production deployment of x402-agent-payments, and what does it cost per month? |
| out-en-3 | en | n/a | yes | correct | correct | — | What salary band does the portfolio author expect for a senior AI engineer position? |
| out-zh-1 | zh | n/a | yes | correct | correct | — | SafeRun 的代幣經濟採用哪一種銷毀機制？ |

## Failures (primary judge)

- `x402-2` (en, **incorrect**): Which three HTTP headers make up the x402 v2 wire flow, and in which direction does each travel?
  - answer: NOT_IN_CORPUS The excerpts name only two headers — `PAYMENT-REQUIRED` and `PAYMENT-SIGNATURE` (`docs/x402-agent-payments/README.md`) — and do not state a third header or the travel direction of any.
  - rationale: The candidate does not answer the question; it only states NOT_IN_CORPUS. It omits all three headers and their directions from the reference answer.
- `x402-5` (en, **partial**): What does scripts/demo.sh prove, and what does it need to run?
  - answer: `scripts/demo.sh` proves the whole payment flow end to end: a seller built on the real verifier is paid from the agent side, producing **402 → signed authorization → 200** (`docs/x402-agent-payments/README.md`). It needs to run: localhost o
  - rationale: Candidate conveys the 402→signed authorization→200 flow and localhost/no-chain/no-facilitator/no-real-key requirements, but omits that the first run creates .demo/venv with the x402 SDK and eth-account.
  - unsupported claims: The excerpts do not list any other runtime prerequisites
- `x402-7` (en, **partial**): What happens to x402 v1 payloads in this stack, and why?
  - answer: x402 **v1** payloads are rejected explicitly rather than half-accepted, because the stack's wire coverage is x402 v2 HTTP (`PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`), the `exact` scheme and CAIP-2 `eip155:*` networks only (`docs/x402-agent-pa
  - rationale: Candidate correctly states v1 payloads are rejected explicitly and the verifier raises invalid_version for non-v2 payloads, but omits the fail-closed rationale that unknown versions raise to give a clear error rather than partial success.
- `x402-11` (zh, **incorrect**): verifier 為什麼對每個請求都重新做真正的密碼學驗證，而不是快取簽章？
  - answer: NOT_IN_CORPUS 摘錄僅說明 verifier 會做 EIP-712 重建與 EOA 還原驗證，未提及不快取簽章的理由或任何快取設計。
  - rationale: 候選答案未提供原因，僅表示摘錄未提及；參考答案中無狀態驗證、無簽章/nonce 快取、每次真正密碼學重新驗證等關鍵事實完全缺失。
- `x402-12` (en, **partial**): What boundary does the verifier keep between the x402 SDK and application code?
  - answer: The verifier builds the 402 challenge (`PAYMENT-REQUIRED`) and verifies the client's `PAYMENT-SIGNATURE` using the official x402 SDK (EIP-712 / EIP-3009) (`docs/x402-agent-payments/verifier/README.md`, `docs/x402-agent-payments/README.md`).
  - rationale: The candidate describes the SDK-vs-policy boundary but omits the reference's key fact that application code never touches SDK types and the verifier returns a plain VerifiedPayment DTO with verified facts.
- `docsrag-2` (en, **incorrect**): How does docs-rag combine its two rankers, and why that method?
  - answer: NOT_IN_CORPUS The excerpts mention "score calibration between the two rankers" (`docs/docs-rag/README.md`) but do not describe the fusion method or its rationale.
  - rationale: Candidate fails to state reciprocal rank fusion of vector KNN and FTS5 trigram search or the score-calibration rationale, instead incorrectly declaring the answer absent from the corpus.
  - unsupported claims: NOT_IN_CORPUS
- `docsrag-4` (en, **partial**): What does the sync client do if another indexer holds the lock?
  - answer: `sync_corpus.sh` retries for up to a minute, then exits non-zero rather than reporting success — the corpus is synced but the index is not (`docs/docs-rag/README.md`).
  - rationale: Candidate correctly states the retry, non-zero exit, and corpus synced, but omits that the index catches up on the next run, saying only that the index is not synced.
- `docsrag-8` (en, **partial**): How does docs-rag meter queries, and can that metering fail a retrieval?
  - answer: Metering: each MCP tool call (`retrieve`, `corpus_status`) appends one line to `logs/queries-<corpus>.log` — the corpus is versioned by name (`docs/docs-rag/README.md`). The excerpts do not state whether metering failures affect retrieval.
  - rationale: Candidate correctly describes log line metering, but misses that the write is best-effort and never blocks or fails retrieval, so the second part is incomplete. The versioned-by-name claim is unsupported.
  - unsupported claims: the corpus is versioned by name (`docs/docs-rag/README.md`)
- `gg-1` (en, **partial**): What exactly does grounding-guard check, and what does it deliberately not do?
  - answer: `grounding-guard` is a deterministic post-generation check: it compares the **numbers** and **identifiers** in LLM-generated text against the `facts` you supply and reports every one that is **not** present there. If a number or symbol isn'
  - rationale: Correctly states it flags ungrounded numbers/identifiers as a pure no-LLM/no-I/O check, but omits key deliberate exclusions: schema/type validation, semantic entailment, prompt-injection defence, and ignoring identifiers over 6 characters.
- `lt-1` (en, **partial**): What do the five llm-toolbox examples teach?
  - answer: 五個範例對應 `docs/llm-toolbox/README.md` 所述的主題：structured output、tool calling、streaming、context 管理，以及手寫 agent loop。對應檔案為 `examples/01_structured_output.py`、`02_tool_calling.py`、`03_streaming.py`、`04_context_management.py`、`05_handrolled_agent.py
  - rationale: It lists the five topics and offline test setup, but omits the specific lessons from the reference: response_format/parsing guards, tool_call_id, finish_reason handling, context trimming/summarisation, and agent-loop convergence.
- `lt-3` (en, **incorrect**): Which gates run in llm-toolbox CI, and on which Python versions?
  - answer: NOT_IN_CORPUS The `docs/llm-toolbox/README.md` excerpt shown contains only the title, CI badge link, and design decisions — no list of gates or Python versions.
  - rationale: The candidate does not provide any of the requested gates or Python versions, only states the information is absent from the excerpt, omitting all key facts.
- `lt-5` (en, **incorrect**): What is the documented limitation of the context-management example?
  - answer: NOT_IN_CORPUS The excerpts only describe `04_context_management` (context budget trimming/summarization strategy, tested by pure functions) in `docs/llm-toolbox/README.md`; no limitation of it is documented.
  - rationale: The reference documents a specific limitation: the character-count budget is only a teaching proxy and should be replaced by a real tokenizer. The candidate denies any documented limitation, contradicting the reference.
  - unsupported claims: No limitation of the context-management example is documented
- `cmp-1` (en, **partial**): Which projects in this portfolio run offline — demo or tests — and how?
  - answer: Two projects: **x402-agent-payments** — offline demos and tests: - Client tests (`yarn test`) run the built `dist/` package against a `node:http` mock seller and stubbed `window.ethereum`: "real `fetch`, real header codec, no network, no ch
  - rationale: Candidate accurately covers x402-agent-payments and docs-rag offline behavior but omits llm-toolbox and grounding-guard, so the portfolio-wide answer is incomplete.
  - unsupported claims: Only two projects run offline (omits llm-toolbox and grounding-guard)

## Unanswerable questions (abstention behaviour)

| id | family | marker abstention | verdict (primary) | verdict (secondary) | answer |
|---|---|---|---|---|---|
| out-en-1 | en | yes | correct | correct | NOT_IN_CORPUS The excerpts contain no information about a stock engine or any revenue figures. |
| out-en-2 | en | yes | correct | correct | NOT_IN_CORPUS The excerpts do not mention any cloud provider hosting production or monthly hosting costs. |
| out-en-3 | en | yes | correct | correct | NOT_IN_CORPUS The excerpts contain no compensation or salary information for any role. |
| out-zh-1 | zh | yes | correct | correct | NOT_IN_CORPUS 提供的摘錄中完全沒有 SafeRun 或其代幣經濟／銷毀機制的相關內容。 |

## Judge disagreements

| id | primary | secondary | primary rationale | secondary rationale |
|---|---|---|---|---|
| x402-2 | incorrect | correct | The candidate does not answer the question; it only states NOT_IN_CORPUS. It omits all three headers and their directions from the reference answer. | Excerpts mention only PAYMENT-REQUIRED and PAYMENT-SIGNATURE; no third header or directions are documented. |
| x402-7 | partial | correct | Candidate correctly states v1 payloads are rejected explicitly and the verifier raises invalid_version for non-v2 payloads, but omits the fail-closed rationale that unknown versions raise to give a clear error rather than partial success. | Candidate correctly states v1 payloads are rejected explicitly, citing wire coverage from docs. Matches reference answer's key fact without contradiction. |
| x402-11 | incorrect | correct | 候選答案未提供原因，僅表示摘錄未提及；參考答案中無狀態驗證、無簽章/nonce 快取、每次真正密碼學重新驗證等關鍵事實完全缺失。 | Candidate correctly notes excerpts only mention cryptographic verification (EIP-712/EOA) but omit caching rationale. Reference answer's statelessness/replay logic isn't in excerpts, so candidate's 'NOT_IN_CORPUS' is accurate. |
| docsrag-2 | incorrect | correct | Candidate fails to state reciprocal rank fusion of vector KNN and FTS5 trigram search or the score-calibration rationale, instead incorrectly declaring the answer absent from the corpus. | Candidate correctly notes fusion method and rationale are absent in excerpts, aligning with reference answer's claims. |
| docsrag-4 | partial | incorrect | Candidate correctly states the retry, non-zero exit, and corpus synced, but omits that the index catches up on the next run, saying only that the index is not synced. | Candidate incorrectly claims index isn't synced, contradicting reference and excerpts which state index catches up on next run. |
| gg-4 | correct | partial | The candidate correctly states the ASCII-boundary rationale: CJK counts as word character, so \b misses identifiers glued to Chinese, while ASCII boundaries still match them. | Candidate correctly explains ASCII boundary use but incorrectly attributes regex behavior to Python, while excerpts only mention regex generally. |
| lt-1 | partial | correct | It lists the five topics and offline test setup, but omits the specific lessons from the reference: response_format/parsing guards, tool_call_id, finish_reason handling, context trimming/summarisation, and agent-loop convergence. | Candidate correctly identifies five examples matching the README's topics and files, aligning with reference answer's core concepts. |
| lt-5 | incorrect | correct | The reference documents a specific limitation: the character-count budget is only a teaching proxy and should be replaced by a real tokenizer. The candidate denies any documented limitation, contradicting the reference. | Candidate correctly notes no limitation is documented in the excerpts, aligning with the provided texts. |

## Spot-check

Spot-check by the coding agent that built this harness (an LLM review, not a human expert; the reviewer also wrote the reference answers, so it checks judge behaviour rather than reference validity). Eight rows were re-read against the retrieved excerpts and the reference: the primary judge's verdict matched the reviewer's reading in 8/8; the secondary judge's matched in 5/8, lenient on rows where the candidate abstained or listed topics without the reference's specifics (x402-2, lt-1) and harsh on one partial (docsrag-4).

| id | judge verdict (primary) | reviewer | note |
|---|---|---|---|
| x402-2 | incorrect | agree (primary); secondary lenient | Answerable question, so the abstention is a system failure: incorrect is right. The secondary judge graded the same abstention correct. |
| x402-3 | correct | agree | Answer matches the reference; both judges correct. |
| x402-5 | partial | agree | Flow and no-chain requirement covered; the omitted .demo/venv detail justifies partial. |
| docsrag-4 | partial | agree (primary); secondary harsh | Retry + non-zero exit correct; the closing clause misstates the index catch-up, so partial is right — the secondary judge's incorrect over-reads it as fabrication. |
| docsrag-7 | correct | agree | Complete zh answer with correct extra deployment detail (single-writer lock). |
| gg-1 | partial | agree | The second half of the question (deliberate non-goals) is missing; partial. |
| lt-1 | partial | agree (primary); secondary lenient | Topics listed, per-example mechanics missing; partial. The answer also switched to Chinese for an English question. |
| cmp-1 | partial | agree | Only 2 of the 4 projects covered; partial. |

## Indexer output

```
(skipped)
```
