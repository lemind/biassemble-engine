#!/usr/bin/env python
"""Run the full indexing pipeline and upsert bias chunks to Supabase.

Usage:
    uv run python scripts/run_indexing.py
"""
import asyncio
import sys
from pathlib import Path

# Make src/ importable when running as a top-level script (not via the package)
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

from src.config import settings
from src.indexing.indexer import run_indexing
from src.indexing.sources.taxonomy import TaxonomySource
from src.providers.sentence_transformer import SentenceTransformerProvider


async def main() -> None:
    print(f"taxonomy_version={settings.taxonomy_version}  model={settings.embedding_model}")

    provider = SentenceTransformerProvider(settings.embedding_model)
    if provider.dimension != settings.embedding_dimension:
        raise RuntimeError(
            f"Dimension mismatch: model={provider.dimension}, config={settings.embedding_dimension}"
        )

    pool = await asyncpg.create_pool(settings.database_url)
    try:
        rows = await run_indexing(TaxonomySource(), provider, pool)
        print(f"\nDone — {rows} new rows  (taxonomy_version={settings.taxonomy_version})")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
