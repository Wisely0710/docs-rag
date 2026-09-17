# Retrieval evaluation — `book` corpus

- Golden set: `eval/golden/book.jsonl` (47 labelled queries, k=10)
- Corpus: `book` under `eval/.work` — 112 files / 4029 chunks (head 1500248d)
- Embeddings: text-embedding-nomic-embed-text-v1.5 (lmstudio backend), 768-d; ranking: vector KNN + FTS5 trigram fused with RRF (k=60)

## Summary

| metric | value |
|---|---|
| recall@1 | 0.766 |
| recall@3 | 0.8723 |
| recall@5 | 0.9149 |
| MRR@10 | 0.8252 |
| latency p50 (ms) | 99.1 |
| latency p95 (ms) | 303.4 |

By family:

| family | queries | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|
| en | 41 | 0.8537 | 0.9756 | 1.0 | 0.9154 |
| zh | 6 | 0.1667 | 0.1667 | 0.3333 | 0.2083 |

## Per query

| id | family | rank | top-1 result | query |
|---|---|---|---|---|
| own-1 | en | 1 | `docs/book/ch04-01-what-is-ownership.md` | How does Rust manage memory without a garbage collector - stack versus heap? |
| own-2 | en | 5 | `docs/book/ch15-04-rc.md` | What are the rules for mutable references and how does borrowing prevent data races? |
| own-3 | en | 1 | `docs/book/ch04-03-slices.md` | How do string slices and the slice type let a function accept parts of a string? |
| var-1 | en | 1 | `docs/book/ch03-01-variables-and-mutability.md` | Variables are immutable by default: how do I make one mutable, and what is shadowing? |
| type-1 | en | 1 | `docs/book/ch03-02-data-types.md` | Which scalar and compound data types exist, including tuples and arrays? |
| ctrl-1 | en | 1 | `docs/book/ch03-05-control-flow.md` | How do if expressions plus loop, while and for control flow work? |
| game-1 | en | 1 | `docs/book/ch02-00-guessing-game-tutorial.md` | Walk through the guessing game: secret number, the rand crate and reading input |
| struct-1 | en | 1 | `docs/book/ch05-01-defining-structs.md` | How do I define a struct and use field init shorthand? |
| method-1 | en | 2 | `docs/book/ch10-02-traits.md` | How does method syntax work with impl blocks and a self parameter? |
| enum-1 | en | 1 | `docs/book/ch06-01-defining-an-enum.md` | How do I define an enum whose variants hold data, like IpAddrKind? |
| match-1 | en | 2 | `docs/book/ch19-01-all-the-places-for-patterns.md` | How does a match expression handle every case and what is the catch-all pattern? |
| iflet-1 | en | 2 | `docs/book/ch19-01-all-the-places-for-patterns.md` | How do I handle a single pattern concisely with if let? |
| mod-1 | en | 1 | `docs/book/ch07-02-defining-modules-to-control-scope-and-privacy.md` | How do modules control scope and privacy in a growing project? |
| paths-1 | en | 1 | `docs/book/ch07-03-paths-for-referring-to-an-item-in-the-module-tree.md` | How do paths refer to an item in the module tree? |
| use-1 | en | 2 | `docs/book/SUMMARY.md` | How do I bring paths into scope with the use keyword, including the glob operator? |
| pkg-1 | en | 1 | `docs/book/ch07-01-packages-and-crates.md` | How do packages and crates relate, and what separates a binary from a library crate? |
| vec-1 | en | 1 | `docs/book/ch08-01-vectors.md` | How do I store a list of values in a Vec and read elements out of it? |
| str-1 | en | 1 | `docs/book/ch08-02-strings.md` | Why is a String UTF-8 encoded and why can I not index it by byte? |
| map-1 | en | 1 | `docs/book/ch08-03-hash-maps.md` | How do I store key-value pairs in a HashMap and who owns the keys? |
| result-1 | en | 1 | `docs/book/ch09-02-recoverable-errors-with-result.md` | How do I propagate errors with the question-mark operator in a function returning Result? |
| panic-1 | en | 1 | `docs/book/ch09-03-to-panic-or-not-to-panic.md` | When should I panic instead of returning an error, and why avoid putting a program in a bad state? |
| generic-1 | en | 1 | `docs/book/ch10-01-syntax.md` | How do I write a generic function using type parameters? |
| trait-1 | en | 1 | `docs/book/ch10-02-traits.md` | How do trait bounds and default implementations work? |
| lifetime-1 | en | 1 | `docs/book/ch10-03-lifetime-syntax.md` | How do lifetime annotations keep references valid? |
| test-1 | en | 1 | `docs/book/ch11-01-writing-tests.md` | How do I write a unit test with the #[test] attribute and assert_eq macro? |
| test-org-1 | en | 1 | `docs/book/ch11-03-test-organization.md` | Where do integration tests live and how is the tests directory organised? |
| closure-1 | en | 1 | `docs/book/ch13-01-closures.md` | How do closures capture their environment and implement the Fn traits? |
| iter-1 | en | 1 | `docs/book/ch13-02-iterators.md` | How do iterator adapters such as map and filter evaluate lazily? |
| profile-1 | en | 1 | `docs/book/ch14-01-release-profiles.md` | How do release profiles customise optimisation and debug settings? |
| box-1 | en | 1 | `docs/book/ch15-01-box.md` | How does Box let me store recursive types such as a cons list? |
| drop-1 | en | 1 | `docs/book/ch15-03-drop.md` | How does running code on cleanup work with the Drop trait? |
| rc-1 | en | 1 | `docs/book/ch15-04-rc.md` | How does reference counting with Rc share ownership between values? |
| refcell-1 | en | 1 | `docs/book/ch15-05-interior-mutability.md` | How does RefCell provide interior mutability at runtime? |
| thread-1 | en | 1 | `docs/book/ch16-01-threads.md` | How do I spawn a thread and wait for it to finish with join? |
| chan-1 | en | 1 | `docs/book/ch16-02-message-passing.md` | How do channels transfer messages between threads with mpsc? |
| mutex-1 | en | 3 | `docs/book/ch21-02-multithreaded.md` | How do Mutex and Arc let several threads share state safely? |
| async-1 | en | 1 | `docs/book/ch17-01-futures-and-syntax.md` | What is a future and how do async and await work? |
| traitobj-1 | en | 1 | `docs/book/ch18-02-trait-objects.md` | How do trait objects with dyn enable dynamic dispatch? |
| refute-1 | en | 1 | `docs/book/ch19-02-refutability.md` | What does refutability mean for patterns in let bindings versus match arms? |
| unsafe-1 | en | 1 | `docs/book/ch20-01-unsafe-rust.md` | How do I use unsafe Rust for raw pointers and calls to unsafe functions? |
| macro-1 | en | 1 | `docs/book/ch20-05-macros.md` | How do I declare a macro with macro_rules? |
| zh-own | zh | miss | `docs/book/appendix-06-translation.md` | 所有權的規則是什麼？堆疊與堆積的差別在哪裡？ |
| zh-lifetime | zh | miss | `docs/book/ch16-03-shared-state.md` | 如何在函式簽名中標註生命週期，讓引用保持有效？ |
| zh-hashmap | zh | 1 | `docs/book/ch08-03-hash-maps.md` | 怎麼用 HashMap 儲存鍵值對？鍵的擁有權歸誰？ |
| zh-thread | zh | miss | `docs/book/ch16-04-extensible-concurrency-sync-and-send.md` | 如何建立執行緒並等待它結束？ |
| zh-test | zh | miss | `docs/book/ch07-02-defining-modules-to-control-scope-and-privacy.md` | 單元測試與整合測試分別放在哪裡、怎麼組織？ |
| zh-match | zh | 4 | `docs/book/ch19-03-pattern-syntax.md` | match 如何處理所有可能情況？萬用模式是什麼？ |

## Misses

- `zh-own` (zh): expected `docs/book/ch04-01-what-is-ownership.md`, top-1 was `docs/book/appendix-06-translation.md` — 所有權的規則是什麼？堆疊與堆積的差別在哪裡？
- `zh-lifetime` (zh): expected `docs/book/ch10-03-lifetime-syntax.md`, top-1 was `docs/book/ch16-03-shared-state.md` — 如何在函式簽名中標註生命週期，讓引用保持有效？
- `zh-thread` (zh): expected `docs/book/ch16-01-threads.md`, top-1 was `docs/book/ch16-04-extensible-concurrency-sync-and-send.md` — 如何建立執行緒並等待它結束？
- `zh-test` (zh): expected `docs/book/ch11-03-test-organization.md`, top-1 was `docs/book/ch07-02-defining-modules-to-control-scope-and-privacy.md` — 單元測試與整合測試分別放在哪裡、怎麼組織？

## Indexer output

```
sqlite-vec=True changed_files=112 removed=0
files=112 chunks=4029 chars=1241370 est_tokens=2358604 tok_per_char=1.9 elapsed=109.21s corpus_head=1500248d
  + docs/book/SUMMARY.md (25 chunks)
  + docs/book/appendix-00.md (1 chunks)
  + docs/book/appendix-01-keywords.md (17 chunks)
  + docs/book/appendix-02-operators.md (70 chunks)
  + docs/book/appendix-03-derivable-traits.md (35 chunks)
  + docs/book/appendix-04-useful-development-tools.md (16 chunks)
  + docs/book/appendix-05-editions.md (10 chunks)
  + docs/book/appendix-06-translation.md (6 chunks)
  + docs/book/appendix-07-nightly-rust.md (31 chunks)
  + docs/book/ch00-00-introduction.md (37 chunks)
  + docs/book/ch01-00-getting-started.md (1 chunks)
  + docs/book/ch01-01-installation.md (20 chunks)
  + docs/book/ch01-02-hello-world.md (25 chunks)
  + docs/book/ch01-03-hello-cargo.md (34 chunks)
  + docs/book/ch02-00-guessing-game-tutorial.md (130 chunks)
  + docs/book/ch03-00-common-programming-concepts.md (4 chunks)
  + docs/book/ch03-01-variables-and-mutability.md (29 chunks)
  + docs/book/ch03-02-data-types.md (55 chunks)
  + docs/book/ch03-03-how-functions-work.md (38 chunks)
  + docs/book/ch03-04-comments.md (4 chunks)
  + docs/book/ch03-05-control-flow.md (57 chunks)
  + docs/book/ch04-00-understanding-ownership.md (1 chunks)
  + docs/book/ch04-01-what-is-ownership.md (82 chunks)
  + docs/book/ch04-02-references-and-borrowing.md (34 chunks)
  + docs/book/ch04-03-slices.md (40 chunks)
  + docs/book/ch05-00-structs.md (2 chunks)
  + docs/book/ch05-01-defining-structs.md (48 chunks)
  + docs/book/ch05-02-example-structs.md (38 chunks)
  + docs/book/ch05-03-method-syntax.md (39 chunks)
  + docs/book/ch06-00-enums.md (2 chunks)
  + docs/book/ch06-01-defining-an-enum.md (51 chunks)
  + docs/book/ch06-02-match.md (45 chunks)
  + docs/book/ch06-03-if-let.md (21 chunks)
  + docs/book/ch07-00-managing-growing-projects-with-packages-crates-and-modules.md (12 chunks)
  + docs/book/ch07-01-packages-and-crates.md (14 chunks)
  + docs/book/ch07-02-defining-modules-to-control-scope-and-privacy.md (25 chunks)
  + docs/book/ch07-03-paths-for-referring-to-an-item-in-the-module-tree.md (54 chunks)
  + docs/book/ch07-04-bringing-paths-into-scope-with-the-use-keyword.md (43 chunks)
  + docs/book/ch07-05-separating-modules-into-different-files.md (20 chunks)
  + docs/book/ch08-00-common-collections.md (5 chunks)
  + docs/book/ch08-01-vectors.md (37 chunks)
  + docs/book/ch08-02-strings.md (51 chunks)
  + docs/book/ch08-03-hash-maps.md (38 chunks)
  + docs/book/ch09-00-error-handling.md (4 chunks)
  + docs/book/ch09-01-unrecoverable-errors-with-panic.md (28 chunks)
  + docs/book/ch09-02-recoverable-errors-with-result.md (92 chunks)
  + docs/book/ch09-03-to-panic-or-not-to-panic.md (47 chunks)
  + docs/book/ch10-00-generics.md (19 chunks)
  + docs/book/ch10-01-syntax.md (51 chunks)
  + docs/book/ch10-02-traits.md (64 chunks)
  + docs/book/ch10-03-lifetime-syntax.md (104 chunks)
  + docs/book/ch11-00-testing.md (7 chunks)
  + docs/book/ch11-01-writing-tests.md (83 chunks)
  + docs/book/ch11-02-running-tests.md (25 chunks)
  + docs/book/ch11-03-test-organization.md (44 chunks)
  + docs/book/ch12-00-an-io-project.md (9 chunks)
  + docs/book/ch12-01-accepting-command-line-arguments.md (22 chunks)
  + docs/book/ch12-02-reading-a-file.md (7 chunks)
  + docs/book/ch12-03-improving-error-handling-and-modularity.md (89 chunks)
  + docs/book/ch12-04-testing-the-librarys-functionality.md (31 chunks)
  + docs/book/ch12-05-working-with-environment-variables.md (34 chunks)
  + docs/book/ch12-06-writing-to-stderr-instead-of-stdout.md (13 chunks)
  + docs/book/ch13-00-functional-features.md (4 chunks)
  + docs/book/ch13-01-closures.md (74 chunks)
  + docs/book/ch13-02-iterators.md (31 chunks)
  + docs/book/ch13-03-improving-our-io-project.md (33 chunks)
  + docs/book/ch13-04-performance.md (10 chunks)
  + docs/book/ch14-00-more-about-cargo.md (3 chunks)
  + docs/book/ch14-01-release-profiles.md (11 chunks)
  + docs/book/ch14-02-publishing-to-crates-io.md (69 chunks)
  + docs/book/ch14-03-cargo-workspaces.md (42 chunks)
  + docs/book/ch14-04-installing-binaries.md (7 chunks)
  + docs/book/ch14-05-extending-cargo.md (3 chunks)
  + docs/book/ch15-00-smart-pointers.md (10 chunks)
  + docs/book/ch15-01-box.md (45 chunks)
  + docs/book/ch15-02-deref.md (47 chunks)
  + docs/book/ch15-03-drop.md (23 chunks)
  + docs/book/ch15-04-rc.md (26 chunks)
  + docs/book/ch15-05-interior-mutability.md (63 chunks)
  + docs/book/ch15-06-reference-cycles.md (49 chunks)
  + docs/book/ch16-00-concurrency.md (10 chunks)
  + docs/book/ch16-01-threads.md (43 chunks)
  + docs/book/ch16-02-message-passing.md (40 chunks)
  + docs/book/ch16-03-shared-state.md (41 chunks)
  + docs/book/ch16-04-extensible-concurrency-sync-and-send.md (16 chunks)
  + docs/book/ch17-00-async-await.md (31 chunks)
  + docs/book/ch17-01-futures-and-syntax.md (69 chunks)
  + docs/book/ch17-02-concurrency-with-async.md (65 chunks)
  + docs/book/ch17-03-more-futures.md (33 chunks)
  + docs/book/ch17-04-streams.md (17 chunks)
  + docs/book/ch17-05-traits-for-async.md (90 chunks)
  + docs/book/ch17-06-futures-tasks-threads.md (20 chunks)
  + docs/book/ch18-00-oop.md (4 chunks)
  + docs/book/ch18-01-what-is-oo.md (29 chunks)
  + docs/book/ch18-02-trait-objects.md (43 chunks)
  + docs/book/ch18-03-oo-design-patterns.md (95 chunks)
  + docs/book/ch19-00-patterns.md (4 chunks)
  + docs/book/ch19-01-all-the-places-for-patterns.md (33 chunks)
  + docs/book/ch19-02-refutability.md (15 chunks)
  + docs/book/ch19-03-pattern-syntax.md (88 chunks)
  + docs/book/ch20-00-advanced-features.md (4 chunks)
  + docs/book/ch20-01-unsafe-rust.md (96 chunks)
  + docs/book/ch20-02-advanced-traits.md (73 chunks)
  + docs/book/ch20-03-advanced-types.md (47 chunks)
  + docs/book/ch20-04-advanced-functions-and-closures.md (27 chunks)
  + docs/book/ch20-05-macros.md (83 chunks)
  + docs/book/ch21-00-final-project-a-web-server.md (7 chunks)
  + docs/book/ch21-01-single-threaded.md (70 chunks)
  + docs/book/ch21-02-multithreaded.md (116 chunks)
  + docs/book/ch21-03-graceful-shutdown-and-cleanup.md (36 chunks)
  + docs/book/foreword.md (10 chunks)
  + docs/book/title-page.md (4 chunks)
```
