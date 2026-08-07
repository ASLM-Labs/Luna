# Luna 0.1 — Phase 12G Report

## Status

`IMPLEMENTED_UNVERIFIED`

Phase 12G adds the final Phase 12 runtime end-to-end and behavior-conformance gate.
It tests the integrated runtime against a hash-locked set of critical observable
behaviors rather than relying only on component tests.

## Delivered

- `luna.conformance` contracts, locked suite, runner, and real-runtime executor;
- suite revision `1.0.0` with 11 critical scenarios;
- canonical suite SHA-256 fixture/oracle lock;
- exact fail-closed oracle comparison and repeatability check;
- completion-truth, evidence, policy, control, replay, scope, isolation, and budget domains;
- legacy Phase 11 acceptance compatibility check;
- Phase 12G deterministic verifier, CLI smoke, RFC, metadata, and quality-gate wiring;
- dispatcher preflight path-scope enforcement discovered through cross-layer testing.

## Important defect closed

Phase 12G exposed a cross-layer gap: an out-of-scope write could reach the later
minimal-change layer before being rejected because dispatcher preflight did not yet
validate the request `path` against `TaskScope.allowed_paths`.

`evaluate_tool_policy()` now canonicalizes schema-backed file paths and denies an
out-of-scope target before dispatch. The integrated regression requires zero tool
calls and an explicit permission denial observation.

## Locked runtime scenarios

```text
L12G-01 verified completion
L12G-02 no false complete
L12G-03 weak evidence resumable
L12G-04 conflicting evidence
L12G-05 multiple actions blocked
L12G-06 cancel at safe boundary
L12G-07 STARTED side effect no replay
L12G-08 scope denial before dispatch
L12G-09 high-risk worktree isolation
L12G-10 tool budget before dispatch
L12G-11 stale evidence rejected
```

## Package-environment verification

The assistant-side environment validates Python syntax, `291 passed` in the full
pytest suite, the 11/11 locked Phase 12G runtime conformance suite, and the legacy
11/11 Phase 11 acceptance suite. Ruff and mypy strict are not available in the
package environment; the target Windows `.venv` remains authoritative for those
checks before commit or push.

## Deliberate boundary

Phase 12G completes the Phase 12 runtime foundation. It does not connect a real
external model or broaden network authority. Phase 13 is responsible for real-model
compatibility, adapter behavior, controlled rollout, shadow/canary evaluation, and
explicit rollback criteria.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 12G runtime E2E and behavior conformance gate passed.
```
