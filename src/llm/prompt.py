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

SYSTEM = (
    "You are a cognitive-bias detector. Given a story, identify which of the catalog "
    "biases the narrator exhibits. Choose ONLY from the catalog, using the exact bias_id. "
    'Respond with STRICT JSON only: a JSON array of objects '
    '{"bias_id": "...", "confidence": 0.0-1.0, "evidence": "short quote from the story"}. '
    "Return [] if the story shows no clear cognitive bias. Output nothing but the JSON array."
)


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
    lines = ["CATALOG (bias_id — indicators):"]
    for bias_id, name, indicators in catalog:
        ind = "; ".join(indicators)
        lines.append(f"- {bias_id} ({name}): {ind}")
    lines += ["", "STORY:", story, "", "Return the JSON array now."]
    return "\n".join(lines)


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
    data = json.loads(json_text)
    if not isinstance(data, list):
        data = [data] if isinstance(data, dict) else []
    return [d for d in data if isinstance(d, dict) and "bias_id" in d]


def _validate_catalog(items: list[dict], valid_ids: set[str]) -> list[BiasCandidate]:
    kept = []
    for d in items:
        bid = d.get("bias_id")
        if bid not in valid_ids:
            continue
        try:
            confidence = float(d.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
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
