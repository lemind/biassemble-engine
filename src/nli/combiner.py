from dataclasses import dataclass


@dataclass
class CombinerOutput:
    admitted: list[str]
    admitted_by: dict[str, list[str]]
    nli_scores: dict[str, float]
    vector_scores: dict[str, float]    # min-max normalized over all 38 biases, NOT raw cosine scores
    combined_scores: dict[str, float]


@dataclass
class CombinerConfig:
    w_nli: float
    w_vec: float
    nli_gate: float
    vec_gate: float
    combined_threshold: float


def combine(
    nli_scores: dict[str, float],
    vector_scores_raw: dict[str, float],
    config: CombinerConfig,
) -> CombinerOutput:
    """Three-gate OR combiner over the full 38-bias vector.

    Gates: NLI entailment >= nli_gate  OR  vec_norm >= vec_gate  OR  combined >= combined_threshold.
    min-max normalization uses all 38 biases (absent biases treated as 0.0 raw score).
    admitted is ordered by combined_score descending.
    """
    all_ids = list(nli_scores.keys())

    # Step 1: min-max normalize vector scores over the full 38-bias vector.
    # Absent biases get 0.0 raw score before normalization.
    all_vec = {bid: vector_scores_raw.get(bid, 0.0) for bid in all_ids}
    min_v = min(all_vec.values())
    max_v = max(all_vec.values())
    if max_v > min_v:
        vec_norm = {bid: (s - min_v) / (max_v - min_v) for bid, s in all_vec.items()}
    else:
        vec_norm = {bid: 0.0 for bid in all_ids}

    # Step 2: combined score for all 38.
    combined = {
        bid: config.w_nli * nli_scores[bid] + config.w_vec * vec_norm[bid]
        for bid in all_ids
    }

    # Step 3: three-gate OR — track which gate(s) admitted each bias.
    admitted: list[str] = []
    admitted_by: dict[str, list[str]] = {}
    for bid in all_ids:
        gates: list[str] = []
        if nli_scores[bid] >= config.nli_gate:
            gates.append("NLI")
        if vector_scores_raw.get(bid, 0.0) >= config.vec_gate:
            gates.append("VECTOR")
        if combined[bid] >= config.combined_threshold:
            gates.append("COMBINED")
        if gates:
            admitted.append(bid)
            admitted_by[bid] = gates

    # Step 4: sort admitted by combined score descending.
    admitted.sort(key=lambda bid: combined[bid], reverse=True)

    return CombinerOutput(
        admitted=admitted,
        admitted_by=admitted_by,
        nli_scores=nli_scores,
        vector_scores=vec_norm,
        combined_scores=combined,
    )
