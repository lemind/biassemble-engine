from src.schemas.internal import CandidateChunk, RetrievedBias


def rerank(
    candidates: list[CandidateChunk],
    threshold: float,
    return_top_k: int,
    admitted_ids: set[str] | None = None,
    score_override: dict[str, float] | None = None,
) -> list[RetrievedBias]:
    """Collapse raw candidate chunks into deduplicated, ranked RetrievedBias objects.

    Pipeline:
      1. Drop chunks below similarity_threshold (or outside admitted_ids when provided).
      2. Group remaining chunks by bias_id.
      3. For each bias, take the highest-scoring chunk (max collapse).
      4. Build RetrievedBias from the winning chunk's full_document + collect all sources.
      5. Sort descending by retrieval_score.
      6. Return top return_top_k results.
    """
    # Step 1: threshold filter (or strategy-admitted set)
    if admitted_ids is not None:
        surviving = [c for c in candidates if c.bias_id in admitted_ids]
    else:
        surviving = [c for c in candidates if c.retrieval_score >= threshold]
    if not surviving:
        return []

    # Step 2 & 3: group by bias_id, pick the chunk with the highest score per bias
    best: dict[str, CandidateChunk] = {}
    sources: dict[str, set[str]] = {}
    for chunk in surviving:
        bid = chunk.bias_id
        if bid not in best or chunk.retrieval_score > best[bid].retrieval_score:
            best[bid] = chunk
        sources.setdefault(bid, set()).add(chunk.source)

    # Step 4: build RetrievedBias from the winning chunk
    results: list[RetrievedBias] = []
    for bid, chunk in best.items():
        doc = chunk.full_document
        results.append(
            RetrievedBias(
                bias_id=bid,
                name=doc.name,
                retrieval_score=chunk.retrieval_score,
                sources=sorted(sources[bid]),
                matched_chunk_type=chunk.chunk_type,
                matched_text=chunk.chunk_text,
                definition=doc.definition,
                examples=doc.examples,
                indicators=doc.indicators,
                false_positives=doc.false_positives,
                related_biases=doc.related_biases,
            )
        )

    # Step 5 & 6: sort descending by combined score (when provided) then trim to top_k
    results.sort(
        key=lambda r: score_override[r.bias_id] if score_override and r.bias_id in score_override else r.retrieval_score,
        reverse=True,
    )
    return results[:return_top_k]
