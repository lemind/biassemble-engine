# Skill: Indexing Pipeline

## Flow

```
knowledge/*.md
      │
      ▼  TaxonomySource.load()           → RawDocument[]
      │
      ▼  normalizer.normalize()          → RawDocument[] (cleaned, validated)
      │
      ▼  chunk_builder.build_chunks()    → chunk dicts + artifacts/chunks.json
      │
      ▼  embedder.embed_batch()          → embeddings + artifacts/embeddings.json
      │
      ▼  indexer.insert()                → bias_embeddings table (PostgreSQL + pgvector)
```

## RawDocument

```python
@dataclass
class RawDocument:
    bias_id: str          # from filename: confirmation_bias.md → "confirmation_bias"
    chunk_type: str       # raw section name: "definition", "examples", etc.
    text: str
    source: str           # "taxonomy", "wiki", "paper", "manual"
    metadata: dict
```

## Normalizer Rules

- Strip excess whitespace and markdown artifacts
- Validate mandatory headings — **error** if `false_positives` missing
- Normalize heading aliases: `False Positive` → `False Positives`
- Remove duplicate `bias_id`s — **error** if duplicates found
- Does NOT touch chunking or embedding logic

## chunk_builder Rules

- `chunk_type` → `ChunkType` enum (SEMANTIC_DEFINITION, SEMANTIC_EXAMPLE, etc.)
- `source_section` → original markdown heading (free text)
- `chunk_text` → `"BiasName — SectionName: <text>"` (bias name prepended)
- `chunk_hash` → `SHA256(bias_id + chunk_type + chunk_text + taxonomy_version)`
- `full_document` → all sections as dict, stored on every row (denormalized intentionally)

### Validation output (required — do not suppress)

```
Knowledge Validation
  30 biases | 150 chunks
  Missing false_positives: 0   ← warn
  Duplicate bias_ids: 0        ← error
  Broken related references: 1 ← warn
  Empty sections: 0            ← warn
  Too short (<50 chars): 2     ← warn
  Too long (>5000 chars): 0    ← warn
```

## Re-index Behavior

- Do NOT delete old rows on re-index
- Insert new rows with updated `taxonomy_version`
- Unique index on `(taxonomy_version, bias_id, chunk_type, chunk_hash)` prevents duplicate inserts
- Caller decides when to delete old versions

## Artifacts

- `artifacts/chunks.json` — inspect after `chunk_builder` to verify text quality
- `artifacts/embeddings.json` — inspect after `embedder` to verify shape
- Both are gitignored
