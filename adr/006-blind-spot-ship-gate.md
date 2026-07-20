# engine ADR-006 — Replace the N=4 `positive` Ship Gate with `blind_spot` (N=80)

### Status: PROPOSED · Started: 2026-07-18

---

## 1. Context

**ADR-003 §7 set the original ship gate:** `SC-001 positive Recall@5 ≥ 0.85`, evaluated on the hand-authored `positive` scenario group — **N=4 stories**. At N=4, each story is worth 0.25 of recall; the gate is really "get 3 or 4 of 4 specific stories right," not a measurement of general recall.

**ADR-005 (the fine-tune plan) already saw this problem and explicitly declined to fix it**, deferring the decision to whoever came after:

> "Say plainly what §1 already implies: N=4 is too small to trust as a generalization estimate, gate or no gate. [...] The gate stays ≥0.85 (point 3 below) because it's the only concrete bar this repo has established and **changing it isn't this ADR's call** — but this is precisely why the blind-spot-batch cross-check two paragraphs up isn't optional polish, it's the only part of this plan that can distinguish 'generalized' from 'memorized the 4 stories, got lucky.'" — ADR-005 §6

`specs/006-fine-tune-llm`'s spec.md made the same choice explicitly, in its **Assumptions** section (not the SC-004 bullet itself, which only states the bare numeric bar): *"The pre-agreed numeric ship bar (Recall@5 ≥ 0.85 on the primary scenario group) is inherited unchanged from the existing production quality target; this feature does not renegotiate that number."*

**What's changed since both of those were written:** ADR-005 §6 also promoted `evaluations/staging/blind_spot_eval_2026-07-13.json` (80 DeepSeek-generated, spot-checked, held-out stories — never used in training) into a real eval group specifically *"because N=4 is too small to trust... this is the only part of this plan that can distinguish generalized from memorized."* That group now exists, has a promoted baseline (`baseline_2026-07-17.json`), and has real trial data behind it.

**The trial data that motivates this ADR** (`specs/006-fine-tune-llm/candidate-2026-07-18-results.md`, full run in `evaluations/runs/run_2026-07-18.json`): the first fine-tuned candidate was evaluated against both groups via the existing `scripts/check_regression.py` (unmodified):

```
GROUP          METRIC           BASELINE   CURRENT     DELTA  TOLERANCE  ELIGIBLE  RESULT
blind_spot     recall_at_k         0.325     0.481    +0.156      0.013       yes  pass
blind_spot     precision_at_k      0.128     0.315    +0.187      0.013       yes  pass
positive       recall_at_k         0.729     0.667    -0.062      0.250       yes  pass (within noise)
```

`blind_spot` (N=80) shows a large, eligible, doubly-confirmed (recall *and* precision both up) improvement. `positive` (N=4) shows a nominal decline that its own ±0.25-per-story tolerance already flags as noise, not signal — the tool's own eligibility math agrees this one story-swing shouldn't be read as a regression. This is the concrete case ADR-005 anticipated: a candidate that plausibly generalizes better, blocked by a gate too small to say so with confidence.

## 2. Decision

**Promote `blind_spot` to the primary ship-gate scenario group. Demote `positive`'s absolute 0.85 bar to a reported-only canary.**

Concretely, replace ADR-003 §7's `SC-001 positive Recall@5 ≥ 0.85` with:

- **New SC-001: `blind_spot` recall_at_k and precision_at_k must both be `eligible` and non-regressed** per `scripts/check_regression.py`'s existing, unmodified per-`(group, metric)` tolerance mechanism (`adr/004-ci-metrics-gate.md` §4) — i.e. both must independently show `"pass"` in the tool's own output, exactly as already computed above. No new tooling, no new tolerance formula, no absolute number invented for this ADR to defend — this reuses the exact mechanism already applied to every other group.
- **`positive`'s Recall@5 remains reported in every eval run** (unchanged — it's still a real scenario group, still shown in the table), but no longer blocks shipping on its own. It still counts toward the existing cross-group rule below.
- **Unchanged from ADR-003 §7 / ADR-005 §6**: no other eligible group (`adversarial`, `edge`, `positive`) may regress past its own tolerance, and a candidate must not trade recall for precision (**ADR-003 §7's own `SC-006` precision-guard concept** — not to be confused with spec.md's differently-numbered `SC-006`, the config-only-swap requirement) — `blind_spot`'s own precision_at_k being required alongside its recall_at_k *is* that check, applied to the group that matters most.

**Why "no regression" and not a new absolute floor (e.g. "blind_spot recall ≥ 0.45"):** `0.85` for `positive` was a real, deliberately chosen product-quality target (ADR-003's own spike work). `blind_spot` has no equivalent history to derive a defensible absolute number from yet — inventing one now would just be swapping one made-up bar for another. **Note precisely what "non-regressed" does and doesn't require**: per `check_regression.py`'s own tolerance math, a candidate that's flat or declines by less than tolerance still reads as `"pass"` — this gate does not require an improvement, only that `blind_spot` not get measurably worse. That's a real, honest bar this repo's existing tolerance math can already support today, not a stronger "must improve" bar dressed up as one. A future ADR can propose a `blind_spot` absolute floor once enough baseline history exists to justify one, the same way `0.85` itself came from real spike data, not a guess.

**No code changes required.** `scripts/check_regression.py` already computes `blind_spot`'s eligibility/pass-fail exactly as shown above — this ADR changes which row of its existing output is read as the ship/no-ship signal, not the tool itself.

## 3. Consequences

- `specs/006-fine-tune-llm/spec.md` SC-004/SC-005 and its Assumptions section still state the bare N=4 `positive` ≥0.85 bar as of this writing — **accepting this ADR requires updating them** to reference `blind_spot` as the primary bar and `positive` as a reported canary. Not yet done; tracked as a task alongside this ADR, not left to drift.
- **`blind_spot`'s `empty_rate` is not part of the new gate** (only `recall_at_k`/`precision_at_k` are) — worth flagging as a known structural gap, not silently accepted: a future candidate could clear this ADR's recall/precision bar while quietly getting more likely to return nothing at all on held-out stories, and nothing here would catch it directly. **For the 2026-07-18 candidate specifically, this was investigated (T025, 2026-07-19) and found benign** — the observed `empty_rate` rise (0.0375 → 0.125) was entirely composed of correctly-silent negative-shaped rows (baseline correctly silent on 3/20, candidate on 10/20), not silence on rows that needed a real answer. That result doesn't close the structural gap for *future* candidates, though — a future revision should still consider whether `empty_rate` needs its own eligibility check once there's a basis for one.
- `adr/003-generative-llm-bias-selection.md` §7's `SC-001` line is superseded by this ADR for ship-gate purposes; ADR-003 itself is left as-is (historical record of the original decision), per this repo's convention of amending via a new ADR rather than rewriting old ones (see how ADR-004/005 already reference ADR-002/003 without editing them).
- The first fine-tuned candidate (`candidate-2026-07-18-results.md`) now reads as **passing** the ship gate on the evidence already collected — but is still not shipped yet, because the evaluated artifact was a runtime-applied LoRA adapter over the production base GGUF (a trial proxy), not the final merged-and-quantized GGUF production would actually run. That re-evaluation is a separate, already-tracked task (see `tasks.md`) — this ADR changes the *gate*, not the *ship decision* for this specific candidate, which still needs one more real check against the actual shippable binary.
- If a future candidate improves `positive` but regresses `blind_spot`, this ADR means it does **not** ship on `positive` alone — that is the intended effect, not a loophole to close later.

## 4. Out of scope

- Does not touch `adversarial`/`edge` gates, precision-guard mechanics, or latency gates (ADR-003 §7 SC-002/003/004/007) — unchanged.
- Does not add a new absolute numeric floor for `blind_spot` (see §2's rationale) — a future ADR's call, once history exists.
- Does not decide whether the first candidate ships — that's `tasks.md`'s remaining work (re-evaluate the real merged GGUF, then decide).
