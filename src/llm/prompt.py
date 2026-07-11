import json
import re
from dataclasses import dataclass

import asyncpg
import structlog

from src.db.queries import CATALOG_QUERY

log = structlog.get_logger()

# Indicator trim depth. MUST match the depth research.md's "Spike result" latency
# figures were measured at (T003 used inds[:3]) — changing this invalidates that
# number until re-measured at T020. See research.md "Catalog size caveat".
_INDICATORS_PER_BIAS = 3

_BULLET_RE = re.compile(r"^[-*]\s*")

# The LLM is shown ALL bias_ids every request (no vector narrowing) so it can name a
# bias even in a domain vector search is blind to — proven to carry novel domains
# (space/deep-sea/archaeology) where vector returned nothing. Bare-list output (ids
# only, no confidence/evidence) was the fastest AND best-scoring format in eval
# (research.md "Format + model selection"). See ADR-003.
SYSTEM = (
    "You are a cognitive-bias detector helping build a candidate list for a later, more "
    "careful review. Read the story and identify every bias that PLAUSIBLY applies — err on "
    "the side of including a bias if there is a reasonable case for it. Choose ONLY from the "
    "provided list of bias_ids, using the exact id. "
    'Respond with STRICT JSON only: an array of bias_id strings, e.g. '
    '["anchoring_bias", "sunk_cost_fallacy"]. No objects, no other fields. '
    "Return [] only if truly nothing in the list plausibly applies. "
    "Output nothing but the JSON array."
)

_EXAMPLE = (
    "\n\nEXAMPLE:\n"
    "bias_ids: sunk_cost_fallacy, anchoring_bias, loss_aversion\n"
    "STORY: Despite losing money every month, Maria keeps the failing shop open because she "
    "already spent her savings renovating it.\n"
    'Correct output: ["sunk_cost_fallacy"]\n'
)

# Bare-list output carries no per-bias confidence; use a neutral placeholder so the
# BiasCandidate/score interface stays intact. Ranking among LLM-only biases then falls
# to the deterministic bias_id tiebreak (rank_and_trim), which is fine.
_LLM_DEFAULT_CONFIDENCE = 0.5


@dataclass
class BiasCandidate:
    bias_id: str
    confidence: float
    evidence: str


def _split_indicators(raw: str | None) -> list[str]:
    if not raw:
        return []
    lines = [_BULLET_RE.sub("", ln).strip() for ln in raw.splitlines()]
    return [ln for ln in lines if ln][:_INDICATORS_PER_BIAS]


async def load_catalog(
    pool: asyncpg.Pool, taxonomy_version: str
) -> list[tuple[str, str, list[str]]]:
    """Fetch (bias_id, name, indicators) for the full taxonomy — the "existing
    catalog/roster provider" research R4 requires (DB-sourced, not hardcoded, not a
    re-parse of knowledge/*.md at request time). Call once at startup, like NLI
    hypotheses — not per-request."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(CATALOG_QUERY, taxonomy_version)
    return [
        (r["bias_id"], r["name"] or r["bias_id"], _split_indicators(r["indicators"]))
        for r in rows
    ]


def build_user_message(story: str, catalog: list[tuple[str, str, list[str]]]) -> str:
    """ids-only prompt: the full list of bias_ids (no definitions/indicators) + the
    story. All 38 ids are shown every request — NOT narrowed by vector — so the LLM
    can name a bias vector missed. The id list is short (~330 tokens for 38, scales to
    ~900 for 200+), which is why this stays fast without needing narrowing."""
    ids = ", ".join(bias_id for bias_id, _, _ in catalog)
    return (
        f"{_EXAMPLE}\nNOW YOUR TURN.\nbias_ids: {ids}\n\n"
        f"STORY:\n{story}\n\nReturn the JSON array of bias_id strings now."
    )


# Margin for chat-template special tokens the raw tokenizer count doesn't see.
_PROMPT_OVERHEAD_TOKENS = 100


def fit_story_to_budget(
    generator, story: str, catalog: list[tuple[str, str, list[str]]]
) -> tuple[str, bool]:
    """Truncate `story` (never the catalog) so system + catalog + story + output fits
    `generator.context_tokens`. Real-world usage measured well inside budget
    (research.md "Spike result": 2666/4096) — this is a defensive cap, not the
    common case. Returns (possibly-truncated story, was_truncated)."""
    budget = generator.context_tokens - generator.max_output_tokens - _PROMPT_OVERHEAD_TOKENS
    empty_user_msg = build_user_message("", catalog)
    fixed_tokens = generator.count_tokens(SYSTEM) + generator.count_tokens(empty_user_msg)
    story_budget = budget - fixed_tokens
    if story_budget <= 0 or generator.count_tokens(story) <= story_budget:
        return story, False
    return generator.truncate_to_tokens(story, story_budget), True


# ── Staged parse pipeline (research R4) — each stage logs in/out counts so a
# failure is attributable to a specific stage, not a mystery empty list. Never
# raises; any stage failure falls through to an empty candidate list (FR-007). ──

def _extract_json(raw: str) -> str | None:
    """Find the first balanced top-level JSON array, ignoring brackets inside
    string literals. A plain greedy `\\[.*\\]` regex matches from the first '['
    to the LAST ']' in the whole response — if the model appends any
    bracket-containing commentary after the array (e.g. "...]\\nNote: [see X]."),
    that swallows trailing garbage and json.loads fails on the whole thing,
    silently dropping a valid result."""
    start = raw.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    return None


def _validate_schema(json_text: str) -> list[dict]:
    """Accept either the bare-list form (["bias_id", ...] — the production format) or
    the legacy object form ([{"bias_id": ..., "confidence": ...}]). Bare strings are
    normalized to {"bias_id": s} so _validate_catalog handles both uniformly."""
    data = json.loads(json_text)
    if not isinstance(data, list):
        data = [data] if isinstance(data, dict) else []
    out: list[dict] = []
    for item in data:
        if isinstance(item, str):
            out.append({"bias_id": item})
        elif isinstance(item, dict) and "bias_id" in item:
            out.append(item)
    return out


def _validate_catalog(items: list[dict], valid_ids: set[str]) -> list[BiasCandidate]:
    kept = []
    for d in items:
        bid = d.get("bias_id")
        if bid not in valid_ids:
            continue
        try:
            confidence = float(d.get("confidence", _LLM_DEFAULT_CONFIDENCE))
        except (TypeError, ValueError):
            confidence = _LLM_DEFAULT_CONFIDENCE
        kept.append(
            BiasCandidate(bias_id=bid, confidence=confidence, evidence=str(d.get("evidence", "")))
        )
    return kept


def parse_biases(raw: str, valid_ids: set[str]) -> list[BiasCandidate]:
    json_text = _extract_json(raw)
    if json_text is None:
        log.warning("llm_parse_stage_failed", stage="extract_json", raw_len=len(raw))
        return []

    try:
        schema_valid = _validate_schema(json_text)
    except json.JSONDecodeError as exc:
        log.warning("llm_parse_stage_failed", stage="validate_schema", error=str(exc))
        return []
    log.info("llm_parse_stage", stage="validate_schema", count=len(schema_valid))

    catalog_valid = _validate_catalog(schema_valid, valid_ids)
    log.info(
        "llm_parse_stage", stage="validate_catalog", in_=len(schema_valid), out=len(catalog_valid)
    )
    return catalog_valid
