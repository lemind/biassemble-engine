# Feature Specification: CI Metrics Gate for Retrieval Quality

**Feature Branch**: `004-metrics-gate`

**Created**: 2026-07-14

**Status**: Draft

**Input**: User description: "CI metrics gate for biassemble-engine retrieval quality — formalize the decisions already made in adr/004-ci-metrics-gate.md: a unit-test gate on every push/PR, a retrieval-regression gate on PRs touching retrieval-critical code (comparing group metrics to the latest promoted baseline with a per-group regression tolerance), and a weekly production-drift monitor against the deployed HF Space. No CI runs automatically today."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every commit gets a pass/fail signal (Priority: P1)

A maintainer pushes a commit or opens a PR against `biassemble-engine`. Without doing anything extra, they get an automatic pass/fail signal on whether the change broke anything the existing test suite already checks — including the metric-computation logic itself (recall/precision/MRR/nDCG/empty-rate math, baseline-delta math).

**Why this priority**: This is the floor. Right now zero automated checks run on any commit — a maintainer only finds out something is broken when they think to run tests by hand, or when it reaches production. This alone converts "hope someone remembers to test" into "always tested."

**Independent Test**: Push a commit that breaks a metric-function test (e.g. flip a comparison operator in the recall calculation) and confirm the check fails automatically, with no other tier needed to prove value.

**Acceptance Scenarios**:

1. **Given** a new commit is pushed to any branch, **When** the commit lands, **Then** the full test suite runs automatically and the commit is marked pass or fail without anyone triggering it manually.
2. **Given** a pull request is opened, **When** the PR is created or updated, **Then** the same automatic check runs and its result is visible on the PR.
3. **Given** a test fails, **When** the check completes, **Then** the failure is visible to the maintainer without them needing to run anything locally first.

---

### User Story 2 - Retrieval-quality regressions are caught before merge (Priority: P1)

A maintainer opens a PR that changes retrieval logic (query building, NLI hypotheses, LLM prompting/selection, or the evaluation scenario sets themselves). Before they can merge, the system runs the real quality evaluation against that PR's own code and tells them whether retrieval quality — measured the same way it's already measured today — got meaningfully worse compared to the last agreed-good result, without them needing to remember to run the eval script by hand and read the printed numbers themselves.

**Why this priority**: This is the actual "quality gate" — the reason this feature exists. Silent retrieval-quality regressions are the failure mode this whole eval harness was built to catch, and today nothing enforces it; a regression can merge and only surface later as a user-facing complaint or a number someone happens to notice next time they run the script by hand.

**Independent Test**: Open a PR that deliberately degrades retrieval quality on a group that is currently large/well-established enough to gate (see Assumptions), and confirm the PR is blocked with a clear explanation of which group regressed and by how much. Open a second PR with no retrieval-affecting change and confirm it passes without a maintainer needing to interpret raw numbers.

**Acceptance Scenarios**:

1. **Given** a PR modifies retrieval-critical code, **When** the PR is opened or updated, **Then** the system runs the same evaluation scenarios used today and compares results to the last agreed-good (promoted) result.
2. **Given** a PR's retrieval quality drops by more than the tolerated noise band for a group that is large/reliable enough to gate, **When** the comparison completes, **Then** the PR is blocked and the maintainer is told which group regressed and by how much.
3. **Given** a PR's retrieval quality is unchanged or improved, **When** the comparison completes, **Then** the PR is not blocked by this check.
4. **Given** a PR touches only unrelated code (e.g. documentation, unrelated API routes), **When** the PR is opened, **Then** this evaluation does not run at all — it only applies to retrieval-critical changes.
5. **Given** a group's historical result set is too small or too low-scoring for a one-story swing to be distinguishable from a total loss of signal in that group, **When** evaluation runs, **Then** that group's result is still shown to the maintainer but does not by itself block the PR.

---

### User Story 3 - Production quality drift is caught even without a PR (Priority: P2)

Without any code change at all, quality can still drift in production — a hosted model updates its behavior, an external dependency changes, or something about the live environment shifts. On a regular cadence, the system checks the live, deployed service the same way it checks a PR, and tells the team if production quality has drifted from the last agreed-good result — without a maintainer needing to remember to check.

**Why this priority**: Lower priority than the merge-time gate because it doesn't block anything and nothing is silently getting worse *right now* without it — but without it, a drift that isn't tied to any specific merged PR (e.g. a hosted model quietly changing) would never be noticed until a user complains.

**Independent Test**: Trigger this check manually against the live service and confirm it reports current quality vs. the last agreed-good result, independent of whatever code is sitting in any open PR.

**Acceptance Scenarios**:

1. **Given** no code changes have occurred, **When** the scheduled check runs, **Then** it evaluates the currently deployed, live service (not any particular PR's code) and compares results to the last agreed-good result.
2. **Given** the live service's quality has drifted below the tolerated noise band for a gate-eligible group, **When** the scheduled check completes, **Then** the drift is reported clearly enough for a maintainer to notice and act on it.
3. **Given** this check finds a drift, **When** it fails, **Then** no in-progress or already-merged PR is blocked by it — it only surfaces the finding.
4. **Given** a maintainer wants to check production quality right now instead of waiting for the schedule, **When** they trigger the check manually, **Then** it runs on demand.

---

### Edge Cases

- What happens when the evaluation scenario data itself changes in the same PR that changes retrieval code (i.e. the "expected answers" move at the same time as the code)? The comparison still runs against the last promoted baseline; a maintainer reviewing the diff is expected to judge whether a resulting "regression" reflects a real quality drop or a scenario-set correction — this feature does not attempt to distinguish the two automatically.
- What happens if the live service the drift monitor depends on is unreachable (deployment down, hosted resource cold-starting, etc.) rather than genuinely low-quality? The check reports "could not evaluate" distinctly from "evaluated and quality dropped" — an unreachable service is not the same finding as a quality regression, and must not be presented as one.
- What happens the first time this runs, before any agreed-good result has ever been recorded? There is nothing to compare against yet — see Assumptions (an existing agreed-good result is a precondition, not something this feature creates).
- What happens when a group's result set is small enough that even total failure in that group can't be distinguished from ordinary noise (see User Story 2, Scenario 5)? It is reported but excluded from blocking until its result set grows or its baseline result improves enough to make the distinction possible — this exclusion is automatic and re-evaluated every run, not a hardcoded one-time list.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST automatically run the existing automated test suite on every push and every pull request, with no manual trigger required.
- **FR-002**: The system MUST produce a pass/fail signal for every pull request that is capable of blocking a merge once branch protection is configured to require it. (Enabling that requirement in repository settings is a deliberate, manual, one-time step this feature enables but does not perform automatically — see Assumptions.)
- **FR-003**: The system MUST automatically run the retrieval-quality evaluation against a pull request's own code when that pull request touches retrieval-critical code, and MUST NOT run it for pull requests that don't.
- **FR-004**: The system MUST compare each pull request's evaluation results to the most recently agreed-good (promoted) result, per scenario group.
- **FR-005**: The system MUST produce a blocking-eligible failure signal when a gate-eligible group's quality drops by more than the tolerated noise band relative to the agreed-good result, on the same terms as FR-002 (a merge is actually blocked once branch protection requires this check).
- **FR-006**: The system MUST NOT block a pull request based on a group whose result set is too small or too low-scoring for the tolerated noise band to be able to distinguish "one scenario's ordinary variance" from "the group's signal is entirely gone" (see Assumptions for the precise rule).
- **FR-007**: The system MUST report evaluation results for every scenario group — including groups excluded from blocking per FR-006 — so nothing is hidden from the maintainer even when it isn't gating.
- **FR-008**: The system MUST run the retrieval-quality evaluation against the live, deployed service on a recurring weekly schedule, independent of any pull request.
- **FR-009**: The system MUST allow a maintainer to trigger the live-service evaluation on demand, without waiting for the schedule.
- **FR-010**: The system MUST NOT block or fail any pull request or merge as a result of the scheduled live-service evaluation — its findings are reported, not enforced as a merge gate.
- **FR-011**: The system MUST make a scheduled evaluation's findings visible enough that a maintainer will notice a reported quality drift without actively searching for it.
- **FR-012**: The system MUST distinguish "the live service could not be evaluated" (e.g. unreachable) from "the live service was evaluated and quality dropped" in what it reports.
- **FR-013**: The system MUST NOT change what counts as an agreed-good result automatically — promoting a new agreed-good result stays a deliberate, manual decision by a maintainer, not something any automated run does on its own.
- **FR-014**: The system MUST NOT change or enforce the existing documented long-term quality targets recorded elsewhere (`evaluations/HISTORY.md`) — this feature only prevents regressions relative to the last agreed-good result; it does not newly require any group to reach its long-term target.

### Key Entities

- **Scenario group**: A named category of evaluation stories (e.g. "positive", "negative", "edge", "adversarial") that already exists in the evaluation harness; each has its own result set size and its own agreed-good result per metric.
- **Agreed-good result (baseline)**: The most recently, deliberately promoted evaluation result that all future runs are compared against; already exists today, promoted manually.
- **Evaluation run**: One execution of the evaluation scenarios against a specific version of the system (a PR's code, or the live deployed service), producing a result per scenario group.
- **Regression finding**: The outcome of comparing an evaluation run's result to the agreed-good result for a group, including whether the drop exceeds that group's tolerated noise band and whether the group is currently eligible to block on that basis.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of commits and pull requests to the repository receive an automatic pass/fail test signal, with zero requiring a maintainer to manually trigger tests to find out if something broke.
- **SC-002**: A deliberately introduced retrieval-quality regression in a gate-eligible group is caught and blocks the pull request before merge, without a maintainer needing to manually run or interpret the evaluation.
- **SC-003**: A pull request with no retrieval-quality change is not blocked by the retrieval-quality check, and that check does not run at all for pull requests outside retrieval-critical code.
- **SC-004**: Production quality drift is surfaced within one week of occurring, without requiring a code change or a maintainer's manual check to discover it.
- **SC-005**: A maintainer can distinguish, from the reported output alone and without reading code, which scenario groups are currently blocking merges versus which are reported-only and why.

## Assumptions

- An agreed-good (promoted) evaluation result already exists for each scenario group before this feature's gates are enabled; this feature consumes and compares against that result, it does not create the first one.
- "Retrieval-critical code" is defined by file path today (query building, NLI, LLM selection/prompting, the evaluation scenario data itself) — this feature reuses that existing boundary rather than redefining it.
- The precise rule for FR-006 ("too small or too low-scoring to gate") is: a group's tolerated noise band, expressed as the fractional impact of a single scenario in that group's result set, must be smaller than the group's own agreed-good score for that metric — otherwise even a complete loss of signal in that group can't mathematically exceed the noise band, and gating on it would be meaningless. This automatically re-includes or excludes a group as its result set grows or its agreed-good score changes, rather than requiring a maintainer to hand-maintain an exclusion list.
- For most scenario groups, quality is measured by how many expected results were actually found (recall/precision-style). For the "negative" group specifically — stories where nothing should be found — quality is instead measured by how often the system correctly found nothing, since "how many expected results were found" is vacuous when nothing is expected.
- Live-service evaluation credentials/access already exist in principle (the live service already exposes a way to run this same evaluation) but are not yet configured for automated/scheduled use — configuring that access is a precondition for User Story 3, tracked as a dependency rather than solved by this spec.
- This feature does not change the underlying retrieval system's quality — it only adds visibility and a merge-time gate around quality that is already being measured today.
- "Blocks merging" (FR-002, FR-005) means the check produces a signal branch protection can require — actually requiring it is a manual, one-time repository-settings decision made once this feature's checks are proven reliable (see quickstart.md's final step), not something any automated part of this feature does on its own. Until that manual step happens, a failing check is visible but advisory, not enforced.
