"""Phase 12F evidence strength and learning-boundary diagnostic."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from luna.contracts.enums import (
    EvidenceResult,
    EvidenceSourceKind,
    RiskLevel,
    TaskPhase,
)
from luna.contracts.evidence import Evidence
from luna.contracts.state import TaskState
from luna.contracts.task import TaskContract, TaskScope
from luna.diagnostics.models import SmokeReport, equals
from luna.learning import LearningCandidateBuilder
from luna.verification import (
    DeterministicVerifier,
    EvidenceStrength,
    SQLiteEvidenceStore,
    VerificationPolicy,
    required_condition_claim_id,
)


def run(root: Path | None = None) -> SmokeReport:
    """Run against an injected test root or a scenario-owned temporary root."""

    if root is not None:
        return _run_at(root)
    with TemporaryDirectory(prefix="luna-phase12f-smoke-") as temp:
        return _run_at(Path(temp))


def _run_at(root: Path) -> SmokeReport:
    task_id = uuid4()
    contract = TaskContract(
        task_id=task_id,
        objective="Verify evidence-aware finalization boundaries.",
        required_conditions=("Tests pass.",),
        evidence_required=("test result",),
        scope=TaskScope(workspace_root=str(root)),
        risk_level=RiskLevel.LOW,
        owner="user",
    )
    strong = Evidence(
        task_id=task_id,
        requirement_id=required_condition_claim_id("Tests pass."),
        source_kind=EvidenceSourceKind.TEST_RESULT,
        source_ref="verification:phase12f-smoke",
        result=EvidenceResult.PASS,
        environment_fingerprint="phase12f-smoke",
        revision="phase12f",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )
    weak = strong.model_copy(
        update={
            "evidence_id": uuid4(),
            "source_kind": EvidenceSourceKind.TOOL_OUTPUT,
        }
    )
    policy = VerificationPolicy(
        current_revision="phase12f",
        expected_environment_fingerprint="phase12f-smoke",
    )
    verifier = DeterministicVerifier()
    strong_report = verifier.verify(contract=contract, evidence=(strong,), policy=policy)
    weak_report = verifier.verify(contract=contract, evidence=(weak,), policy=policy)
    conflict_report = verifier.verify(
        contract=contract,
        evidence=(
            strong,
            strong.model_copy(
                update={
                    "evidence_id": uuid4(),
                    "result": EvidenceResult.FAIL,
                }
            ),
        ),
        policy=policy,
    )
    store = SQLiteEvidenceStore(root / "evidence.sqlite3")
    store.save(strong)
    state = TaskState(
        task_id=task_id,
        contract=contract,
        phase=TaskPhase.VERIFYING,
        failed_assumptions=("A stale verifier result could prove completion.",),
    )
    learning = LearningCandidateBuilder().build(state=state, report=strong_report)
    payload = {
        "strong_status": strong_report.completion_status.value,
        "strong_strength": strong_report.evidence_strength_assessments[0].strength.value,
        "weak_status": weak_report.completion_status.value,
        "weak_qualifying": weak_report.evidence_strength_assessments[0].qualifying,
        "conflict_status": conflict_report.completion_status.value,
        "disagreement_count": len(conflict_report.disagreements),
        "evidence_store_integrity": store.verify_integrity(),
        "learning_review_required": bool(learning.candidates)
        and all(item.review_required for item in learning.candidates),
        "learning_auto_commit": any(
            item.automatic_commit_allowed for item in learning.candidates
        ),
    }
    return SmokeReport(
        scenario_id="phase12f",
        payload=payload,
        checks=(
            equals("strong_status", payload["strong_status"], "VERIFIED_COMPLETE"),
            equals(
                "strong_strength",
                payload["strong_strength"],
                EvidenceStrength.DETERMINISTIC.value,
            ),
            equals("weak_status", payload["weak_status"], "INCONCLUSIVE"),
            equals("weak_qualifying", payload["weak_qualifying"], False),
            equals(
                "conflict_status",
                payload["conflict_status"],
                "CONFLICTING_EVIDENCE",
            ),
            equals("disagreement_count", payload["disagreement_count"], 1),
            equals(
                "evidence_store_integrity",
                payload["evidence_store_integrity"],
                True,
            ),
            equals(
                "learning_review_required",
                payload["learning_review_required"],
                True,
            ),
            equals("learning_auto_commit", payload["learning_auto_commit"], False),
        ),
    )
