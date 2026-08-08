# RFC-019 — Trace/Dataset Governance and Cognitive Quality Foundation

Status: FOUNDATION_IMPLEMENTED_UNVERIFIED
Phase: 19
Target branch: `phase-19-trace-dataset-governance`

## 1. Purpose

Phase 19 establishes the governance and evaluation foundation required before Luna can claim
model improvement. The phase has two parallel tracks:

- **A. Dataset Governance** — reconstruct, classify, normalize, split, and transform trajectory
  data without contaminating evaluation or importing wrapper-specific control semantics.
- **B. Cognitive Quality** — freeze a pre-training baseline and measure planning, tool selection,
  failure recovery, evidence use, uncertainty calibration, and self-correction as separate
  dimensions.

This foundation does **not** claim that a real training run has happened. Real source traces,
model weights, hardware-specific training, and post-training held-out evaluation remain separate
execution steps after the governance boundary is verified.

## 2. No raw hidden chain-of-thought

Phase 19 does not collect, require, expose, or train on raw hidden chain-of-thought. A canonical
trajectory is an **observable structured decision trace** composed of explicit runtime-visible
stages such as:

`TASK → INTENT/CONTEXT → PLAN → ACTION → OBSERVATION → INTERPRETATION/REPLAN → EVIDENCE → VERIFICATION → FINAL`

Each event may carry a concise decision basis and evidence references. Those fields describe the
observable basis for a decision; they are not a hidden token-by-token reasoning transcript.

The contract contains an explicit invariant that raw hidden chain-of-thought is forbidden.

## 3. Trajectory reconstruction

Reconstruction groups already-observable source rows by source trajectory identity and requires a
contiguous sequence. Missing or duplicate source rows are **not invented**. They must be repaired
from evidence or the trajectory must be dropped/quarantined before transformation.

Canonical trajectory metadata includes:

- source trajectory identity;
- task, repository, and trajectory family;
- dataset taxonomy;
- observable decision events;
- outcome and failure labels;
- provenance references;
- license review state;
- PII review state.

## 4. Dataset taxonomy

The first deterministic taxonomy vocabulary is:

- `IMPLEMENTATION_CODING`
- `SECURITY_HARNESS`
- `MODEL_JUDGE_REVIEW`
- `SEED_AUTHORING`
- `FAILED_RISKY_ACTION`
- `OTHER`

Taxonomy is explicit metadata. Phase 19 does not silently infer sensitive provenance or trust from
model prose.

## 5. Failure taxonomy

Binary pass/fail is insufficient for learning analysis. Phase 19 adds:

- `INTENT_ERROR`
- `CONTEXT_ERROR`
- `PLANNING_ERROR`
- `TOOL_SELECTION_ERROR`
- `TOOL_ARGUMENT_ERROR`
- `EXECUTION_ERROR`
- `OBSERVATION_INTERPRETATION_ERROR`
- `EVIDENCE_ERROR`
- `VERIFICATION_ERROR`
- `UNCERTAINTY_ERROR`
- `SELF_CORRECTION_ERROR`

Failed or partial canonical trajectories require one or more explicit failure labels.

## 6. Tool normalization

Wrapper-specific names are normalized into semantic actions such as read, search, write, process,
test, verify, and network research. A mapping may record the nearest Luna-native tool name for
dataset interpretation, but normalization **never creates an executable `ToolRequest`** and grants
no runtime authority.

Therefore a historical Codex/CLI wrapper is not copied into Luna's policy boundary.

## 7. Leak-free split

Splitting occurs **before** training transformation. The primary group key binds repository family,
task family, and trajectory family so related trajectories cannot be distributed across train and
validation by individual row.

Held-out task families are declared explicitly and must appear only in `HELD_OUT`. They cannot
enter train or validation. The splitter is deterministic and hash-stable for non-held-out groups.

The held-out set is intended for task/behavior families not seen during training, so post-training
claims measure generalization rather than memorization.

## 8. Training transformation boundary

Only reviewed trajectories can be transformed:

- license review must be complete;
- PII review must be complete;
- held-out data is rejected;
- targets are observable action/replan/verification/final events;
- `target_only_loss=true` is mandatory;
- raw hidden chain-of-thought is forbidden;
- failure and provenance labels remain attached.

Phase 19 foundation transforms data **for** controlled training; it does not execute SFT itself.

## 9. Cognitive quality baseline

Before training, Luna freezes evidence-backed scorecards across these dimensions:

- reasoning;
- planning;
- tool selection;
- failure recovery;
- evidence usage;
- uncertainty calibration;
- self-correction.

The baseline is content-hash locked. Candidate results must use the same case IDs and are compared
per dimension. Generic statements such as "Luna is better" are not an accepted output.

## 10. Uncertainty handling

Confidence is evidence-bound:

- insufficient evidence cannot proceed;
- contradictory evidence always requires `STOP` and reinspection;
- high confidence with sufficient/strong evidence may proceed;
- confidence by itself never overrides contradictory evidence.

A high-confidence decision contradicted by evidence is treated as a calibration failure rather
than a reason to continue.

## 11. Self-correction quality

Self-correction is defined as **changed-basis replanning**, not repeated attempts with cosmetic
changes. A genuine correction requires:

- identification of the failed assumption;
- new observed evidence;
- a strategy change;
- explicit changed dimensions;
- no blind retry.

Repeated Plan A → Plan A.1 → Plan A.2 without new evidence is pseudo-learning and scores as a
self-correction failure.

## 12. Candidate acceptance

Post-training comparisons are rejected when any of the following is present:

- any measured cognitive dimension regresses;
- a critical regression is present; or
- held-out contamination is detected.

Otherwise the report exposes dimension-specific deltas. Acceptance of a future trained model still
requires the real fixed/held-out evaluation run; this RFC does not auto-accept model weights.

## 13. Explicit non-goals of this foundation

This foundation does not:

- execute a GPU training job;
- fine-tune or publish model weights;
- ingest the user's large trace archive automatically;
- invent missing tool outputs;
- use held-out data for training transformation;
- train on raw hidden chain-of-thought;
- use model confidence as proof;
- let normalized historical tool calls bypass Luna runtime policy.

## 14. Acceptance

The foundation is acceptable only when deterministic tests/verifier prove:

1. observable structured traces forbid raw hidden chain-of-thought;
2. reconstruction refuses missing/duplicate source sequences;
3. failure taxonomy is multi-axis;
4. tool normalization grants no executable authority;
5. task/repository/trajectory families remain leak-free;
6. explicit held-out families cannot enter training;
7. training transform is target-only and review-gated;
8. contradictory evidence stops even under high confidence;
9. self-correction requires changed basis;
10. baseline is hash-locked and dimension-specific;
11. contamination/critical regressions reject a candidate;
12. Phase 18 remains green;
13. release metadata is current.
