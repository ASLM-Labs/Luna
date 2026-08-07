# Phase 11 Source Baseline for Phase 12A

**Observed package:** `Luna_Phase12_Source.zip`
**Package SHA-256:** `a9250e2366e7583bb0effccf34d05095a5fd3e2639bcbdb84ee91910bb703ab3`
**Observed date:** 2026-08-06
**Git metadata:** Not present in the supplied source package.

## Verified in the isolated package

```text
Python                     3.13.5
Pytest                     193 passed
Phase 11 verifier          PASS (with PYTHONPATH=src in the isolated package)
Locked suite revision      1.0.0
Locked suite SHA-256       3121e570d188a7c372d0a2436c56bd9f6377fa1dadf1c41d1f5f8fcd94d02827
Acceptance cases           11/11 PASS
Release gate               PASS
```

## Not verifiable from this ZIP

- repository branch and HEAD commit;
- pull-request merge state;
- GitHub Actions status;
- Windows `.venv` Ruff and mypy strict results after Phase 12A is applied.

Those items remain target-machine closure checks and must not be inferred from this
source archive.

## Phase 12A baseline rule

The Phase 11 locked eval suite, fixture/oracle hash, and release thresholds are not
changed by Phase 12A. Any regression in the 193-test baseline or Phase 11 verifier
blocks the Phase 12A patch.
