#!/usr/bin/env python
"""Cosine delta probe: compare how closely an old vs new chunk embeds to a target story.

Pass condition: new_score > old_score (no fixed threshold).
For domain paragraph validation (T005), also verify new_score > SIMILARITY_THRESHOLD from .env.

Usage:
    uv run python scripts/probe_chunk.py \\
      --story "The evidence is clear: our policies are working." \\
      --old "Confidence intervals that are too narrow relative to actual outcome distributions" \\
      --new "States an outcome as certain or inevitable without acknowledging the possibility of being wrong"
"""
import argparse
import os
import sys
from pathlib import Path

# huggingface_hub uses httpx which raises on socks:// proxy scheme even when
# the model is already cached. Clear proxy env vars before any library import
# that might instantiate an httpx client.
for _var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
    os.environ.pop(_var, None)

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.providers.sentence_transformer import SentenceTransformerProvider


def _cosine(a: list[float], b: list[float]) -> float:
    va = np.array(a)
    vb = np.array(b)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare cosine similarity of old vs new chunk against a story."
    )
    parser.add_argument("--story", required=True, help="Target story text")
    parser.add_argument("--old", required=True, help="Old chunk text")
    parser.add_argument("--new", required=True, help="New chunk text")
    args = parser.parse_args()

    provider = SentenceTransformerProvider(settings.embedding_model)
    story_vec, old_vec, new_vec = provider.embed_texts([args.story, args.old, args.new])

    old_score = _cosine(story_vec, old_vec)
    new_score = _cosine(story_vec, new_vec)
    delta = new_score - old_score

    print(f"old:       {old_score:.3f}")
    print(f"new:       {new_score:.3f}")
    print(f"delta:     {delta:+.3f}  {'IMPROVED' if delta > 0 else 'REGRESSED'}")
    print(f"threshold: {settings.similarity_threshold:.3f}  "
          f"({'ABOVE' if new_score >= settings.similarity_threshold else 'BELOW'} — relevant for T005 domain paragraphs)")


if __name__ == "__main__":
    main()
