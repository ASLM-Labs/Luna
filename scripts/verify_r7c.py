"""Deterministic verification for R7-C ResumeCompatibilityVector."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.continuity import (  # noqa: E402
    ContinuityService,
    ResumeCompatibilityDimension,
    ResumeCompatibilityVector,
    ResumePolicy,
    ResumeStatus,
    SQLiteContinuityStore,
)
from luna.contracts import RiskLevel, TaskContract, TaskScope, TaskState  # noqa: E402
from luna.contracts.base import SCHEMA_VERSION as CONTRACT_SCHEMA_VERSION  # noqa: E402
from luna.contracts.enums import PlanStepStatus, TaskPhase  # noqa: E402
from luna.contracts.plan import PlanStep  # noqa: E402
from luna.runtime import DeterministicFingerprintProvider, SQLiteRuntimeJournal  # noqa: E402

_REQUIRED_FILES = (
    ROOT / "src" / "luna" / "continuity" / "models.py",
    ROOT / "src" / "luna" / "continuity" / "service.py",
    ROOT / "src" / "luna" / "runtime" / "environment.py",
    ROOT / "src" / "luna" / "runtime" / "journal.py",
    ROOT / "src" / "luna" / "runtime" / "loop.py",
    ROOT / "tests" / "test_r7c_resume_compatibility.py",
)


def _state(root: Path) -> TaskState:
    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Verify R7-C compatibility gating.",
        required_conditions=("Resume requires compatible durable state.",),
        evidence_required=("compatibility decision",),
        scope=TaskScope(workspace_root=str(root)),
        risk_level=RiskLevel.LOW,
        owner="user",
    )
    return TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.PLANNED,
        plan=(
            PlanStep(
                sequence=1,
                description="Continue safely.",
                status=PlanStepStatus.PENDING,
            ),
        ),
        revision=3,
    )


def _vector(
    *,
    continuity: int = 1,
    journal: int = 2,
    contracts: str = CONTRACT_SCHEMA_VERSION,
) -> ResumeCompatibilityVector:
    return ResumeCompatibilityVector(
        runtime_revision="r7c-verifier",
        continuity_schema_version=continuity,
        runtime_journal_schema_version=journal,
        contract_schema_version=contracts,
        workspace_fingerprint="workspace-r7c",
        environment_fingerprint="environment-r7c",
    )


def _policy(vector: ResumeCompatibilityVector) -> ResumePolicy:
    return ResumePolicy(
        runtime_revision=vector.runtime_revision,
        workspace_fingerprint=vector.workspace_fingerprint,
        environment_fingerprint=vector.environment_fingerprint,
        compatibility_vector=vector,
    )


def main() -> int:
    missing = tuple(str(path.relative_to(ROOT)) for path in _REQUIRED_FILES if not path.is_file())

    with TemporaryDirectory(prefix="luna-r7c-verify-") as temp:
        root = Path(temp)
        state = _state(root)
        store = SQLiteContinuityStore(root / "continuity.sqlite3")
        service = ContinuityService(store)
        journal = SQLiteRuntimeJournal(root / "journal.sqlite3")
        persisted = _vector(
            continuity=store.schema_version(),
            journal=journal.schema_version(),
        )
        service.create_checkpoint(
            state=state,
            workspace_fingerprint=persisted.workspace_fingerprint,
            environment_fingerprint=persisted.environment_fingerprint,
            runtime_revision=persisted.runtime_revision,
            compatibility_vector=persisted,
            next_step="Continue safely.",
        )
        mismatch = service.resume_latest(
            task_id=state.task_id,
            policy=_policy(
                _vector(
                    continuity=2,
                    journal=3,
                    contracts="2.0",
                )
            ),
        )

        state2 = _state(root)
        service2 = ContinuityService(SQLiteContinuityStore(root / "legacy.sqlite3"))
        service2.create_checkpoint(
            state=state2,
            workspace_fingerprint="workspace-r7c",
            environment_fingerprint="environment-r7c",
            runtime_revision="r7c-verifier",
            next_step="Continue safely.",
        )
        missing_vector = service2.resume_latest(
            task_id=state2.task_id,
            policy=_policy(_vector()),
        )

        state3 = _state(root)
        service3 = ContinuityService(SQLiteContinuityStore(root / "matching.sqlite3"))
        matching = _vector()
        service3.create_checkpoint(
            state=state3,
            workspace_fingerprint=matching.workspace_fingerprint,
            environment_fingerprint=matching.environment_fingerprint,
            runtime_revision=matching.runtime_revision,
            compatibility_vector=matching,
            next_step="Continue safely.",
        )
        ready = service3.resume_latest(
            task_id=state3.task_id,
            policy=_policy(matching),
        )

        provider_policy = DeterministicFingerprintProvider(
            runtime_revision="r7c-provider"
        ).resume_policy(
            task_contract=state.contract,
            continuity_schema_version=store.schema_version(),
            runtime_journal_schema_version=journal.schema_version(),
            contract_schema_version=CONTRACT_SCHEMA_VERSION,
        )
        observed_continuity_schema = store.schema_version()
        observed_journal_schema = journal.schema_version()

    runtime_source = (ROOT / "src" / "luna" / "runtime" / "loop.py").read_text(
        encoding="utf-8"
    )
    model_source = (ROOT / "src" / "luna" / "continuity" / "models.py").read_text(
        encoding="utf-8"
    )

    mismatch_dimensions = set(mismatch.compatibility_mismatches)
    checks = {
        "required_files_present": not missing,
        "vector_fields_exact": set(ResumeCompatibilityVector.model_fields)
        == {
            "schema_version",
            "runtime_revision",
            "continuity_schema_version",
            "runtime_journal_schema_version",
            "contract_schema_version",
            "workspace_fingerprint",
            "environment_fingerprint",
        },
        "component_owned_versions_bound": (
            provider_policy.compatibility_vector is not None
            and provider_policy.compatibility_vector.continuity_schema_version == 1
            and provider_policy.compatibility_vector.runtime_journal_schema_version == 2
            and provider_policy.compatibility_vector.contract_schema_version
            == CONTRACT_SCHEMA_VERSION
        ),
        "schema_mismatch_blocks_resume": mismatch.status is ResumeStatus.BLOCKED,
        "schema_mismatch_dimensions_explicit": mismatch_dimensions
        == {
            ResumeCompatibilityDimension.CONTINUITY_SCHEMA_VERSION,
            ResumeCompatibilityDimension.RUNTIME_JOURNAL_SCHEMA_VERSION,
            ResumeCompatibilityDimension.CONTRACT_SCHEMA_VERSION,
        },
        "legacy_checkpoint_blocked_by_extended_policy": (
            missing_vector.status is ResumeStatus.BLOCKED
            and missing_vector.compatibility_mismatches
            == (ResumeCompatibilityDimension.VECTOR,)
        ),
        "matching_vector_resumes": (
            ready.status is ResumeStatus.READY
            and ready.compatibility_mismatches == ()
        ),
        "runtime_loop_binds_continuity_schema": "continuity_schema_version=("
        in runtime_source,
        "runtime_loop_binds_journal_schema": "runtime_journal_schema_version="
        in runtime_source,
        "runtime_loop_binds_contract_schema": "contract_schema_version=CONTRACT_SCHEMA_VERSION"
        in runtime_source,
        "runtime_checkpoint_persists_vector": (
            "compatibility_vector=resume_policy.compatibility_vector" in runtime_source
        ),
        "budget_semantics_not_in_vector": "runtime_budget" not in model_source,
        "session_not_in_vector": "session_id" not in model_source,
        "provider_continuation_not_in_vector": "provider" not in model_source.casefold(),
        "journal_schema_version_observable": observed_journal_schema == 2,
        "continuity_schema_version_observable": observed_continuity_schema == 1,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": "R7-C",
                "scope": "RESUME_COMPATIBILITY_VECTOR",
                "checks": checks,
                "missing_files": missing,
                "status": status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
