#!/usr/bin/env python3
"""Ask one question against a docs-rag corpus and print a cited answer.

Usage:

    python qa/ask.py --rag-dir eval/qa/.work --corpus portfolio --backend deepseek \
        "How does the verifier fail closed?"

The index must already exist (build it with the indexer, as eval/qa/README.md shows);
this CLI only reads it. Corpus selection and environment setup reuse the evaluation
harness's helper, so a CLI run sees exactly the configuration an eval run sees.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="docs-rag QA: retrieve, answer, cite")
    parser.add_argument("question", help="the question to ask")
    parser.add_argument("--rag-dir", required=True, help="RAG_DIR holding corpora.json and the index")
    parser.add_argument("--corpus", required=True, help="corpus name as declared in corpora.json")
    parser.add_argument(
        "--backend",
        choices=("stub", "deepseek", "lmstudio"),
        default="lmstudio",
        help="chat backend (default: lmstudio, the deployment default)",
    )
    parser.add_argument("--model", help="chat model (required for lmstudio; defaults per backend otherwise)")
    parser.add_argument("--k", type=int, default=6, help="excerpts retrieved (1-10; the service clamps)")
    parser.add_argument(
        "--embed-backend",
        choices=("stub", "lmstudio", "none"),
        default="none",
        help="must match how the index was built (default: the environment's)",
    )
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from eval.evalutil import configure_env

    configure_env(
        rag_dir=Path(args.rag_dir),
        corpus=args.corpus,
        embed_backend=None if args.embed_backend == "none" else args.embed_backend,
    )

    import searchlib
    from qa.answer import answer_question
    from qa.llm import ChatError, make_client

    try:
        client = make_client(args.backend, args.model)
    except ChatError as exc:
        raise SystemExit(str(exc)) from exc

    answer = answer_question(
        args.question,
        retriever=lambda question, k: searchlib.retrieve(question, k=k, caller="qa"),
        client=client,
        k=args.k,
    )

    if args.json:
        payload = {
            "question": answer.question,
            "answer": answer.text,
            "abstained": answer.abstained,
            "citations": answer.citations,
            "model": client.model,
            "sources": [{"path": hit["path"], "seq": hit["seq"], "score": hit["score"]} for hit in answer.hits],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(answer.text)
    if answer.citations:
        print("\ncitations: " + ", ".join(f"`{path}`" for path in answer.citations))
    print(f"\nsources ({client.model}, ranked):")
    for rank, hit in enumerate(answer.hits, 1):
        print(f"  {rank}. {hit['path']} (chunk {hit['seq']}, score {hit['score']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
