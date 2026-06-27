# Skill: Evaluation

## Metrics

| Metric | Formula | Purpose |
|--------|---------|---------|
| Recall@K | `len(expected ∩ retrieved) / len(expected)` | Primary — are the right biases found? |
| Precision@K | `len(expected ∩ retrieved) / len(retrieved)` | Are retrieved biases relevant? |
| MRR | `1 / rank` of first correct hit | How early does the right answer appear? |
| Empty Retrieval Rate | fraction of scenarios returning `[]` | 0% on golden, ~100% on no-bias |
| Coverage | distinct bias_ids ever retrieved / total biases | Catches taxonomy imbalance |

## Golden Dataset Format

```json
{
  "scenario_id": "marcus_novatech",
  "story": "...",
  "story_analysis": {
    "themes": ["investment", "sunk cost"],
    "beliefs": ["stock will recover"],
    "claims": []
  },
  "expected_bias_ids": ["confirmation_bias", "anchoring_bias", "sunk_cost_fallacy"]
}
```

Files live in `evaluations/golden/retrieval/*.json`.

## CLI Output

```
Evaluation — biassemble-rag
Model: all-MiniLM-L6-v2  |  Taxonomy: v1  |  Threshold: 0.45  |  K: 5  |  Strategy: repeated_story

scenario               expected    retrieved   recall@5    precision@5   mrr
────────────────────────────────────────────────────────────────────────────
marcus_novatech        3           3           1.00        1.00          1.00

AGGREGATE   recall@5: 0.91   precision@5: 0.74   mrr: 0.88   empty_rate: 0.00   coverage: 18/30
```

## Rules

- **Establish baseline before tuning.** Run eval after indexing, before touching threshold/top-k.
- **Run eval after every change** to: embedding model, threshold, top-k, knowledge files, query strategy.
- `empty_rate` tracks separately for golden vs no-bias datasets.
- `coverage < total_biases` means some biases are never retrieved — investigate knowledge quality.

## Success Criteria

- Recall@5 ≥ 0.85 across golden dataset
- Marcus/NovaTech returns Confirmation Bias, Anchoring Bias, Sunk Cost Fallacy in top 5
- "I ate pizza" returns `biases: []`
- Coverage = 30/30 (all biases retrievable)
