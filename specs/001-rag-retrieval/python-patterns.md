# Python Patterns Reference

Patterns that appear in this codebase, mapped to where you'll implement them. Read this alongside the task you're working on — each entry says what it is, why it's used here, and what an interviewer will likely ask.

---

## T002 — Dataclasses and Pydantic

### `@dataclass` vs `class BaseModel`

```python
from dataclasses import dataclass
from pydantic import BaseModel

@dataclass
class CandidateChunk:       # internal — no validation needed, fast, no serialization
    bias_id: str
    retrieval_score: float

class BiasResult(BaseModel):  # API boundary — validated, serializable to/from JSON
    id: str
    retrieval_score: float
```

**Rule**: dataclasses for internal data that never crosses a service boundary. Pydantic for anything that touches JSON (request bodies, response models, config).

**Interview question**: *"Why not use Pydantic for everything?"* — Pydantic validates every field on construction. For internal objects created thousands of times in a pipeline, that overhead adds up. Dataclasses are plain Python structs.

### `@dataclass(frozen=True)`

Makes the instance immutable (hashable, usable as a dict key). Use when you want tuple-like safety with named fields.

```python
@dataclass(frozen=True)
class ChunkKey:
    bias_id: str
    chunk_type: str
```

**Interview question**: *"How do you make a dataclass hashable?"* — `frozen=True`. Without it, `@dataclass` instances are mutable and not hashable by default.

### `__post_init__` in dataclasses

```python
@dataclass
class FullBiasDocument:
    name: str
    definition: str
    false_positives: str

    def __post_init__(self):
        if not self.false_positives.strip():
            raise ValueError(f"false_positives cannot be empty for '{self.name}'")
```

Runs after `__init__`. Use for validation that can't be expressed in type hints.

---

## T003 — Abstract Base Classes

### ABC pattern

```python
from abc import ABC, abstractmethod

class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...
```

**Why ABC and not Protocol?**
- `ABC`: enforced at class definition time (`TypeError` if subclass doesn't implement abstract methods)
- `Protocol`: structural duck typing — anything with the right methods matches, no inheritance required

Use `ABC` when you control all implementations and want enforcement. Use `Protocol` when you want to describe a shape that third-party objects might already satisfy.

**Interview question**: *"What's the difference between ABC and Protocol?"* — ABC is nominal (you inherit it), Protocol is structural (you just need the right methods). `isinstance(obj, MyProtocol)` works with `@runtime_checkable`.

### `@property` as abstract

```python
@property
@abstractmethod
def model_name(self) -> str: ...
```

The decorator order matters: `@property` must be outermost. Without both decorators, the property won't be flagged as abstract.

---

## T004 — FastAPI Lifespan

### `@asynccontextmanager` lifespan

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    provider = SentenceTransformerProvider(settings.embedding_model)
    pool = await asyncpg.create_pool(settings.database_url)
    app.state.provider = provider
    app.state.pool = pool
    yield
    # shutdown
    await pool.close()

app = FastAPI(lifespan=lifespan)
```

`yield` divides startup (before) from shutdown (after). Everything before `yield` runs once at startup; everything after runs once when the server shuts down.

**Interview question**: *"How do you manage shared resources in FastAPI?"* — lifespan context manager attached to the app. The resource lives in `app.state` and is accessible via `request.app.state`.

---

## T009, T013 — File I/O with pathlib

### `pathlib.Path` over `os.path`

```python
from pathlib import Path

knowledge_dir = Path("knowledge")
for file in knowledge_dir.glob("*.md"):
    content = file.read_text(encoding="utf-8")
    bias_id = file.stem          # "confirmation_bias" from "confirmation_bias.md"
```

`Path` is object-oriented, chainable, and platform-safe. `.stem` gives the filename without extension. `.glob()` returns a generator.

**Interview question**: *"How do you read all `.md` files in a directory?"* — `Path("dir").glob("*.md")`. The old way (`os.listdir` + string manipulation) is not expected in modern Python.

### Generator expressions for memory efficiency

```python
# list comprehension — builds entire list in memory
chunks = [build_chunk(doc) for doc in docs]

# generator — lazy, one item at a time
chunks = (build_chunk(doc) for doc in docs)

# use generator when you immediately iterate (e.g., pass to list() or for loop)
# use list when you need random access or len()
```

---

## T012 — Grouping with defaultdict

### `collections.defaultdict`

```python
from collections import defaultdict

# Grouping CandidateChunk[] by bias_id:
by_bias: dict[str, list[CandidateChunk]] = defaultdict(list)
for chunk in chunks:
    by_bias[chunk.bias_id].append(chunk)

# Now collapse each group:
for bias_id, group in by_bias.items():
    best = max(group, key=lambda c: c.retrieval_score)
```

`defaultdict(list)` means accessing a missing key returns `[]` and adds it, instead of raising `KeyError`.

**Interview question**: *"How would you group a list of objects by a field?"* — `defaultdict(list)` is the idiomatic answer. Alternative: `itertools.groupby` (requires sorted input, more verbose).

### `hashlib.sha256`

```python
import hashlib

def chunk_hash(bias_id: str, chunk_type: str, chunk_text: str, taxonomy_version: str) -> str:
    content = f"{bias_id}|{chunk_type}|{chunk_text}|{taxonomy_version}"
    return hashlib.sha256(content.encode()).hexdigest()
```

`.hexdigest()` returns a 64-character hex string. `.digest()` returns bytes. Always encode strings to bytes before hashing.

---

## T013 — Batching

### Manual batching with slices

```python
def batched(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]

for batch in batched(chunks, settings.index_batch_size):
    embeddings = provider.embed_texts([c.chunk_text for c in batch])
```

Python 3.12 has `itertools.batched()` built-in. For 3.11, write this helper.

**Interview question**: *"How do you process a list in fixed-size batches?"* — `range(0, len(items), batch_size)` with slice notation.

---

## T014 — Context Managers

### Writing your own context manager with `@contextmanager`

```python
import time
from contextlib import contextmanager

@contextmanager
def timer() -> Generator[dict, None, None]:
    result = {}
    start = time.perf_counter()
    try:
        yield result
    finally:
        result["ms"] = int((time.perf_counter() - start) * 1000)

with timer() as t:
    embeddings = provider.embed_query(text)
latency_ms = t["ms"]
```

`@contextmanager` turns a generator function into a context manager. `yield` is the point where `with` body runs. Use `try/finally` to guarantee cleanup even on exception.

**Interview question**: *"What is a context manager? How do you write one?"* — implements `__enter__` and `__exit__`, or use `@contextmanager` decorator. The `with` statement calls them automatically. Used for resource management (files, locks, timers, DB connections).

### Class-based context manager

```python
class TimingContext:
    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)
        return False   # don't suppress exceptions
```

`__exit__` returning `False` (or `None`) lets exceptions propagate. Return `True` to suppress them.

---

## T015 — Registry Pattern

### Dict-based strategy registry

```python
QUERY_STRATEGY_REGISTRY: dict[str, type[QueryStrategy]] = {
    "repeated_story": RepeatedStoryStrategy,
}

def get_query_strategy(name: str) -> QueryStrategy:
    cls = QUERY_STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown query strategy: {name!r}. Available: {list(QUERY_STRATEGY_REGISTRY)}")
    return cls()
```

`{name!r}` in f-strings adds quotes around the value: `"repeated_story"` instead of `repeated_story`. Useful in error messages.

**Interview question**: *"How do you implement the Strategy pattern in Python?"* — ABC for the interface, dict registry for lookup. Avoids `if/elif` chains that need updating whenever a new strategy is added.

---

## T016 — Sorting and max

### `max()` and `sorted()` with `key=`

```python
# Best chunk per bias:
best_chunk = max(group, key=lambda c: c.retrieval_score)

# Sort descending by score:
ranked = sorted(results, key=lambda r: r.retrieval_score, reverse=True)

# More efficient with operator.attrgetter (avoids lambda overhead):
from operator import attrgetter
best_chunk = max(group, key=attrgetter("retrieval_score"))
```

`attrgetter("field")` is equivalent to `lambda x: x.field` but faster and more readable.

**Interview question**: *"How do you sort objects by an attribute?"* — `sorted(items, key=attrgetter("field"))`. Know both lambda and attrgetter.

---

## T017 — Async patterns

### `async/await` and the event loop

```python
async def retrieve(request: RetrieveRequest) -> tuple[list[RetrievedBias], RetrievalMetadata]:
    query = query_builder.build(request)
    embedding = await embed(query)          # I/O — yields control to event loop
    candidates = await searcher.search(embedding)   # I/O — DB query
    results = reranker.rerank(candidates)   # CPU — no await
    return results, metadata
```

`await` suspends the current coroutine and yields control to the event loop, which can run other coroutines. I/O-bound work (DB queries, HTTP calls) benefits from `async`. CPU-bound work (reranking, string processing) doesn't need `await`.

**Interview question**: *"What is the difference between threading and asyncio?"* — asyncio is single-threaded cooperative multitasking. One task runs at a time but voluntarily yields at `await` points. No GIL issues, no race conditions on shared state.

### `asyncio.gather` for concurrent requests

```python
import asyncio
import httpx

async def load_test():
    async with httpx.AsyncClient() as client:
        tasks = [client.post("/retrieve-biases", json=payload) for _ in range(10)]
        responses = await asyncio.gather(*tasks)
```

`asyncio.gather` runs coroutines concurrently. All 10 requests are in-flight simultaneously; total time ≈ slowest single request.

**Interview question**: *"How do you run multiple async operations concurrently?"* — `asyncio.gather(*coroutines)`. Returns results in the same order as inputs.

### `async with` for resource managers

```python
async with pool.acquire() as conn:
    rows = await conn.fetch(SQL, *params)
# connection automatically returned to pool here
```

`async with` calls `__aenter__` and `__aexit__`. asyncpg pool uses this to acquire/release connections without leaking them.

---

## T019 — Metrics computation

### List comprehensions for metrics

```python
# Recall@K for one scenario:
def recall_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    if not expected:
        return 1.0
    hits = sum(1 for e in expected if e in retrieved[:k])
    return hits / len(expected)

# MRR across scenarios:
def mrr(results: list[tuple[list[str], list[str]]]) -> float:
    reciprocal_ranks = []
    for expected, retrieved in results:
        for rank, bias_id in enumerate(retrieved, start=1):
            if bias_id in expected:
                reciprocal_ranks.append(1 / rank)
                break
        else:
            reciprocal_ranks.append(0.0)   # for/else: else runs if loop didn't break
    return sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
```

**Interview question**: *"What does the `else` clause on a `for` loop do?"* — runs if the loop completed without hitting `break`. Useful for "not found" cases. Almost no one knows this exists.

---

## General Python interview topics this codebase covers

| Pattern | Where in codebase | Common interview form |
|---------|------------------|----------------------|
| ABC vs Protocol | EmbeddingProvider, KnowledgeSource, QueryStrategy | "When would you use each?" |
| `@dataclass` vs `BaseModel` | All schemas | "Why not Pydantic everywhere?" |
| `@contextmanager` | TimingContext | "Write me a context manager" |
| `defaultdict` | reranker.py grouping | "Group a list by a field" |
| `max()` with `key=` | reranker.py collapse | "Find max of objects by attribute" |
| `async/await` | retriever.py, searcher.py | "How does asyncio work?" |
| `asyncio.gather` | NFR load test | "Run N requests concurrently" |
| `pathlib.Path` | TaxonomySource | "Read all files in a directory" |
| Generator vs list | embedder batching | "Memory-efficient iteration" |
| `for/else` | MRR computation | Almost always surprises the interviewer |
| `hashlib.sha256` | chunk_builder | "How do you hash a string?" |
| Registry pattern | QUERY_STRATEGY_REGISTRY | "Replace an if/elif chain" |
| `{value!r}` in f-strings | error messages | "How do you add quotes in f-strings?" |
