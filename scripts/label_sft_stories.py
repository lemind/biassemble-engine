#!/usr/bin/env python
"""Label consolidated synthetic stories with Gemini — the one consistent teacher
model (ADR-005 §2), replacing each row's generator-claimed target_bias_ids with
a trusted label. Batches many stories per call (not one-request-per-story) to
keep total request count low and avoid the truncation failures seen repeatedly
with 40-story generation batches.

Story text only is sent — NOT the generator's target_bias_ids — so Gemini isn't
anchored to a guess (data-model.md: generator's target_bias_ids is intent, not
a trusted label).

Usage:
    uv run python scripts/label_sft_stories.py --input evaluations/staging/sft_raw_batches/consolidated_pre_labeling.jsonl \
        --output evaluations/staging/sft_raw_batches/labeled_chunk1.jsonl --start 0 --count 50
"""

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

VALID_BIAS_IDS = [
    "affect_heuristic", "ambiguity_effect", "anchoring_bias", "authority_bias",
    "availability_heuristic", "bandwagon_effect", "base_rate_neglect", "choice_supportive_bias",
    "confirmation_bias", "curse_of_knowledge", "decoy_effect", "dunning_kruger_effect",
    "escalation_of_commitment", "framing_effect", "fundamental_attribution_error",
    "gamblers_fallacy", "halo_effect", "hindsight_bias", "hot_hand_fallacy",
    "illusion_of_control", "in_group_bias", "loss_aversion", "narrative_fallacy",
    "negativity_bias", "omission_bias", "optimism_bias", "overconfidence_bias",
    "planning_fallacy", "projection_bias", "recency_bias", "representativeness_heuristic",
    "self_serving_bias", "spotlight_effect", "status_quo_bias", "stereotyping_bias",
    "sunk_cost_fallacy", "survivorship_bias", "zero_risk_bias",
]

MODEL = "gemini-2.5-flash-lite"
PROMPT_VERSION = "v1"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def _read_gemini_key() -> str:
    core_env = Path("/home/dl/_prog/biassemble/biassemble-core/.env")
    for line in core_env.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("GEMINI_API_KEY not found in biassemble-core/.env")


def build_prompt(stories: list[dict]) -> str:
    catalog = ", ".join(VALID_BIAS_IDS)
    lines = [
        "You are labeling stories for a cognitive-bias detection training dataset.",
        "For EACH story below, identify which of these bias ids are clearly present:",
        catalog,
        "",
        "Rules:",
        "- Use ONLY ids from the list above, exact spelling.",
        "- A story may have zero, one, or multiple bias ids. Most have 1-3.",
        "- Only include an id if the story text clearly supports it — no speculative labels.",
        "- Return ONLY a JSON array, one object per story, in the SAME ORDER given, no other text:",
        '  [{"id": "<story id>", "bias_ids": ["..."]}]',
        "",
        "STORIES:",
    ]
    for s in stories:
        lines.append(json.dumps({"id": s["id"], "story": s["story"]}))
    return "\n".join(lines)


def call_gemini(prompt: str, api_key: str) -> str:
    resp = httpx.post(
        API_URL,
        params={"key": api_key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def extract_json_array(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"```$", "", text.strip())
    # Repair a reproducible Gemini glitch seen on real output: a duplicated key
    # like {"id": "id": "b3_adv_007", ...} instead of {"id": "b3_adv_007", ...}.
    text = re.sub(r'\{"id":\s*"id":', '{"id":', text)
    return json.loads(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args()

    all_rows = [json.loads(l) for l in args.input.read_text().splitlines() if l.strip()]
    chunk = all_rows[args.start : args.start + args.count]
    print(f"Labeling rows {args.start}..{args.start + len(chunk)} of {len(all_rows)}")

    api_key = _read_gemini_key()
    prompt = build_prompt([{"id": r["id"], "story": r["story"]} for r in chunk])

    print(f"Calling {MODEL} with {len(chunk)} stories in one request ...")
    raw = call_gemini(prompt, api_key)

    try:
        labels = extract_json_array(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: could not parse Gemini response as JSON: {e}", file=sys.stderr)
        print("--- raw response ---", file=sys.stderr)
        print(raw, file=sys.stderr)
        sys.exit(1)

    if len(labels) != len(chunk):
        print(f"WARNING: got {len(labels)} labels for {len(chunk)} stories — mismatch", file=sys.stderr)

    labels_by_id = {l["id"]: l["bias_ids"] for l in labels}
    valid_ids = set(VALID_BIAS_IDS)
    output_rows = []
    rejected = []
    dropped_ids = []
    for r in chunk:
        gemini_ids = labels_by_id.get(r["id"])
        if gemini_ids is None:
            rejected.append((r["id"], "no label returned"))
            continue
        valid = [b for b in gemini_ids if b in valid_ids]
        invalid = [b for b in gemini_ids if b not in valid_ids]
        # Drop only the invalid id(s), keep the row with its remaining valid
        # ids — Gemini is the trusted teacher; one hallucinated extra
        # shouldn't torpedo an otherwise-good story and its other correct
        # labels (same "drop the bad entry, keep the row" precedent as
        # adv_005 in the blind-spot batch and T011's name normalization).
        # Exception: if EVERYTHING returned was invalid (gemini_ids non-empty
        # but valid is empty), this row needs re-labeling, not a silent
        # bias_ids=[] that would misrepresent it as a confirmed negative.
        if invalid and not valid and gemini_ids:
            rejected.append((r["id"], f"all returned id(s) invalid: {invalid}"))
            continue
        if invalid:
            dropped_ids.append((r["id"], invalid))
        out = dict(r)
        out["bias_ids"] = valid
        out.pop("target_bias_ids", None)
        out["teacher_model"] = MODEL
        out["label_prompt_version"] = PROMPT_VERSION
        output_rows.append(out)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        for r in output_rows:
            f.write(json.dumps(r) + "\n")

    print(f"Labeled {len(output_rows)} rows successfully -> {args.output}")
    if dropped_ids:
        print(f"{len(dropped_ids)} row(s) kept with a partial drop (invalid id removed, valid ids retained):")
        for rid, invalid in dropped_ids:
            print(f"  {rid}: dropped {invalid}")
    if rejected:
        print(f"{len(rejected)} fully rejected (need re-labeling):")
        for rid, reason in rejected:
            print(f"  {rid}: {reason}")


if __name__ == "__main__":
    main()
