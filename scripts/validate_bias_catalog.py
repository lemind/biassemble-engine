#!/usr/bin/env python
"""Validate SFT training-data rows against the live, DB-sourced bias catalog.

Single source of truth for "what's a valid bias_id" during dataset construction —
imported by scripts/label_sft_stories.py and scripts/assemble_sft_dataset.py
(data-model.md's BiasCatalogSnapshot decision). Does NOT hardcode the 38-id
catalog: reuses src/llm/prompt.py's load_catalog(), the same DB-sourced query
path production already uses, so this stays correct if the taxonomy changes.

Usage (manual sanity check):
    uv run python scripts/validate_bias_catalog.py
"""

import asyncio

import asyncpg

from src.config import settings
from src.llm.prompt import load_catalog


class _SingleConnPool:
    """Wraps a single asyncpg connection with the `.acquire()` async-context-manager
    interface load_catalog() expects from a real pool — avoids opening a full pool
    for one query. Same pattern as scripts/run_evaluation.py's _load_catalog_once()."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc) -> None:
        return None


async def _load_valid_bias_ids_once() -> set[str]:
    """One-off asyncpg connection to fetch the live catalog's bias_ids."""
    conn = await asyncio.wait_for(
        asyncpg.connect(settings.database_url, statement_cache_size=0), timeout=10
    )
    try:
        pool_like = _SingleConnPool(conn)
        catalog = await load_catalog(pool_like, settings.taxonomy_version)
        return {bias_id for bias_id, _name, _indicators in catalog}
    finally:
        await conn.close()


def load_valid_bias_ids() -> set[str]:
    """Sync entrypoint — queries the live catalog once, returns the current set
    of valid bias_ids. Call once per script run, not per row."""
    return asyncio.run(_load_valid_bias_ids_once())


def validate_row(bias_ids: list[str], valid_ids: set[str]) -> bool:
    """True iff every id in bias_ids is present in valid_ids. Empty list is valid
    (negative examples carry no bias_ids). Reject-the-whole-row semantics — the
    caller must not coerce or silently drop just the invalid entries; if this
    returns False, the entire row is excluded from the dataset (spec.md FR-005,
    contracts/sft-dataset-schema.md rule 1)."""
    return all(b in valid_ids for b in bias_ids)


if __name__ == "__main__":
    ids = load_valid_bias_ids()
    print(f"Live catalog: {len(ids)} valid bias_ids")
    for bias_id in sorted(ids):
        print(f"  {bias_id}")
