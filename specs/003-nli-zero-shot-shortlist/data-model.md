# Data Model: NLI Zero-Shot Bias Shortlist

Delta from spec 001/002 baseline. No schema migrations — all changes are in-memory pipeline and response shape additions.

---

## New: SelectionStrategy (interface)

```python
class SelectionStrategy(Protocol):
    def select(self, story: str) -> dict[str, float]:
        """Return {bias_id: score} for all 38 biases. Score is 0.0 if not selected."""
        ...
```

**Implementations**:
- `VectorOnlyStrategy` — wraps existing `QueryStrategy` output; emits raw cosine scores (unchanged from pre-spec) in `retrieval_score`; populates absent biases with 0.0 for internal combiner use only. The external `BiasResult.retrieval_score` remains the raw cosine — backward-compatible byte-for-byte with pre-spec behavior when `SELECTION_STRATEGY=vector_only`.
- `NLIUnionStrategy` — runs NLI inference + vector search concurrently; applies three-gate union combiner; returns combined scores.

---

## New: NLIResult

```python
@dataclass
class NLIResult:
    scores: dict[str, float]              # {bias_id: entailment_score}, all 38 biases
    raw_scores: dict[str, dict[str, float]]  # {bias_id: {entailment, neutral, contradiction}}
    latency_ms: float
    truncated_premise: bool
```

`raw_scores` stores the full NLI head output per bias. Only `entailment` is used for selection; `neutral` and `contradiction` are saved for future calibration analysis (temperature scaling, threshold diagnostics). Storage cost is negligible.

---

## New: CombinerOutput

```python
@dataclass
class CombinerOutput:
    admitted: list[str]                    # bias_ids that cleared at least one gate, ordered by combined_scores[id] descending
    admitted_by: dict[str, list[str]]      # {bias_id: ["NLI"|"VECTOR"|"COMBINED"]} — which gate(s) admitted each bias
    nli_scores: dict[str, float]           # raw, all 38
    vector_scores: dict[str, float]        # min-max normalized over 38, all 38
    combined_scores: dict[str, float]      # weighted combination, all 38
```

`admitted_by` records which gate(s) fired for each admitted bias. Essential for debugging precision: when a bias is a false positive, `admitted_by` immediately tells you whether it was NLI, vector, or combined that let it through — without re-running the request.

---

## New: hypotheses/v1.yaml

```yaml
version: "v1"
hypotheses:
  - bias_id: anchoring_bias
    hypothesis: "The narrator remains committed to an initial figure or belief and makes only minor adjustments despite significant contradicting evidence."
  - bias_id: confirmation_bias
    hypothesis: "..."
  # ... 38 entries total
```

Loaded once at startup. `hypotheses_version` = the `version` field; recorded in every eval run and every API response.

---

## Modified: RetrievalMetadata (response additions — additive only)

Fields added to the existing response. Existing fields unchanged — biassemble-core requires no code changes.

```python
class RetrievalMetadata(BaseModel):
    # existing fields (unchanged)
    biases: list[BiasResult]
    retrieved_chunks: int
    taxonomy_version: str
    embedding_model: str
    request_id: str

    # new fields (present when SELECTION_STRATEGY=nli_union)
    selection_strategy: str | None = None      # "vector_only" | "nli_union"
    hypotheses_version: str | None = None      # from hypotheses/v1.yaml
    nli_latency_ms: float | None = None
    truncated_premise: bool | None = None
    nli_scores: dict[str, float] | None = None         # top returned biases only
    vector_scores: dict[str, float] | None = None      # top returned biases only
    combined_scores: dict[str, float] | None = None    # top returned biases only
```

---

## Config: new env vars

| Variable | Default | Description |
|---|---|---|
| `SELECTION_STRATEGY` | `vector_only` | `vector_only` or `nli_union` |
| `NLI_MODEL` | `MoritzLaurer/deberta-v3-base-zeroshot-v2.0` | HF model ID |
| `W_NLI` | `0.7` | Weight for NLI score in combiner |
| `W_VEC` | `0.3` | Weight for vector score in combiner |
| `NLI_GATE` | `0.80` | Per-signal gate: bias admitted if nli(b) ≥ this |
| `VEC_GATE` | `0.35` | Per-signal gate: bias admitted if vec(b) ≥ this |
| `COMBINED_THRESHOLD` | `0.60` | Fallback gate on combined score |
| `SENTENCE_MODE` | `false` | Offline T-eval-3 only — do not set in production |
| `HYPOTHESES_PATH` | `hypotheses/v1.yaml` | Path to hypotheses file |

---

## No DB changes

pgvector schema is unchanged. `bias_embeddings` table, `taxonomy_version`, and all existing indexes remain as-is. Vector search path is identical to spec 001/002.
