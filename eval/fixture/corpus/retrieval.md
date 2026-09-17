# Retrieval design

Queries run two independent rankers and fuse them. The vector ranker embeds the query
and scans chunk embeddings; it handles paraphrase but blurs rare identifiers. The FTS5
trigram ranker matches exact strings such as file paths, identifiers and error codes.

The fused score is the sum of 1 / (60 + rank) over both ranker lists — reciprocal rank
fusion with k=60 — so no score calibration between the rankers is required.
