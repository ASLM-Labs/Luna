# Phase 12F — Verification, Evidence and Review-Gated Learning

**Package status:** `IMPLEMENTED_UNVERIFIED`

## Added

- runtime-owned evidence-strength classes `WEAK`, `MODERATE`, `STRONG`, and
  `DETERMINISTIC`;
- conservative source/reproducibility/confidence qualification rules;
- explicit unresolved `EvidenceDisagreement` records that block false success;
- current task/revision/environment/freshness evidence rejection rules;
- durable SQLite WAL `SQLiteEvidenceStore` with canonical-payload SHA-256 integrity
  and immutable evidence IDs;
- `VerifiedEvidenceRegistry` for durable evidence plus optional append-only audit;
- `VerificationCoordinator` that binds `CompletionGate`, `FinalReportComposer`,
  authoritative `TaskState`, and review-only learning output;
- evidence strength in final-report evidence references and disagreement visibility
  in unverified report content;
- `LearningCandidate` / `LearningCandidateBatch` and deterministic candidate
  extraction from failed assumptions, evidence conflicts, rejected evidence, and
  verification gaps;
- contract-level `review_required=true` and `automatic_commit_allowed=false`;
- LunaRuntime `record_evidence()` and optional Phase 12F finalization services;
- no-evidence `VERIFICATION_PENDING` behavior preserved for safe resume;
- non-terminal evidence-gap/conflict finalization with a resumable `VERIFYING` checkpoint;
- verified/final-failure finalization to `CLOSED` plus a terminal continuity checkpoint;
- runtime stop reasons for `UNVERIFIED` and `INCONCLUSIVE` outcomes;
- Phase 12F verifier, tests, CLI smoke, RFC, metadata, and quality-gate wiring.

## Security and integrity properties

- model inference cannot be PASS evidence and cannot grant evidence strength;
- generic successful tool output remains below the default completion threshold;
- stale revision/environment/freshness evidence cannot verify current state;
- unresolved qualifying PASS/FAIL disagreement cannot produce
  `VERIFIED_COMPLETE`;
- duplicate evidence IDs cannot be silently overwritten with a different payload;
- evidence-registry integrity is checked before runtime finalization;
- completion status remains owned by the deterministic `CompletionGate`;
- final report cannot claim a status different from the gate result;
- learning candidates cannot automatically commit themselves;
- learning-candidate construction has no memory, process, network, or source-code
  mutation authority;
- terminal finalization is persisted in the existing continuity layer;
- Phase 12E remains compatible when Phase 12F services are not configured.

## Deliberate boundary

Phase 12F creates learning **candidates**, not self-modification. Candidate review,
promotion, retention, and any later dataset/governance policy remain explicit later
work. Real model compatibility and controlled rollout begin in Phase 13 after Phase
12G end-to-end behavior conformance.

## Package-environment verification

The assistant-side package environment validates Python syntax, `285 passed` in the
full pytest suite, Phase 1–12F deterministic verifiers, and CLI smokes. The target Windows
`.venv` remains authoritative for Ruff and mypy strict before commit or push.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 12F verification, evidence and learning gate passed.
```
