# engine ADR-004 — CI Metrics Gate for Retrieval Quality (Spec 005)

### Status: PROPOSED · Started: 2026-07-14
### This is a prompt-ADR + spec-kit plan: paste into any AI session running spec 005. The session's job is to execute THIS plan and refuse scope beyond §9.

---

## 1. Context (evidence, not opinion)

The eval *harness* is already mature — this is not a build-from-scratch:

- `src/evaluation/evaluate.py` computes Recall@5, Precision@5, MRR, nDCG@5, and `empty_rate` per scenario group (`positive`, `negative`, `edge`, `adversarial`), and `compute_deltas()` already diffs a run against the latest promoted baseline (`evaluations/baselines/baseline_*.json`).
- `tests/test_evaluate.py` has 25 deterministic, network-free unit tests covering the metric functions themselves (recall/precision/MRR/nDCG edge cases, aggregation, delta computation).
- `scripts/run_evaluation.py` runs the full harness locally against live Supabase; `POST /evaluate` (`src/api/routes/retrieve.py`) runs the identical harness on the deployed HF Space as an async job (`GET /evaluate/{job_id}` polls), used to produce the "LIVE SERVER eval" numbers already in `evaluations/HISTORY.md`.
- Per-group targets are already documented in `HISTORY.md` (positive ≥0.85, negative ≥0.90, edge ≥0.583, adversarial ≥0.333) — but only as prose. Nothing reads them and exits non-zero.

The gap is entirely on the *enforcement* side:

- `.github/workflows/` contains exactly one workflow (`build-llama-wheel.yml`), a manual, one-time wheel build. **No workflow runs `pytest`.** Nothing executes automatically on push or PR — not even the 25 free, deterministic metric tests that already exist.
- `compute_deltas()` output is only ever printed to a human's terminal or returned in a JSON blob a human reads — never checked as pass/fail anywhere.
- N is tiny per group (2–5 scenarios). `HISTORY.md` says this explicitly, repeatedly: *"pos_r@5=0.875 is on N=4 stories — one story = ±0.25; statistically fragile."* A zero-tolerance delta gate would flap on nothing but eval noise.
- Current production strategy (`llm_union`, deployed default per `space-vars.env`) sits at positive-recall 0.562 — below its own `HISTORY.md` target of 0.85. That gap is a known, tracked fine-tune target (see ADR-003 §10), **not a regression**. A gate built on absolute targets would leave `main` red today, before any new code is even touched — the opposite of a useful signal.
- The deployed Space's `POST /evaluate` answers with whatever code is *currently live on HF*, not the code sitting in an open PR. Hitting it verifies production health; it does not gate a candidate diff.

## 2. Decision

Two tiers, deliberately mirroring the mock-every-commit / real-gated-and-scheduled split already adopted in the sibling `biassemble-core` repo — same shape, because the underlying cost/determinism tradeoff is the same one:

**Tier 1 — unit gate, every push + every PR, no path filter.**
Runs `pytest` (full suite, which already includes the 25 metric-function tests in `tests/test_evaluate.py`). This closes the actual gap: today *nothing* runs automatically, not even the free deterministic checks. No network, no DB, no model download — under a minute. Blocks merge on any failure.

**Tier 2a — retrieval regression gate, PRs touching retrieval-critical paths.**
Path-filtered trigger: `src/retrieval/**`, `src/nli/**`, `src/llm/**`, `src/selection/**`, `src/evaluation/**`, `evaluations/**`, `hypotheses/**` — `src/evaluation/**` is included deliberately: a change to `recall_at_k`/`precision_at_k`/`empty_rate` themselves in `evaluate.py` can pass every unit test (the math is internally consistent) while silently shifting what the numbers *mean*, and only a real eval run against a real baseline would catch that; Tier 1 alone can't. Runs `scripts/run_evaluation.py` in the CI runner against **the PR's own checked-out code**, over live Supabase (needs a `DATABASE_URL` secret in this repo — does not exist yet). `vector_only` + `nli_union` always run (cheap: sentence-transformer + DeBERTa weights, no compiled extensions). `llm_union` runs too, using the prebuilt `vendor/wheels/llama_cpp_python-*.whl` (already committed, already proven to install in seconds on an `ubuntu-22.04` runner per `build-llama-wheel.yml`'s glibc analysis — no from-source compile needed).

- **Gate rule is regression, not absolute target** (explicit choice, not a default): fail if a group's quality metric drops by more than **one scenario-equivalent** vs the latest promoted baseline. Tolerance = `1 / count` for that group — the same granularity `HISTORY.md` already reasons in ("one story = ±0.25" for N=4), not an arbitrary epsilon. `HISTORY.md`'s absolute targets stay as documented, non-blocking aspirational SLOs — this ADR does not enforce them and does not change them.
- **The gated metric is group-dependent, not always `recall_at_k`/`precision_at_k`.** For `positive`/`edge`/`adversarial`, those two are the right quality signal. For `negative`, both are a renamed copy of the same 0/1-per-story "did it return anything" indicator (`recall_at_k([], [])=1.0`, else `0.0`, whenever `expected=[]` — identical in every case to `not retrieved`), so the harness's own `empty_rate` is the clearer, self-documenting metric to gate — same number, but named for what it actually checks, and matching how `HISTORY.md`'s own gate table already frames the negative row. No direction inversion is needed: `empty_rate`, like `recall_at_k`/`precision_at_k`, is already oriented so higher is better, so the identical `delta < -tolerance` rule applies — regression is `empty_rate` **decreasing** (engine starts returning results on no-bias stories). Only the metric *name* differs per group, not the comparison direction. Full formula and the small-N boundary case are worked out in §4.
- This is intentionally the "regression gate" option, not "absolute threshold" or "absolute-as-warning" — chosen so CI is green today and only trips on an actual introduced regression, not on the pre-existing, already-tracked fine-tune gap.

**Tier 2b — production drift monitor, weekly schedule + manual `workflow_dispatch`.**
Hits the deployed HF Space's `POST /evaluate` (auth: `RAG_API_KEY` + HF Bearer token — both GH secrets, not yet present) instead of running locally. Same regression rule, but comparing the *live production* run to the latest promoted baseline. This tier is a monitor, not a merge gate — there's no PR to block, since it's checking what's already shipped. On regression it should fail its own workflow run loudly (visible in Actions) but must not touch branch protection.

## 3. Architecture

```
push / PR (any file)
  └─► Tier 1: pytest (unit) ──────────────────────► blocks merge

PR touching src/retrieval|nli|llm|selection/**, evaluations/**, hypotheses/**
  └─► Tier 2a: run_evaluation.py against PR code + live Supabase
        compare group_metrics vs evaluations/baselines/baseline_*.json
        per eligible (group, metric) pair (1/count < baseline_value): delta < -(1/count)
        (metrics = recall_at_k AND precision_at_k, checked independently;
         empty_rate for negative) ────────────────────────────────────► blocks merge
        ineligible (group, metric) pairs (both of adversarial's, today;
         edge's precision_at_k) ────────────────────────────────────────► reported only

weekly cron + manual dispatch
  └─► Tier 2b: POST /evaluate on deployed HF Space, poll GET /evaluate/{job_id}
        compare vs baseline, same tolerance ─────────────────────────► visible failure, no merge to block
```

Baseline promotion (`--promote`) stays a **manual, human decision** — unchanged from today. Nothing in this ADR auto-promotes a baseline from a CI run; that would let a gradually-regressing series of PRs each "pass" against an already-degraded baseline. A human runs `--promote` deliberately, same as now, after judging a run trustworthy.

## 4. Regression-tolerance mechanics (worked example)

`GroupMetrics.count` already carries the scenario count per group — the tolerance formula reads directly off data the harness already produces, no new field:

```
tolerance(group)  = 1 / group.count
metrics(group)    = { empty_rate }                     if group == "negative"
                   = { recall_at_k, precision_at_k }    otherwise
for each m in metrics(group):
    eligible(group, m) = tolerance(group) < baseline_value(group, m)
    fail if: eligible(group, m) and delta(group, m) < -tolerance(group)
```

`recall_at_k` and `precision_at_k` are gated **independently**, not as a pair that both have to fail — a PR that keeps recall intact but makes the engine noisier (more junk returned alongside the correct answers) should still be caught on precision alone. That means **eligibility is computed per (group, metric), not per group**: a group can be gate-eligible on one metric and not the other, because they have different baseline values even though they share the same `tolerance = 1/count`. `empty_rate` is defined the same "higher is better" way as `recall_at_k`/`precision_at_k`, so there is no separate inverted comparison to get backwards — only which metric(s) apply changes per group, never the comparison direction.

**Normal case — `positive`, `count=4`, baseline `recall_at_k=0.875`.** A PR that breaks one previously-correct scenario drops it to `0.625` (`Δ=-0.25`), which equals `-tolerance` exactly. With `<` (strict), this passes — losing exactly one scenario is within the noise band for N=4, the same granularity `HISTORY.md` already tolerates. Losing *two* stories (`Δ=-0.50`) is strictly past tolerance and fails. A same-story score wobble from `0.875` to `0.85` (`Δ=-0.025`, a partial-credit shift, not a full miss) stays under tolerance and passes.

**`negative`, `count=5`, baseline `empty_rate=1.0`.** Same `1/count=0.20` tolerance, same `< -tolerance` rule, just on `empty_rate` instead of `recall_at_k`: dropping to `0.80` (`Δ=-0.20`, one story starts leaking a false positive) passes as noise; dropping to `0.60` (two stories) fails.

**Per-metric eligibility split — `edge`, `count=2`, real baseline values (`baseline_2026-07-09.json`): `recall_at_k=0.833`, `precision_at_k=0.400`.** `tolerance = 1/2 = 0.50` for both, since it only depends on `count`. `recall_at_k`: `0.50 < 0.833` → **eligible**, blocking. `precision_at_k`: `0.50 < 0.400` is **false** → **ineligible**, reported only — same group, same tolerance, opposite eligibility, because the two metrics don't share a baseline value. This is the concrete case that shows eligibility has to be checked per metric: computing it once per group and applying it to both would have wrongly made `edge`'s precision blocking (it can't distinguish "one story's precision wobble" from "precision signal gone" any better than `adversarial` could on recall — see below).

**Boundary case — `adversarial`, `count=2`, baseline `recall_at_k=0.333`, `precision_at_k=0.267`.** `tolerance = 1/2 = 0.50`. Since both metrics are `∈ [0,1]` per story, neither can drop by more than its own baseline — the floor is `Δ ≥ -baseline_value` for each. `0.50` exceeds both `0.333` and `0.267`, so both are **unsatisfiable**: losing every adversarial scenario only reaches `Δ=-0.333` (recall) or `Δ=-0.267` (precision), neither of which trips a `0.50` tolerance. The `1/count` tolerance formula silently stops being able to fail exactly when `1/count ≥ baseline_value` — true for both of `adversarial`'s metrics today.

Rather than patch this with a tighter cap or a non-strict comparison (both of which either reopen the "one scenario = noise" hole above or land back on the same unsatisfiable boundary — `min(1/count, baseline_value)` with strict `<` is *still* unsatisfiable, since it caps tolerance at exactly the unreachable floor), **a (group, metric) pair is only eligible for the blocking gate when `1/count(group) < baseline_value(group, metric)`.** Both of `adversarial`'s metrics fail that check today and are **reported, not blocking**, in Tier 2a/2b output until its N grows past `count=4` (`1/4=0.25 < 0.267`, the tighter of its two baselines) — the 2026-07-13 staged blind-spot batch (`evaluations/staging/blind_spot_eval_2026-07-13.json`, not yet promoted) is the concrete path there — or its baseline scores improve past `0.5`. T002's checker computes this eligibility from data already in `GroupMetrics`, not a hardcoded exception list, so it re-includes each `(group, metric)` pair automatically once its own threshold is crossed, independent of its sibling metric.

## 5. Secrets / inputs this needs (none exist yet — you set these, I can't)

- `DATABASE_URL` — GH Actions secret, for Tier 2a's direct Supabase connection from the runner.
- `RAG_API_KEY` and the HF Bearer token — GH Actions secrets, for Tier 2b's calls to the deployed Space (same pair used in `reference-hf-space-private` local workflows, just needs to land in this repo's Actions secrets too).
- `ENGINE_URL` — plain repo variable (not secret), the deployed Space's base URL, for Tier 2b.

## 6. Eval plan (what this ADR's own rollout must demonstrate before merge)

- Tier 1 runs green on the current branch with zero code changes needed (the 25 tests already pass locally — CI wiring is the only new thing).
- Tier 2a, run once manually against `main`'s current baseline with no code changes, produces a `Δ=0` no-op pass — proves the tolerance formula doesn't false-positive on a no-change diff.
- Tier 2a, run against a deliberately-broken branch (e.g. flip `similarity_threshold` to an absurd value), fails — proves the gate actually catches a real regression, not just a smoke test that can't fail (the exact failure mode this ADR exists to avoid repeating). Use an *eligible* group for this check (`positive` or `negative`) — `adversarial` is exempt from blocking per §4 and would falsely look like the gate is broken.
- Tier 2b runs once manually against the live Space and produces a believable, non-flaky delta vs baseline.

## 7. Task list (spec-kit format — detail lives in tasks.md)

- T001 — `.github/workflows/pytest.yml`: Tier 1, push + PR, no path filter.
- T002 — CI-side regression checker: a small script (no torch/model deps) that loads a run's `group_metrics` + a baseline JSON, applies §4's per-group metric/direction/eligibility rules, and exits non-zero on breach in an eligible group (ineligible groups are logged, not enforced). Shared by Tier 2a and 2b so the rule lives in one place.
- T003 — `.github/workflows/retrieval-gate.yml`: Tier 2a, path-filtered PR trigger, installs `vendor/wheels/*.whl`, runs `scripts/run_evaluation.py`, feeds output to T002's checker.
- T004 — `.github/workflows/production-drift.yml`: Tier 2b, weekly cron + `workflow_dispatch`, calls `POST /evaluate` + polls, feeds result to T002's checker.
- T005 — document the required secrets (§5) in README or CONTRIBUTING so the gap is visible to whoever sets up branch protection.
- T006 — validate per §6 (no-op pass + deliberate-break fail) before flipping branch protection to require these checks.

## 8. Out of scope (refuse these in-session)

- Changing or re-deriving the `HISTORY.md` absolute targets — those stay as documented aspirational SLOs, untouched.
- Auto-promoting baselines from CI — promotion stays manual (§3).
- Fixing the `llm_union` positive-recall gap itself (that's the ADR-003 fine-tune track, not this one).
- Branch-protection configuration (requiring these checks in GitHub's repo settings) — a follow-up action once T006 validates the gate isn't flaky, not part of this ADR's build.
- Extending the gate to `biassemble-core`'s eval workflow — separate repo, separate (still-open) fix.

## 9. Consequences

- CI goes from zero automated coverage to a real, two-tier signal, without turning `main` red on day one (regression gate, not absolute).
- New ongoing cost: Tier 2a adds Supabase + (for `llm_union`) llama.cpp inference time to any PR touching retrieval code — bounded, but not free, and only on the path-filtered subset.
- New secrets to manage (§5) — a small ongoing maintenance surface (rotation, scoping) that didn't exist before.
- The `1/count` tolerance is only as good as the tiny N behind it; as `evaluations/*` groups grow (the 2026-07-13 blind-spot batch is a candidate), tolerance tightens automatically since it's `1/count`-derived, not hardcoded — no follow-up tuning needed when N grows.

## 10. Execution log

*(none yet — PROPOSED)*
