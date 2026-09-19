# Judging

A judge scores one candidate answer against a reference answer and the retrieved excerpts.
It returns JSON with three fields: verdict, unsupported_claims and rationale.

The verdict is one of correct, partial or incorrect. correct means the key facts of the
reference are present and nothing is contradicted; partial means some key facts are missing
or the answer is vague; incorrect means the answer misses, contradicts or fabricates the key
facts.

unsupported_claims lists factual claims that neither the excerpts nor the reference support,
such as invented numbers. Two judges from different model families can grade the same run;
the harness then reports their agreement as a kappa coefficient.
