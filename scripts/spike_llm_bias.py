"""spec-004 T003 — validation spike (GO/NO-GO gate).

Throwaway. Proves a small local GGUF LLM can name catalog biases in a story at all,
and measures cold vs warm latency, BEFORE any integration is built (ADR-003 §2).

Run:  env -u ALL_PROXY -u all_proxy .venv/bin/python scripts/spike_llm_bias.py

Not wired into the app. Reads the catalog straight from knowledge/*.md.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from huggingface_hub import hf_hub_download
from llama_cpp import Llama

REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
GGUF = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
KNOWLEDGE = Path("knowledge")

# ── Catalog: (bias_id, name, indicators) from knowledge/*.md ──────────────────
def load_catalog() -> list[tuple[str, str, list[str]]]:
    cat = []
    for md in sorted(KNOWLEDGE.glob("*.md")):
        if md.stem == "STYLE_GUIDE":
            continue
        text = md.read_text(encoding="utf-8")
        name_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        name = name_m.group(1).strip() if name_m else md.stem
        ind_m = re.search(r"##\s*Indicators\s*\n(.+?)(?:\n##\s|\Z)", text, re.DOTALL)
        inds = []
        if ind_m:
            inds = [re.sub(r"^[-*]\s*", "", ln).strip()
                    for ln in ind_m.group(1).splitlines() if ln.strip().startswith(("-", "*"))]
        # Capped at 3/bias for a tight spike prompt — NOT what T006's real build_prompt
        # necessarily uses. The measured warm-latency figure in research.md is only valid
        # for this trim depth; re-measure at T020 against whatever the real prompt sends.
        cat.append((md.stem, name, inds[:3]))
    return cat


SYSTEM = (
    "You are a cognitive-bias detector. Given a story, identify which of the catalog "
    "biases the narrator exhibits. Choose ONLY from the catalog, using the exact bias_id. "
    'Respond with STRICT JSON only: a JSON array of objects '
    '{"bias_id": "...", "confidence": 0.0-1.0, "evidence": "short quote from the story"}. '
    "Return [] if the story shows no clear cognitive bias. Output nothing but the JSON array."
)


def build_user(story: str, catalog) -> str:
    lines = ["CATALOG (bias_id — indicators):"]
    for bid, name, inds in catalog:
        ind = "; ".join(inds) if inds else ""
        lines.append(f"- {bid} ({name}): {ind}")
    lines += ["", "STORY:", story, "", "Return the JSON array now."]
    return "\n".join(lines)


def parse(raw: str, valid_ids: set[str]):
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return None, "no JSON array found"
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return None, f"json error: {e}"
    kept = [d for d in data if isinstance(d, dict) and d.get("bias_id") in valid_ids]
    return kept, f"{len(data)} parsed, {len(kept)} in-catalog"


# ── Test stories ─────────────────────────────────────────────────────────────
STORIES = {
    "overconfidence (known)": (
        "I've been trading options for eight months and I'm up big. My method just works — "
        "I can read the charts and I know when a stock is about to move. My broker keeps warning "
        "me about risk, but honestly he's too cautious. I've never been wrong when I get that gut "
        "feeling. This next trade is a sure thing; I'm putting in most of my savings because I "
        "already know how it plays out. There's no real chance it goes against me."
    ),
    "sunk_cost / escalation (known)": (
        "We've already sunk two years and most of the budget into this platform rebuild. It's months "
        "behind and the new framework keeps fighting us. The team quietly thinks we should cut it and "
        "restart on something simpler. But we've put so much into it now — walking away would waste "
        "everything we've spent. So we're doubling the team and pushing through. We can't stop after "
        "coming this far."
    ),
    "confirmation (known)": (
        "I'm convinced our new pricing is the reason churn went up. I pulled the three support tickets "
        "that mention price and shared them with the team. When our analyst showed a chart suggesting "
        "onboarding is the real problem, I told her the data was probably measuring the wrong thing. "
        "I only really read the reports that back up the pricing theory. I'm more sure now than I was "
        "last week."
    ),
    "neutral (should be empty)": (
        "The train left at 8:04 and arrived at 9:12. I had a coffee at the station, then walked to the "
        "office, which took about ten minutes. In the afternoon it rained, so I took the bus home instead "
        "of walking. I made pasta for dinner and read for an hour before bed."
    ),
}


def main():
    catalog = load_catalog()
    valid_ids = {bid for bid, _, _ in catalog}
    print(f"catalog: {len(catalog)} biases; prompt example bias: {catalog[0][0]}")

    print("downloading GGUF ...")
    path = hf_hub_download(repo_id=REPO, filename=GGUF)
    print("model file:", path)

    t_load0 = time.monotonic()
    llm = Llama(model_path=path, n_ctx=4096, n_threads=2, verbose=False)
    load_s = time.monotonic() - t_load0
    print(f"model loaded in {load_s:.1f}s\n")

    def run(story):
        user = build_user(story, catalog)
        t0 = time.monotonic()
        out = llm.create_chat_completion(
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user}],
            max_tokens=512, temperature=0.0,
        )
        dt = time.monotonic() - t0
        raw = out["choices"][0]["message"]["content"]
        kept, note = parse(raw, valid_ids)
        return dt, raw, kept, note

    results = {}
    first = True
    for label, story in STORIES.items():
        dt, raw, kept, note = run(story)
        tag = " (COLD — includes first-call warmup)" if first else ""
        first = False
        print(f"── {label}{tag}  |  {dt:.1f}s  |  {note}")
        print("   raw:", raw.strip()[:300].replace("\n", " "))
        if kept is not None:
            print("   biases:", [d["bias_id"] for d in kept])
        print()
        results[label] = (dt, [d["bias_id"] for d in (kept or [])])

    # Warm latency: repeat the overconfidence story 3× (model already warm)
    print("── warm latency (overconfidence ×3) ──")
    warm = []
    for i in range(3):
        dt, *_ = run(STORIES["overconfidence (known)"])
        warm.append(dt)
        print(f"   run {i+1}: {dt:.1f}s")
    print(f"\nSUMMARY: load={load_s:.1f}s  warm p50≈{sorted(warm)[1]:.1f}s")


if __name__ == "__main__":
    main()
