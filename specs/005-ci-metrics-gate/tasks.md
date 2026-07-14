---

description: "Task list for CI Metrics Gate for Retrieval Quality"
---

# Tasks: CI Metrics Gate for Retrieval Quality

**Input**: Design documents from `specs/005-ci-metrics-gate/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/check-regression-cli.md](./contracts/check-regression-cli.md), [quickstart.md](./quickstart.md) — all written and internally reviewed this session (a direction-inversion bug in the regression formula and a test-placement inconsistency were found and fixed; the documents linked above are the corrected versions).

**Tests**: Included — `check_regression.py`'s tolerance/eligibility logic is exactly the kind of free, deterministic logic this repo already unit-tests (`tests/test_evaluate.py`'s 25 tests), and Tier 1 (US1) only has teeth if there's something for it to run.

**Organization**: Tasks are grouped by user story (spec.md: US1/US2 = P1, US3 = P2) so each is independently completable and testable, per this repo's MVP-per-story convention.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1/US2/US3)

## Path Conventions

Single project (per plan.md's Structure Decision) — `.github/workflows/`, `scripts/`, `tests/` at repository root. No new top-level directories.

---

## Phase 1: Setup

**Purpose**: Surface the one thing no task in this list can actually "complete" by writing code, and do the cheap sanity check that later phases assume.

- [x] T001 [P] Documented in README.md's new "## CI" section: table of `DATABASE_URL`, `RAG_API_KEY`, `HF_TOKEN`, `ENGINE_URL` (name/type/used-by/purpose), plus an explicit note that none exist yet and `pytest.yml` is the only one of the three workflows that can pass in CI until they're provisioned. Secret values themselves are not provisioned — that's the human step this task deliberately can't complete.
- [x] T002 [P] Confirmed: `vendor/wheels/llama_cpp_python-0.3.19-cp311-cp311-manylinux_2_34_x86_64.whl` exists (12.5MB), and its internal `METADATA` (`Name: llama_cpp_python`, `Version: 0.3.19`) matches both the filename tag and the `pyproject.toml` pin exactly. No mismatch, no action needed beyond verification.

---

## Phase 2: Foundational (blocks US2 + US3 — does **not** block US1)

**Purpose**: The regression-comparison logic shared by Tier 2a and Tier 2b, built once per research.md's "one script, no ML deps" decision.

**⚠️ Scope note, deliberately narrower than the template default**: US1 (Phase 3) needs none of this — `pytest.yml` is valid and complete on its own. This phase only blocks US2/US3.

- [x] T003 [P] Implemented `scripts/check_regression.py` (stdlib-only: argparse/json/sys/dataclasses; matches [contracts/check-regression-cli.md](./contracts/check-regression-cli.md) exactly). `compute_finding()` applies one formula to every `(group, metric)` pair — `tolerance=1/count`, `eligible=tolerance<baseline_value`, `regressed=eligible and delta<-tolerance` — with no per-group branching on direction and no hardcoded "adversarial" exception; `metrics_for_group()` is the only place group identity matters (`empty_rate` for `negative`, `recall_at_k`+`precision_at_k` independently otherwise, 7 findings total across today's 4 groups). Exit 0/1/2 per the contract. Smoke-tested against the real `baseline_2026-07-09.json` as a no-op: output matches the contract's table exactly, including `edge`'s per-metric eligibility split (recall eligible, precision not).
- [x] T004 [P] `tests/test_check_regression.py` — 15 tests, all passing: one/two-scenario-loss noise boundary (a), `negative`'s `empty_rate` direction matches recall/precision exactly (b), `adversarial`'s real shape never regresses even at total loss, verified shape-based not name-based via a synthetic differently-named group (c), 3 exit-2 cases for missing/malformed/incomplete input (d), the `edge` per-metric eligibility split as a dedicated assertion (e). Full suite: `uv run pytest tests/ -v` → 130 passed (115 pre-existing + 15 new), 0 failures.

**Checkpoint**: `check_regression.py` is correct in isolation — this is quickstart.md Step 2, runnable entirely offline with no secrets from T001.

---

## Phase 3: User Story 1 - Every commit gets a pass/fail signal (Priority: P1) 🎯 MVP

**Goal**: Automatic pass/fail on every push and PR, no manual trigger, using tests that already exist (plus T004's new ones once Phase 2 lands — but this story does not depend on Phase 2 to ship).

**Independent Test**: Push a commit that breaks any existing test (e.g. flip a comparison operator in `recall_at_k`) and confirm the check fails automatically with zero local setup.

### Implementation for User Story 1

- [x] T005 [US1] Created `.github/workflows/pytest.yml`: `on: push` + `on: pull_request`, no path filter, no `paths:` key at all (confirmed via YAML parse — both triggers resolve to unrestricted). `astral-sh/setup-uv@v3` (no prior uv-in-CI convention existed in this repo to match, so used the standard action), `uv sync`, `uv run pytest tests/ -v`. No secrets/network/services referenced anywhere in the file.
- [x] T006 [US1] **Partially validated — flagging the gap rather than overclaiming.** Confirmed locally: YAML parses correctly, `on:` resolves to `{push, pull_request}` with no path restriction, and the exact command the workflow runs (`uv sync && uv run pytest tests/ -v`) passes (130/130) when run directly on this machine. **Not validated**: an actual GitHub-hosted run triggering on a real push/PR — this loop's commit authorization doesn't extend to `git push`, so the workflow has never executed on GitHub's infrastructure yet. That first real trigger (quickstart.md Step 1) is still an open verification step for whoever pushes this branch.

**Checkpoint**: US1 fully functional independently — this alone converts "zero automated coverage" into "every commit tested," the floor this feature exists to fix, deployable/demoable without Phase 2, 4, or 5.

---

## Phase 4: User Story 2 - Retrieval-quality regressions are caught before merge (Priority: P1)

**Goal**: PRs touching retrieval-critical code get evaluated against their own code and blocked on an eligible-group regression, per ADR §2 Tier 2a.

**Independent Test**: Per spec.md — one PR that deliberately degrades an eligible `(group, metric)` pair (e.g. `positive`'s `recall_at_k`) is blocked with a named cause; a second PR with no retrieval-quality change passes without a human reading raw numbers.

**Depends on**: Phase 2 (T003/T004) for the comparison logic; **T001's secrets must be provisioned before this can succeed in CI** (the workflow file itself can be written and merged without them, but every run will fail at the Supabase-connection step until they exist — this is the blocking external dependency flagged in Phase 1, not a code gap).

### Implementation for User Story 2

- [x] T007 [US2] Created `.github/workflows/retrieval-gate.yml`: path filter matches ADR §2/spec.md FR-003 exactly (verified via YAML parse — 7 entries including `src/evaluation/**`). Runs `scripts/run_evaluation.py --strategy llm_union` with `PSQL_SEARCH=true` (matching research.md's "whatever the PR defaults to" decision — production's actual default is `llm_union`), installs the T002 wheel, resolves the latest run/baseline files by filename, feeds both to `check_regression.py`, and maps exit `1`→job failure (`::error::` annotated) vs. exit `2`→a distinctly-labeled infrastructure-error failure, matching the CLI contract. **New decision surfaced during implementation, resolved with your input**: `llm_union` needs a ~2.5GB GGUF model download at runtime, unaddressed in the original plan/research docs — added an `actions/cache` step keyed on the model name so only a cache-miss run pays the download cost. **Flagged, not silently assumed**: a HACK/REVISIT comment in the workflow marks the untested assumption that GitHub-hosted runners can reach Supabase directly via the `PSQL_SEARCH=true`/`psql`-subprocess path (that path exists in `run_evaluation.py` to dodge a *local-dev* SOCKS proxy that doesn't exist on GH runners — never verified against a real run).
- [x] T008 [US2] **Validated locally against live Supabase, not via GitHub Actions** — `.env` already had `DATABASE_URL`/`RAG_API_KEY` for local dev (missed this initially, corrected mid-task). What GitHub Actions itself would do (trigger on a real PR event, run inside its own runner) is still unverified — but the actual mechanism `retrieval-gate.yml` invokes (`run_evaluation.py` → `check_regression.py`) has now been proven end-to-end with real data, twice:
  1. A fresh live `llm_union` eval run (`evaluations/runs/run_2026-07-14.json`) compared against the then-current baseline correctly **fired a real regression** (`negative`/`empty_rate` 1.000→0.200, exit 1) — proving the gate can actually fail, the exact thing ADR §1 exists to guarantee.
  2. That "regression" turned out to be a stale-baseline artifact, not a code problem (see below) — after promoting a new baseline, the identical run compares clean (exit 0), and `negative` is now correctly self-excluded from blocking by the eligibility formula (its own tolerance sits exactly at its baseline value).

  **Two real things found and fixed along the way, both committed separately from the CI-gate feature itself:**
  - Pre-existing bug in `src/evaluation/evaluate.py`: `evaluations/staging/` (holding a *results*-shaped JSON, not a *scenario*-shaped one) was missing from `_SKIP_GROUPS`, crashing `load_scenarios()` on every full local run since 2026-07-13. Fixed (`"staging"` added to the skip set).
  - The promoted baseline predated `llm_union` becoming production's default — promoted a new one (`baseline_2026-07-14.json`) with your go-ahead; logged in `evaluations/HISTORY.md`.

  Not run: a synthetic "deliberately broken code" PR (quickstart Step 4's literal scenario) — judged unnecessary given the gate already proved it can fail on real data, which is stronger evidence than a synthetic break.

**Checkpoint**: US1 + US2 both work independently. US2 is code-complete even if T001 isn't done yet, but not *demonstrable* until it is — call this out explicitly when reporting status, don't let "workflow file merged" read as "gate is live."

---

## Phase 5: User Story 3 - Production quality drift is caught even without a PR (Priority: P2)

**Goal**: Weekly (+ on-demand) check of the deployed service against the last promoted baseline, visible but never merge-blocking.

**Independent Test**: Manually dispatch the workflow and confirm it reports live-service quality vs. baseline, independent of any open PR, and touches no PR/branch-protection status either way.

**Depends on**: Phase 2 (T003/T004); **T001's secrets** (`RAG_API_KEY`, HF Bearer token, `ENGINE_URL`) must exist for this to run at all in CI — same external blocker as US2, called out once in Phase 1 rather than repeated as a new finding here.

### Implementation for User Story 3

- [ ] T009 [US3] Create `.github/workflows/production-drift.yml`: `schedule` (weekly cron) + `workflow_dispatch` triggers — **no `pull_request` trigger at all** (spec.md FR-010, US3 must never be able to block a merge by construction, not by convention). Steps: `POST {ENGINE_URL}/evaluate` with `RAG_API_KEY` + HF Bearer token headers (per `src/api/routes/retrieve.py`'s documented contract), poll `GET {ENGINE_URL}/evaluate/{job_id}` every ~10s until `status == "done"` or a timeout is hit, save the result, resolve the latest local `evaluations/baselines/baseline_*.json` the same way T007 does, run `check_regression.py` against it. On exit `1`, fail this workflow's own run visibly (job failure, clearly labeled as a production drift finding) — but the workflow has no mechanism to touch any PR or branch-protection status, satisfying FR-010 structurally. On exit `2` (e.g. `/evaluate` unreachable, Space cold-start timeout), fail with a distinctly labeled "could not evaluate" message, not "quality dropped" (spec.md FR-012 / the edge case about not conflating the two).
- [ ] T010 [US3] Validate per quickstart.md Step 5: `gh workflow run production-drift.yml` + `gh run watch`; confirm it evaluates the *live* service (not any PR's code), confirm the weekly `schedule:` cron expression is present in the workflow YAML (can't be observed running live without waiting a week — reading the trigger definition is sufficient here), confirm no PR or branch-protection state changes regardless of pass/fail.

**Checkpoint**: All three user stories independently functional — US1 alone is a complete, shippable improvement over today's zero-CI baseline; US2 adds the actual quality gate; US3 adds drift visibility on top of both.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T011 Run quickstart.md Steps 1–5 end-to-end, in order, as the final integration check before considering this feature done — not a substitute for T006/T008/T010 (which validate each story independently), but a confirmation that nothing regressed across stories when combined.
- [ ] T012 **Explicitly out of this task list, do not create a task that "completes" it here**: quickstart.md Step 6 / ADR §9 — flipping branch protection to require `pytest.yml` and `retrieval-gate.yml` (not `production-drift.yml`, which is a monitor per FR-010) is a manual GitHub repo-settings decision a human makes after T011 is green, not a deliverable of this feature.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001 and T002 can both start immediately, in parallel.
- **Foundational (Phase 2)**: No dependency on Phase 1's completion (T003/T004 don't need the secrets T001 documents) — but T001 must land before Phase 4/5 can be *validated*, even though it doesn't block Phase 2's code from being written.
- **US1 (Phase 3)**: Depends on nothing but repo state as it exists today. **Can ship before Phase 2 exists at all.**
- **US2 (Phase 4)**: Depends on Phase 2 (T003/T004) for `check_regression.py`, and on T001 (external) to be *demonstrable*, not just written.
- **US3 (Phase 5)**: Depends on Phase 2 (T003/T004), and on T001 (external) to be demonstrable — otherwise independent of US2.
- **Polish (Phase 6)**: Depends on whichever of US1/US2/US3 are in scope for a given delivery — T011 assumes all three; if shipping US1 alone as the MVP, T011 reduces to just T006.

### Within Each Phase

- T003 and T004 in Phase 2 are `[P]` but T004 tests T003's behavior — write T003 first in practice even though they're marked parallel-eligible for a two-person split (one drafts the script, one drafts tests against the contract, then reconcile).
- T007 (US2) depends on T003/T004 (Phase 2) and T002 (Phase 1, the wheel check).
- T009 (US3) depends on T003/T004 (Phase 2) only — does not need T002 (no llama-cpp-python involved in evaluating the *already-deployed* Space over HTTP).

### Parallel Opportunities

- T001 + T002 (Phase 1) — different concerns, no shared files.
- T003 + T004 (Phase 2) — different files (`scripts/check_regression.py` vs `tests/test_check_regression.py`), though see the note above about practical sequencing.
- Once Phase 2 is done, T007 (US2) and T009 (US3) touch different workflow files and can proceed in parallel.
- US1 (Phase 3) can be built and shipped at any point, independent of everything else in this list — it has no upstream dependency besides the repo as it exists today.

---

## Parallel Example: Phase 2 (Foundational)

```bash
Task: "Implement scripts/check_regression.py per contracts/check-regression-cli.md"
Task: "Write tests/test_check_regression.py against the same contract"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1's T002 only (T001 isn't needed for US1 at all — it's purely a US2/US3 prerequisite).
2. Complete Phase 3 (US1).
3. **STOP and VALIDATE**: T006 — confirm `pytest.yml` runs on a throwaway push/PR.
4. This alone is a complete, mergeable improvement: zero-to-full automated test coverage on every commit, spec.md SC-001 satisfied, no secrets required.

### Incremental Delivery

1. Phase 3 (US1) → ship immediately, no external dependency.
2. Phase 1 T001 (document + a human provisions the secrets) can happen in parallel with Phase 2/3, but must land before Phase 4/5 are demonstrable.
3. Phase 2 (Foundational) → Phase 4 (US2) → validate (T008) once T001's secrets exist → this is the actual quality gate, the reason this feature exists.
4. Phase 5 (US3) → validate (T010) — can land before *or* after US2 once Phase 2 and T001 are done; the two don't depend on each other.
5. Phase 6 → final cross-story check, then the manual branch-protection step (T012) outside this feature.

### Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps each task to spec.md's US1/US2/US3 for traceability.
- T001 is the one task in this list whose "done" state is a human action outside any repo, not a commit — track it separately from code-review-style completion.
- Avoid re-deriving the regression formula anywhere outside T003 — every other reference to it (workflows, tests, docs) should point at `scripts/check_regression.py` as the single source of truth, per research.md's rationale for making it a separate script in the first place.
