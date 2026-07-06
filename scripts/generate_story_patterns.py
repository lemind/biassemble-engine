#!/usr/bin/env python3
"""Generate 50 story-pattern snippets per bias and append ## Story Patterns to knowledge files.

Usage:
    GEMINI_API_KEY=<key> python scripts/generate_story_patterns.py [--bias <bias_id>] [--dry-run]

Runs 5 batches of 10 snippets per bias. Each batch passes previously generated
snippets so the model avoids repeating domains/phrasings.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
BATCHES = 5
SNIPPETS_PER_BATCH = 10

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

PROMPT_TEMPLATE = """You are generating retrieval-training content for a cognitive-bias detection system. Your output will be embedded (all-MiniLM-L6-v2) and matched against real first-person stories written by ordinary people. The goal is VOCABULARY COVERAGE: the same cognitive pattern expressed in maximally different words, domains, and voices.

TARGET BIAS: {bias_name}
DEFINITION: {definition_section}
INDICATORS: {indicators_section}
EXISTING EXAMPLES (do not duplicate their domains/phrasings): {examples_section}
FALSE POSITIVES (what this bias is NOT — never generate these): {false_positives_section}
RELATED BIASES (avoid drifting into these): {related_biases_section}

{already_generated_note}

Generate exactly {n} story snippets. Rules:

VOICE
- First person, present or recent past. The narrator is INSIDE the bias: they do not know they are biased, never name the bias, never reflect on it. Write the language people think in, not the language psychologists use to describe thinking.
- FORBIDDEN words/phrases: "{bias_name}", "bias", "cognitive", "rational", "objectively", "in hindsight", "I realize now", any psychology jargon.

DIVERSITY (the entire point — enforce hard)
- {n} snippets must cover at least {min_domains} DISTINCT domains from: workplace/management, money/investing, consumer/purchases, health/medical, romantic relationships, family, friendship/social, legal/disputes, politics/news, education/learning, technology/projects, hobbies/sports.
- No two snippets may share: opening structure, key vocabulary, sentence rhythm, or emotional register. Vary: casual vs formal, calm vs agitated, young vs old narrator, planner vs impulsive personality.
- Length: 25–60 words each (embedding density band; never shorter than 25).

FIDELITY
- Each snippet exhibits {bias_name} as the PRIMARY and essentially ONLY pattern. If a draft could equally be read as one of the RELATED BIASES, rewrite it until it is unambiguous.
- Each snippet must contain the bias MECHANISM in action (per INDICATORS), not just a topic association.
- Nothing from FALSE POSITIVES may appear as a positive example.

OUTPUT FORMAT (exactly; one paragraph per snippet; [Domain] from this controlled list only: Political, Social, Management, Consumer, Legal, Medical, Financial, Educational, Technical, Family):

## Story Patterns

[Management] <snippet text>

[Medical] <snippet text>

... ({n} total)

No commentary, no numbering, no explanations."""

_DOMAIN_RE = re.compile(r"^\[([A-Za-z]+)\]\s*")
_SECTION_RE = re.compile(r"^## Story Patterns\s*", re.MULTILINE)


def _parse_sections(md: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    lines_acc: list[str] = []
    for line in md.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            pass
        elif line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(lines_acc).strip()
            current = line[3:].strip().lower()
            lines_acc = []
        elif current is not None:
            lines_acc.append(line)
    if current is not None:
        sections[current] = "\n".join(lines_acc).strip()
    return sections


def _call_gemini(prompt: str, api_key: str, retries: int = 5) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]})
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["curl", "-s", "-X", "POST", url,
                 "-H", "Content-Type: application/json",
                 "-d", body],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(f"curl error: {result.stderr}")
            data = json.loads(result.stdout)
            if "error" in data:
                code = data["error"].get("code", 0)
                msg = data["error"].get("message", "unknown")
                if code == 429:
                    raise RuntimeError(f"429 rate limit: {msg}")
                raise RuntimeError(f"API error {code}: {msg}")
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt * 8
                print(f"retry in {wait}s ({e})...", end=" ", flush=True)
                time.sleep(wait)
            else:
                raise


def _extract_snippets(raw: str) -> list[str]:
    snippets: list[str] = []
    for para in raw.split("\n\n"):
        para = para.strip()
        if _DOMAIN_RE.match(para) and len(para.split()) >= 15:
            snippets.append(para)
    return snippets


def generate_for_bias(path: Path, api_key: str, dry_run: bool) -> None:
    md = path.read_text(encoding="utf-8")
    secs = _parse_sections(md)

    bias_id = path.stem
    bias_name = bias_id.replace("_", " ").title()
    name_line = next((l[2:].strip() for l in md.splitlines() if l.startswith("# ")), bias_name)
    bias_name = name_line

    if "story patterns" in secs:
        existing_count = len([p for p in secs["story patterns"].split("\n\n") if _DOMAIN_RE.match(p.strip())])
        print(f"  {bias_id}: already has {existing_count} patterns — skipping")
        return

    all_snippets: list[str] = []

    for batch in range(BATCHES):
        already_note = ""
        if all_snippets:
            already_note = (
                f"ALREADY GENERATED (do not repeat these domains or phrasings):\n"
                + "\n\n".join(all_snippets)
                + "\n"
            )

        prompt = PROMPT_TEMPLATE.format(
            bias_name=bias_name,
            definition_section=secs.get("definition", ""),
            indicators_section=secs.get("indicators", ""),
            examples_section=secs.get("examples", ""),
            false_positives_section=secs.get("false positives", ""),
            related_biases_section=secs.get("related biases", ""),
            already_generated_note=already_note,
            n=SNIPPETS_PER_BATCH,
            min_domains=min(SNIPPETS_PER_BATCH, 8),
        )

        if dry_run:
            print(f"  {bias_id} batch {batch+1}/{BATCHES}: [dry-run, prompt len={len(prompt)}]")
            all_snippets.extend([f"[Management] Dry-run snippet {i+1}" for i in range(SNIPPETS_PER_BATCH)])
            continue

        print(f"  {bias_id} batch {batch+1}/{BATCHES}...", end=" ", flush=True)
        try:
            raw = _call_gemini(prompt, api_key)
            snippets = _extract_snippets(raw)
            print(f"{len(snippets)} snippets")
            all_snippets.extend(snippets)
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(4)

    if not all_snippets:
        print(f"  {bias_id}: no snippets generated — skipping file write")
        return

    story_block = "\n\n".join(all_snippets)
    new_section = f"\n\n## Story Patterns\n\n{story_block}\n"

    if _SECTION_RE.search(md):
        updated = _SECTION_RE.sub(f"## Story Patterns\n\n{story_block}\n", md)
    else:
        updated = md.rstrip() + new_section

    if not dry_run:
        path.write_text(updated, encoding="utf-8")
    print(f"  {bias_id}: wrote {len(all_snippets)} patterns")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bias", help="Only process this bias_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key and not args.dry_run:
        print("ERROR: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    paths = sorted(KNOWLEDGE_DIR.glob("*.md"))
    paths = [p for p in paths if p.name.upper() != "STYLE_GUIDE.MD"]

    if args.bias:
        paths = [p for p in paths if p.stem == args.bias]
        if not paths:
            print(f"ERROR: bias '{args.bias}' not found", file=sys.stderr)
            sys.exit(1)

    print(f"Generating story patterns for {len(paths)} biases ({BATCHES}×{SNIPPETS_PER_BATCH} each)")
    for path in paths:
        generate_for_bias(path, api_key, args.dry_run)

    print("\nDone. Next: bump TAXONOMY_VERSION in .env then run: python scripts/run_indexing.py")


if __name__ == "__main__":
    main()
