# Phase 12C — Action Proposal + Two-Stage Tool Selection + Structured Denial

**Package status:** `IMPLEMENTED_UNVERIFIED`

## Added

- untrusted `ActionProposal` contract;
- action kind / target kind / required capability boundary;
- one-side-effect-per-iteration `ActionProposalBatch` guard;
- runtime-owned `ToolFamily` and `ToolRoute` metadata;
- Stage 1 deterministic family selection;
- Stage 2 registered concrete ToolSpec selection;
- ambiguous tool selection denial instead of guessing;
- strict argument validation before request preparation;
- existing dispatcher policy reused as deterministic preflight;
- no-fallback behavior after preferred-tool or permission denial;
- machine-readable `ActionDenial` stage/code/checks;
- denial → `BLOCKED` Observation normalization;
- `ActionResolution` with `PREPARED` / `DENIED` states;
- explicit `ActionResolver.to_tool_request()` handoff to future dispatcher execution;
- Phase 12C tests, verifier, RFC, CLI smoke, and quality-gate integration.

## Security properties

- action proposal grants no permission;
- proposal cannot set or lower runtime-owned risk;
- invented tool names never become executable requests;
- tool routes must reference registered tools;
- ambiguous compatible tools are denied rather than guessed;
- denied preferred tools are not silently replaced with another tool;
- high-impact expectation and existing scope/autonomy/risk checks run before preparation;
- denied actions become explicit blocked observations;
- one iteration cannot contain multiple side-effect proposals;
- selector/resolver do not execute handlers or call the dispatcher.

## Deliberate boundary

Phase 12C prepares or denies exactly one action. It does not perform the real agent loop,
retry/replan policy, failure taxonomy, minimal-change enforcement, checkpoint orchestration,
or completion verification. `ToolDispatcher` remains the real execution authority.

## Package-environment verification

Baseline Phase 12B source produced:

```text
Pytest baseline       224 passed
```

After Phase 12C implementation the isolated package environment is expected to produce:

```text
Python syntax         PASS
Pytest                242 passed
Phase 1-12B verifier  PASS
Phase 12C verifier    PASS
phase12c-smoke        PASS
```

Ruff and mypy strict must also pass in the target Windows `.venv` before merge.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 12C action selection gate passed.
```
