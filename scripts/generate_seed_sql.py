#!/usr/bin/env python
"""Generate a SQL seed file from local knowledge files — no DB connection needed.

Runs the full local pipeline (load → normalize → chunk → embed) and writes
artifacts/seed_embeddings.sql. Used when run_indexing.py fails due to proxy
TCP timeouts against Supabase.

Usage:
    # 1. Generate
    ALL_PROXY="" all_proxy="" HF_HUB_OFFLINE=1 uv run python scripts/generate_seed_sql.py

    # 2. Apply via Supabase CLI (uses HTTPS Management API, bypasses TCP proxy)
    supabase link --project-ref <project-ref>   # one-time
    supabase db query --linked --file artifacts/seed_embeddings.sql
"""
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.db.queries import TABLE, fmt_vector
from src.indexing.chunk_builder import build_chunks
from src.indexing.embedder import embed_chunks
from src.indexing.normalizer import normalize
from src.indexing.sources.taxonomy import TaxonomySource
from src.providers.sentence_transformer import SentenceTransformerProvider

ARTIFACTS_DIR = Path("artifacts")


def _sql_str(value: str) -> str:
    """Escape and quote a string for SQL — doubles single quotes."""
    return "'" + value.replace("'", "''") + "'"


def _sql_jsonb(obj: object) -> str:
    return _sql_str(json.dumps(obj, ensure_ascii=False)) + "::jsonb"


def _sql_vector(embedding: list[float]) -> str:
    return _sql_str(fmt_vector(embedding)) + "::vector"


def main() -> None:
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    print(f"taxonomy_version={settings.taxonomy_version}  model={settings.embedding_model}")

    provider = SentenceTransformerProvider(settings.embedding_model)
    source = TaxonomySource()

    raw_docs = source.load()
    print(f"loaded {len(raw_docs)} raw documents")

    normalized = normalize(raw_docs)
    chunks = build_chunks(normalized, settings.taxonomy_version)
    print(f"built {len(chunks)} chunks")

    embedded = embed_chunks(chunks, provider, settings.index_batch_size)
    print(f"embedded {len(embedded)} chunks — generating SQL...")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")
    lines: list[str] = [
        f"-- Bias embeddings seed",
        f"-- Generated: {now}",
        f"-- taxonomy_version: {settings.taxonomy_version}",
        f"-- embedding_model: {settings.embedding_model}",
        f"-- Rows: {len(embedded)}",
        f"--",
        f"-- Paste into Supabase SQL Editor and run.",
        "",
    ]

    for ec in embedded:
        c = ec.chunk
        lines.append(
            f"INSERT INTO {TABLE} "
            f"(bias_id,chunk_type,source_section,chunk_text,chunk_hash,"
            f"full_document,embedding,source,metadata,"
            f"taxonomy_version,embedding_model,chunk_index,indexed_at) VALUES ("
            + ",".join([
                _sql_str(c.bias_id),
                _sql_str(c.chunk_type),
                _sql_str(c.source_section),
                _sql_str(c.chunk_text),
                _sql_str(c.chunk_hash),
                _sql_jsonb(asdict(c.full_document)),
                _sql_vector(ec.embedding),
                _sql_str(c.source),
                _sql_jsonb(c.metadata),
                _sql_str(settings.taxonomy_version),
                _sql_str(settings.embedding_model),
                str(c.chunk_index),
                f"'{now}'",
            ])
            + ") ON CONFLICT (taxonomy_version,bias_id,chunk_type,chunk_hash) DO NOTHING;"
        )

    out = Path("artifacts/seed_embeddings.sql")
    out.write_text("\n".join(lines) + "\n")
    size_kb = out.stat().st_size // 1024
    print(f"wrote {out} ({size_kb} KB, {len(embedded)} INSERT statements)")
    print("Paste into: Supabase dashboard → SQL Editor → New query")


if __name__ == "__main__":
    main()
