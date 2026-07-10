# Implementation Plan: Generative LLM Bias Selection

**Branch**: `004-add-llm-model` | **Date**: 2026-07-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-add-llm-model/spec.md` · Decision record: `adr/003-generative-llm-bias-selection.md`

## Summary

Add a third, flag-selectable `SelectionStrategy` — `llm_union` — that runs a small local generative LLM (Qwen2.5-1.5B-Instruct, GGUF Q4 via `llama-cpp-python`) which reads a story once and names the cognitive biases it exhibits, combined with the existing vector search as a concurrent complementary signal. The existing `vector_only` and `nli_union` strategies are untouched and remain selectable via `SELECTION_STRATEGY`. Each admitted bias is tagged with the signal that surfaced it (`vector` / `llm` / `both`) in both the response (additive `source` field) and per-request logs. Work is **validation-first**: a gating spike must prove the model detects biases at all before any integration is built. Target: realistic ~200-word story completes in <45s p50 on the free `cpu-basic` tier — replacing the current NLI path that times out (>280s) on real stories.

## Technical Context

**Language/Version**: Python 3.12 (existing engine)

**Primary Dependencies**: FastAPI + uvicorn (existing); `llama-cpp-python` (NEW, for CPU GGUF inference); `huggingface_hub` (NEW, to fetch the GGUF at startup/build); existing `asyncpg`, `sentence-transformers` (vector path), `structlog`, `pydantic`

**Storage**: PostgreSQL/pgvector (existing, unchanged — vector search only). No schema/DB changes.

**Testing**: pytest (existing); plus the eval harness in `src/evaluation/` gated by SC-001..006

**Target Platform**: HuggingFace Space, `cpu-basic` (2 shared vCPU, 16 GB RAM), Linux container

**Project Type**: Single web-service (FastAPI retrieval engine)

**Performance Goals**: Realistic (~200-word) story p50 wall time **< 45s** on `cpu-basic` (SC-002); model loads once at startup; single-request-at-a-time acceptable

**Constraints**: Free tier only — no GPU, no paid hardware, no added recurring cost. Model must be ungated + openly licensed. Additive-only API/config changes. Existing strategies must remain byte-identical in behavior.

**Scale/Scope**: One new strategy module + one new model wrapper + one combiner path + additive config/schema/logging. No changes to `biassemble-core`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution (`.specify/memory/constitution.md`) is an unpopulated template — no ratified principles to gate against. Falling back to the engine's de-facto principles from ADR-001/002 and the repo conventions:

| Principle (de-facto) | Status |
|---|---|
| Additive, non-breaking API/schema changes | ✅ `source` is optional; new `SELECTION_STRATEGY` value; existing paths unchanged |
| Eval gates are the sole arbiter of quality | ✅ recall gates retained (spec SC-005); the spike (SC-001) and latency bar (SC-002, the one the NLI path silently failed) are the new decisive gates |
| Interface is durable, model is a cartridge (ADR-002 §2) | ✅ reuses the existing `SelectionStrategy` Protocol; new strategy is a peer of NLI/vector |
| "No generative LLM in engine" (ADR-002) | ⚠️ **intentionally amended** — see Complexity Tracking; local inference preserves the boundary's intent (privacy/cost/control) |
| Free-tier / no new recurring cost | ✅ ungated Apache-2.0 model, local CPU inference |
| Validation-first before integration | ✅ FR-008 / SC-001 spike gates all downstream tasks |

**Gate result: PASS** (one justified amendment, tracked below).

## Project Structure

### Documentation (this feature)

```text
specs/004-add-llm-model/
├── plan.md              # This file
├── research.md          # Phase 0 — model/runtime/prompt/combiner decisions
├── data-model.md        # Phase 1 — new config, schema field, provenance entity
├── quickstart.md        # Phase 1 — how to run the spike + the strategy locally
├── contracts/
│   └── retrieve-biases-v3.md   # additive: source field + llm_union strategy
├── checklists/
│   └── requirements.md  # spec quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
src/
├── selection/
│   ├── base.py              # SelectionStrategy Protocol + StrategyMetadata (extend: llm_scores, per-bias source)
│   ├── vector_only.py       # UNCHANGED
│   ├── nli_union.py         # UNCHANGED
│   └── llm_union.py         # NEW — LLM + concurrent vector, union combine, source tagging
├── llm/                     # NEW module (peer of src/nli/)
│   ├── __init__.py
│   ├── generator.py         # NEW — llama-cpp-python wrapper: load GGUF, prompt, strict-JSON parse
│   └── prompt.py            # NEW — story + catalog → prompt; output schema + repair
├── nli/                     # UNCHANGED (classifier, combiner, hypothesis_loader)
├── config.py                # extend: llm_model_repo, llm_gguf_file, llm_* knobs; accept selection_strategy="llm_union"
├── schemas/
│   └── response.py          # extend: BiasResult.source: Literal["vector","llm","both"] | None
└── api/
    └── app.py               # extend: startup branch for "llm_union" (load generator, wire strategy)

tests/                       # flat layout (existing convention: tests/test_*.py)
├── test_llm_prompt.py       # generator JSON parse/repair
├── test_llm_union.py        # llm_union end-to-end
├── test_strategy_switch.py  # flag switching, existing strategies unchanged
└── test_llm_source.py       # per-bias source in response + logs

scripts/                     # spike script for the gating validation (throwaway-friendly)
```

**Structure Decision**: Single web-service. The new LLM code mirrors the existing `src/nli/` module layout exactly (a `generator.py` analogous to `classifier.py`), and the new `llm_union.py` sits beside `nli_union.py` under the existing `SelectionStrategy` Protocol. This maximizes symmetry with the proven NLI path and keeps the model swappable per ADR-002 §2.

**Considered and deferred — full pipeline decomposition** (`Selector`/`Retriever`/`Combiner`/`Validator`/`Logger` as separate modules). It's a cleaner long-term shape and aligns with the eventual harness direction, but with a single strategy implementation it's premature abstraction (YAGNI) and would diverge from the established `nli_union.py` one-module pattern. We adopt the *separation of concerns* it's really after — parsing is an explicit staged pipeline (research R4: extract→schema→catalog, each logged) and combine/rank is a distinct step — while keeping it inside `llm_union.py`. Revisit the module split when a second generative strategy or the eval-harness refactor actually needs it.

**Startup robustness principle**: only model **load** failure aborts boot (parity with the NLI branch); the startup **warmup** is informational — its failure is logged, not fatal, so a transient hiccup can't prevent the Space from booting (task T008).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| Crossing ADR-002's "no generative LLM in engine" boundary | The NLI mechanism is O(N_labels)=82 CPU passes and times out on real stories (measured >280s); a read-once generative model is the only free-tier mechanism that completes | Keeping NLI: measured failure in production, not tunable. Moving generation to core: duplicates core's Gemini and abandons the grounded local-retrieval design + the future fine-tune-on-own-data flywheel. Local inference preserves the boundary's real intent (no external API, no data egress, no per-call cost). |
| New `llama-cpp-python` dependency | Raw `transformers` CPU generation is memory-bandwidth-bound and ~4× slower than Q4 GGUF; GGUF is what makes <45s viable on 2 vCPU | Raw `transformers`: too slow to hit SC-002 on free hardware. (Kept as a fallback if the wheel fails to build — Phase 0 records the risk.) |

## Phase notes

- **Phase 0 (research.md)**: lock model choice + fallback ladder (0.5B ↔ 1.5B ↔ 3B), GGUF quant level, `llama-cpp-python` install/build risk on the Space, prompt + strict-JSON strategy, llm↔vector union rule + score scales, source-tagging semantics, latency budget breakdown.
- **Phase 1 (data-model.md, contracts/, quickstart.md)**: config additions, `BiasResult.source` field, `StrategyMetadata` extension, provenance record; additive contract doc; quickstart that runs the spike **first**.
- **Phase 2 (tasks.md)**: created by `/speckit-tasks`. Task 1 is the gating spike; nothing else starts until it's green.
