# Phase 12B — Layered Context Composer

**Package status:** `IMPLEMENTED_UNVERIFIED`

## Added

- canonical `ACTIVE`, `TASK`, `RUNTIME_CONTINUITY`, `WORKSPACE`, and
  `VERIFIED_MEMORY` context layers;
- `CONTROL` versus `DATA_ONLY` interpretation boundary;
- explicit model-visibility sensitivity and secret exclusion;
- per-source freshness windows and future/stale source rejection;
- explicit memory relevance basis requirement;
- runtime-locked unverified-memory and secret-redaction guards;
- hard per-layer and overall context budgets;
- deterministic layered selection, exclusions, missing-source tracking, and bundle
  fingerprinting;
- sanitized model rendering that preserves provenance without hidden content;
- compatibility bridge from existing Phase 2 `ContextCandidate`;
- Phase 12B unit tests, verifier, RFC, CLI smoke, and quality-gate integration.

## Security properties

- unseen sources cannot masquerade as observed context;
- observed metadata without actual model-visible content is not admitted;
- workspace and memory content cannot become `CONTROL` instructions;
- verified-memory candidates require an explicit task relevance basis;
- unverified memory blocking cannot be disabled by policy;
- secret candidate exclusion and deterministic secret redaction cannot be disabled;
- future and stale sources can be rejected before model context is built;
- bulk workspace/memory context cannot evict higher-priority active/task/runtime
  control context under a shared budget;
- the composer performs no hidden file, process, database, or network I/O.

## Deliberate boundary

Phase 12B composes only already-observed inputs. It does not decide which tool to call,
read files, query memory, run commands, access the network, or execute a policy-agent
loop. Those responsibilities remain explicit future runtime steps.

## Package-environment verification

The supplied Phase 12A merged source baseline initially produced:

```text
Pytest baseline       205 passed
```

After Phase 12B implementation the isolated package environment produced:

```text
Python syntax         PASS
Pytest                224 passed
Phase 1-12A verifier  PASS
Phase 12B verifier    PASS
phase12b-smoke        PASS
```

Ruff and mypy strict are unavailable in the isolated package environment and must run
in the target Windows `.venv`. Final target status therefore remains
`IMPLEMENTED_UNVERIFIED` until `scripts\check_hold.bat` passes.

## Target-machine closure

```bat
scripts\check_hold.bat
```

Expected final line:

```text
[PASS] Luna 0.1 Phase 12B layered context composer gate passed.
```
