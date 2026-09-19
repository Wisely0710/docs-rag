# Answering

The answering pipeline runs three steps in order: it retrieves the top-k excerpts for the
question, builds a prompt from those excerpts, and calls the chat model once at
temperature 0.

The prompt demands that every claim cite a corpus path in backticks. When the excerpts do
not contain the answer, the model must not guess: it replies with the marker NOT_IN_CORPUS
on the first line instead, followed by at most one short sentence.

Citations are extracted from the reply by matching backticked paths that end in `.md`. An
answer that cites a path which is not part of the corpus is reported as an invalid citation
by the evaluation harness.
