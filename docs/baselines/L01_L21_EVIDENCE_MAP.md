# Luna L01–L21 Evidence Map — Phase 12A Baseline

This map links the existing Phase 1–11 implementation to its primary code and
verification evidence. It does not replace the locked acceptance suite.

| ID | Capability | Primary implementation | Verification evidence | Status |
|---|---|---|---|---|
| L01 | Versioned contracts | `src/luna/contracts/*` | `tests/test_contract_*.py`, `verify_phase1.py` | PASS |
| L02 | Authoritative task state | `contracts/state.py` | `test_contract_state.py` | PASS |
| L03 | Intent resolution | `intent/*` | `test_intent_resolution.py`, `verify_phase2.py` | PASS |
| L04 | Context collection/budget | `context/*` | `test_context_collection.py` | PASS |
| L05 | Task contract preparation | `preparation.py`, `tasking/*` | `test_task_preparation.py` | PASS |
| L06 | Adaptive planning | `planning/planner.py` | `test_adaptive_planner.py` | PASS |
| L07 | Plan lifecycle/replan | `planning/lifecycle.py`, `replanner.py` | planning tests | PASS |
| L08 | Expected observation/retry guard | `planning/expectation.py`, `retry.py` | retry/replan tests | PASS |
| L09 | Model backend boundary | `modeling/*` | model boundary tests | PASS |
| L10 | Tool registry/dispatcher | `tools/*` | dispatcher/registry tests | PASS |
| L11 | Safe shell/process | `shell/*` | safe process tests | PASS |
| L12 | Workspace scope/snapshot/rollback | `workspace/*` | workspace tests, `verify_phase5.py` | PASS |
| L13 | Observation/audit/evidence | `audit/*`, contracts observation/evidence | Phase 6 tests/verifier | PASS |
| L14 | Deterministic verification | `verification/*` | Phase 7 tests/verifier | PASS |
| L15 | Checkpoint/restart/resume | `continuity/*` | Phase 8 tests/verifier | PASS |
| L16 | Identity/communication | `identity/*` | Phase 10 identity tests | PASS |
| L17 | Permissions/autonomy | `autonomy/*`, `tools/policy.py` | Phase 10 autonomy tests | PASS |
| L18 | Model/runtime separation | `modeling/tool_bridge.py`, dispatcher/gates | model tool boundary tests | PASS |
| L19 | Controlled tool execution | `tools/dispatcher.py`, `audit/dispatcher.py` | Phase 5/6 tests | PASS |
| L20 | Fixed eval/regression | `evals/*` | Phase 11 eval tests/verifier | PASS |
| L21 | Measurable release gate | `acceptance/*` | Phase 11 acceptance tests/verifier | PASS |

## Phase 12A addition

Phase 12A adds the request/outcome and dependency boundary above L01–L21. It does not
claim that the end-to-end policy-agent loop exists yet. That claim belongs to Phase
12E/12G and remains pending.
