# Quickstart: CI Metrics Gate for Retrieval Quality

Feature `005-ci-metrics-gate`. This is the §6 validation sequence from `adr/004-ci-metrics-gate.md`, made runnable. **Do not flip branch protection to require these checks (tasks.md's final task) until every step here is green.**

## Step 0 — Prerequisite secrets exist (blocks Steps 3–5)

Tiers 2a/2b cannot run at all without these in this repo's GitHub Actions settings (none exist as of this writing):

```
DATABASE_URL       # Supabase connection string
RAG_API_KEY        # deployed Space auth
<HF Bearer token>  # deployed Space auth (private Space)
ENGINE_URL         # deployed Space base URL — plain repo variable, not secret
```

Step 1 (pytest) needs none of these and can ship independently.

## Step 1 — Unit gate runs on its own

```bash
# local sanity check before trusting the workflow file
uv run pytest tests/ -v
```

Expect: all existing tests pass, including the new `tests/test_check_regression.py`. Then confirm `.github/workflows/pytest.yml` triggers on a throwaway push/PR with no path filter.

## Step 2 — Regression checker is correct in isolation (no CI, no eval run needed)

```bash
# no-op: run vs itself
python scripts/check_regression.py --run evaluations/runs/run_<latest-date>.json \
                                    --baseline evaluations/baselines/baseline_<latest-date>.json
echo $?   # expect 0 — a run compared to the baseline it *became* should show delta=0 everywhere
```

```bash
# synthetic regression: hand-edit a copy of the run JSON to zero out `positive`'s recall_at_k,
# then check it against the real baseline
python scripts/check_regression.py --run /tmp/broken_run.json \
                                    --baseline evaluations/baselines/baseline_<latest-date>.json
echo $?   # expect 1 — positive is gate-eligible (tolerance 0.25 < baseline 0.875), full loss trips it
```

```bash
# adversarial edge case from ADR §4 — confirm it reports but does NOT flip the exit code
python scripts/check_regression.py --run /tmp/broken_adversarial_run.json \
                                    --baseline evaluations/baselines/baseline_<latest-date>.json
echo $?   # expect 0 even with adversarial's recall_at_k zeroed out — table shows it, exit code ignores it
```

## Step 3 — Retrieval-gate workflow, no-op pass (needs Step 0's secrets)

Open a throwaway PR touching only `src/retrieval/query_builder.py` with a no-op comment change. Confirm `.github/workflows/retrieval-gate.yml`:
- triggers (path filter matched)
- runs `scripts/run_evaluation.py` against Supabase successfully
- feeds the result to `check_regression.py`
- the PR check passes (Δ≈0 vs baseline)

**Flakiness risk, read before running**: `llm_union` (the PR's default, per `space-vars.env`) has real run-to-run variance — `HISTORY.md` records `positive` recall swinging `0.562`–`0.875` across otherwise-identical runs, which is bigger than `positive`'s own `0.25` tolerance. A no-op PR *can* legitimately fail this check by bad luck alone, purely from LLM sampling variance, not from anything the PR changed. For **this specific validation step** (proving the mechanism works, not testing `llm_union`'s actual quality), override the strategy to something deterministic — `scripts/run_evaluation.py`'s `--strategy vector_only` flag (same override the deployed `/evaluate?strategy=vector` endpoint exposes for quick smoke tests) — so a failure here means "the gate is broken," not "the LLM sampled differently this time." The real `retrieval-gate.yml` workflow still runs the PR's actual default strategy in production, per research.md's decision — this override is a one-off for isolating Step 3's proof, not a change to what T007 does normally. If you do hit a flake with `llm_union` on this step, re-run once before concluding the gate itself is wrong.

## Step 4 — Retrieval-gate workflow, deliberate-break fail (per ADR §6 — use an eligible group)

Open a second throwaway PR that flips `settings.similarity_threshold` to an absurd value (e.g. `0.99`), touching `src/config.py` — add it to the workflow's path filter for this test only, or temporarily widen the filter. Confirm the check **fails** and the failure message names `positive` or `negative` (an eligible group), not `adversarial`. This is the proof the gate can actually fail — the exact failure mode ADR §1 exists to avoid repeating (the old `biassemble-core` eval workflow that could never fail).

## Step 5 — Production drift monitor, manual dispatch

```bash
gh workflow run production-drift.yml
gh run watch
```

Confirm it calls the deployed Space's `POST /evaluate`, polls to completion, runs `check_regression.py` against the live result, and — regardless of pass/fail — does **not** touch any PR or branch protection status. Confirm the weekly `schedule` trigger is present in the workflow file (can't be tested live without waiting a week; reading the cron expression is sufficient here).

## Step 6 — Only after Steps 1–5 are all green

Enable branch protection requiring `pytest.yml` and `retrieval-gate.yml` (not `production-drift.yml` — it's a monitor, not a merge gate, per FR-010). This step is manual, in GitHub's repo settings, and out of scope for this feature's own tasks (ADR §9) — it's the human decision that consumes everything this feature built.
