"""Deterministic repository gate for the C-011 S5C shadow-evaluation ledger."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import (  # noqa: E402
    CapabilityStatus,
    build_canonical_capability_registry,
)
from luna.evaluation_governance import (  # noqa: E402
    BenchmarkContaminationReport,
    EvaluationCase,
    EvaluationPartition,
    EvaluatorKind,
    EvaluatorSpec,
    FrozenEvaluationSuite,
)
from luna.parallel_cognition import (  # noqa: E402
    EqualComputeBudget,
    ShadowArmSpec,
    ShadowComparisonStatus,
    ShadowConfiguration,
    ShadowEvaluationPlan,
    ShadowEvidenceKind,
    ShadowEvidenceReference,
    ShadowLedgerIntegrityError,
    ShadowMetricObservation,
    ShadowRunObservation,
    ShadowRunSlot,
    SQLiteShadowEvaluationLedger,
    compare_shadow_observations,
)

READY = "C011_S5C_SHADOW_EVALUATION_LEDGER_READY_FOR_REPOSITORY_GATE"
ACCEPTED = "C011_S5C_SHADOW_EVALUATION_LEDGER_ACCEPTED"
NEXT_GATE = "C011_S5D_EXTERNAL_EVIDENCE_AND_PROMOTION_DECISION_BLOCKED_PENDING_OWNER_DECISION"
BASELINE_COMMIT = "a7907bdfa1633ab68efdc8a535e7628181f149ff"
BASELINE_TREE = "3f5babb8c356256de895ef86bb47bdcba6a9e133"
REQUIRED_FILES = (
    "c011_s5c_verification.json",
    "docs/C011_S5C_SHADOW_EVALUATION_LEDGER_REPORT.md",
    "docs/C011_S5C_UPDATE_MANIFEST.json",
    "scripts/verify_c011_s5c.py",
    "src/luna/parallel_cognition/shadow_evaluation.py",
    "tests/test_c011_s5c_shadow_evaluation.py",
)
DECLARED_SCOPE_FILES = frozenset(
    {
        "LUNA_HANDOFF.md",
        "MANIFEST.json",
        "SHA256SUMS.txt",
        "c011_s5c_verification.json",
        "docs/C011_S5C_SHADOW_EVALUATION_LEDGER_REPORT.md",
        "docs/C011_S5C_UPDATE_MANIFEST.json",
        "docs/LUNA_ROADMAP.md",
        "docs/NEURAL_NATIVE_BRIDGE_UPDATE_MANIFEST.json",
        "docs/NEURAL_RUNTIME_NR2B_UPDATE_MANIFEST.json",
        "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        "scripts/check.bat",
        "scripts/verify_c011_s4.py",
        "scripts/verify_c011_s5a.py",
        "scripts/verify_c011_s5b.py",
        "scripts/verify_c011_s5b_real_adapter.py",
        "scripts/verify_c011_s5b_real_evidence.py",
        "scripts/verify_c011_s5c.py",
        "src/luna/parallel_cognition/__init__.py",
        "src/luna/parallel_cognition/shadow_evaluation.py",
        "tests/test_c011_s5c_shadow_evaluation.py",
        "tests/test_project_metadata.py",
    }
)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _canonical_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _metadata_integrity() -> bool:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    if (
        manifest.get("hash_normalization") != "utf8_text_lf_v1"
        or manifest.get("metadata_scope") != "release_artifact_allowlist_v2"
    ):
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            return False
        sums[relative] = digest
    if set(sums) != set(files):
        return False
    for relative, metadata in files.items():
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            return False
        path = ROOT / relative
        if not path.is_file():
            return False
        canonical = _canonical_bytes(path)
        digest = sha256(canonical).hexdigest()
        if (
            metadata.get("sha256") != digest
            or metadata.get("size_bytes") != len(canonical)
            or sums.get(relative) != digest
        ):
            return False
    return True


def _receipt() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((ROOT / "c011_s5c_verification.json").read_text(encoding="utf-8")),
    )


def _fixture_plan() -> ShadowEvaluationPlan:
    evaluator = EvaluatorSpec(
        evaluator_id="c011-s5c-repository-gate",
        revision="1.0.0",
        kind=EvaluatorKind.DETERMINISTIC,
        implementation_sha256=_digest("c011-s5c-repository-gate-v1"),
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
    )
    cases = (
        EvaluationCase(
            case_id="gate-held",
            source_trajectory_id="gate-held-source",
            partition=EvaluationPartition.HELD_OUT,
            task_family="gate-held-task",
            repository_family="gate-held-repository",
            trajectory_family="gate-held-trajectory",
            content_sha256=_digest("gate-held-content"),
            evidence_refs=("fixture:gate-held",),
        ),
        EvaluationCase(
            case_id="gate-ood",
            source_trajectory_id="gate-ood-source",
            partition=EvaluationPartition.OOD,
            task_family="gate-ood-task",
            repository_family="gate-ood-repository",
            trajectory_family="gate-ood-trajectory",
            content_sha256=_digest("gate-ood-content"),
            evidence_refs=("fixture:gate-ood",),
        ),
    )
    suite = FrozenEvaluationSuite.freeze(
        suite_name="c011-s5c-repository-gate-suite",
        revision="1.0.0",
        evaluator=evaluator,
        cases=cases,
    )
    configurations = tuple(ShadowConfiguration)
    arms = tuple(
        ShadowArmSpec(
            configuration=configuration,
            execution_configuration_sha256=_digest(f"gate-execution:{configuration.value}"),
            backend_id="fixture:c011-s5c",
            provider_profile_id="fixture-profile",
            provider_binding_id="fixture-binding",
            model_identity="fixture-candidate",
            driver_sha256=_digest("gate-driver"),
            runtime_sha256=_digest("gate-runtime"),
            environment_sha256=_digest("gate-environment"),
            sampling_sha256=_digest("gate-sampling"),
            seed=17,
            worker_count=2 if configuration is ShadowConfiguration.PARALLEL else 0,
        )
        for configuration in configurations
    )
    slots: list[ShadowRunSlot] = []
    sequence = 0
    for case_id in suite.case_ids:
        for configuration in configurations:
            sequence += 1
            slots.append(
                ShadowRunSlot(
                    schedule_index=sequence,
                    case_id=case_id,
                    repetition=1,
                    configuration=configuration,
                )
            )
    return ShadowEvaluationPlan(
        task_id="22222222-2222-4222-8222-222222222222",
        source_task_revision=1,
        task_contract_sha256=_digest("gate-task-contract"),
        workload_sha256=_digest("gate-workload"),
        prompt_sha256=_digest("gate-prompt"),
        context_manifest_sha256=_digest("gate-context"),
        execution_tree_sha256=_digest("gate-tree"),
        compute_accounting_sha256=_digest("gate-accounting"),
        metric_policy_sha256=_digest("gate-metric-policy"),
        contamination_exposure_manifest_sha256=_digest("gate-exposure-manifest"),
        contamination_provenance_complete=True,
        evaluator_independence_evidence_sha256=_digest("gate-evaluator-evidence"),
        evaluator_independence_verified=True,
        evaluation_suite=suite,
        contamination_report=BenchmarkContaminationReport(),
        equal_compute_budget=EqualComputeBudget(
            max_total_tokens=100,
            max_tool_calls=1,
            max_compute_units=100,
            max_context_bytes=4096,
            max_wall_time_ms=5000,
        ),
        repetitions=1,
        arms=arms,
        run_slots=tuple(slots),
    )


def _fixture_observations(
    plan: ShadowEvaluationPlan,
) -> tuple[ShadowRunObservation, ...]:
    observations: list[ShadowRunObservation] = []
    for index, configuration in enumerate(ShadowConfiguration):
        arm = next(item for item in plan.arms if item.configuration is configuration)
        slot = next(
            item
            for item in plan.run_slots
            if item.case_id == "gate-held" and item.configuration is configuration
        )
        worker_compute = 60 if configuration is ShadowConfiguration.PARALLEL else 0
        observations.append(
            ShadowRunObservation(
                plan_id=plan.plan_id,
                slot_id=slot.slot_id,
                case_id="gate-held",
                repetition=1,
                configuration=configuration,
                execution_configuration_sha256=arm.execution_configuration_sha256,
                evidence_kind=ShadowEvidenceKind.DETERMINISTIC_FIXTURE,
                result_sha256=_digest(f"gate-result:{configuration.value}"),
                evaluator_evidence_refs=(
                    ShadowEvidenceReference(
                        locator=f"fixture:gate-held:{configuration.value}",
                        content_sha256=_digest(f"gate-evidence:{configuration.value}"),
                    ),
                ),
                metrics=ShadowMetricObservation(
                    quality_score_milli=700 + index * 25,
                    required_evidence_count=3,
                    verified_required_evidence_count=3,
                    required_evidence_coverage_milli=1000,
                    latency_ms=1000 - index * 50,
                    input_tokens=40,
                    output_tokens=10,
                    tool_calls=1,
                    root_compute_units=100 - worker_compute,
                    worker_compute_units=worker_compute,
                    compute_units=100,
                    context_bytes=2048,
                    duplicate_work_units=index,
                    stale_rejections=0,
                    worker_rejections=0,
                    unnecessary_spawns=0,
                    changed_basis_respawns=0,
                    contradictions_detected=1,
                    contradictions_resolved=1,
                    user_voice_violations=0,
                ),
            )
        )
    return tuple(observations)


def _fixture_truth() -> bool:
    plan = _fixture_plan()
    observations = _fixture_observations(plan)
    comparison = compare_shadow_observations(
        plan=plan,
        case_id="gate-held",
        repetition=1,
        observations=observations,
    )
    reordered = compare_shadow_observations(
        plan=plan,
        case_id="gate-held",
        repetition=1,
        observations=tuple(reversed(observations)),
    )
    marker = b"S5C-RAW-HIDDEN-REASONING-MUST-NOT-BE-STORED"
    with TemporaryDirectory(prefix="luna-s5c-gate-") as temporary:
        path = Path(temporary) / "shadow.sqlite3"
        ledger = SQLiteShadowEvaluationLedger(path)
        ledger.append_completed_run(
            plan=plan,
            observations=observations,
            comparison=comparison,
        )
        ledger.verify_integrity()
        ledger_ok = ledger.entry_count() == 5 and marker not in path.read_bytes()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "UPDATE shadow_entries SET artifact_sha256 = ? WHERE sequence = 2",
                ("0" * 64,),
            )
            connection.commit()
        try:
            ledger.verify_integrity()
        except ShadowLedgerIntegrityError:
            tamper_rejected = True
        else:
            tamper_rejected = False
    return bool(
        comparison == reordered
        and comparison.status is ShadowComparisonStatus.COMPARABLE
        and comparison.evidence_kinds == (ShadowEvidenceKind.DETERMINISTIC_FIXTURE,)
        and comparison.non_inferiority_established is False
        and comparison.shadow_output_to_task_state is False
        and comparison.root_context_adoption_authority is False
        and comparison.task_state_authority is False
        and comparison.completion_authority is False
        and comparison.user_facing_voice_authority is False
        and comparison.promotion_authority is False
        and ledger_ok
        and tamper_rejected
    )


def _receipt_truth() -> bool:
    receipt = _receipt()
    fixture = receipt.get("fixture_evidence")
    authority = receipt.get("authority")
    return bool(
        receipt.get("stage") == "S5C_SHADOW_EVALUATION_LEDGER"
        and receipt.get("stage_status") in {READY, ACCEPTED}
        and receipt.get("baseline_commit") == BASELINE_COMMIT
        and receipt.get("baseline_tree") == BASELINE_TREE
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("default_enabled") is False
        and receipt.get("production_runtime_wiring_added") is False
        and receipt.get("deterministic_fixture_comparison_executed") is True
        and receipt.get("real_provider_execution") is False
        and receipt.get("live_model_execution") is False
        and receipt.get("equal_compute_non_inferiority_established") is False
        and receipt.get("hidden_chain_of_thought_access") is False
        and isinstance(fixture, dict)
        and fixture.get("configurations") == ["SOLO", "ULTRA_SOLO", "PARALLEL"]
        and fixture.get("complete_triplet") is True
        and fixture.get("normalized_compute_units_per_arm") == 100
        and fixture.get("ledger_entry_count") == 5
        and fixture.get("raw_output_persisted") is False
        and isinstance(authority, dict)
        and authority
        and all(value is False for value in authority.values())
        and receipt.get("next_gate") == NEXT_GATE
    )


def _verification_truth() -> bool:
    receipt = _receipt()
    update = json.loads((ROOT / "docs/C011_S5C_UPDATE_MANIFEST.json").read_text(encoding="utf-8"))
    report = (ROOT / "docs/C011_S5C_SHADOW_EVALUATION_LEDGER_REPORT.md").read_text(encoding="utf-8")
    verification = receipt.get("verification")
    if not isinstance(verification, dict) or verification != update.get("verification"):
        return False
    full = verification.get("repository_full_gate")
    if not isinstance(full, dict):
        return False
    stage = receipt.get("stage_status")
    if stage != update.get("stage_status"):
        return False
    if stage == READY:
        repository_gate = bool(
            full.get("status") == "PENDING"
            and full.get("pytest_passed") is None
            and full.get("verifier_and_cli_chain") == "PENDING"
        )
    elif stage == ACCEPTED:
        repository_gate = bool(
            full.get("status") == "PASS"
            and full.get("pytest_passed") == 1440
            and full.get("pytest_skipped_platform") == 1
            and full.get("ruff") == "PASS"
            and full.get("mypy_strict") == "PASS_312_FILES"
            and full.get("verifier_and_cli_chain") == "PASS_56_OF_56"
            and full.get("execution_environment") == "EXACT_STAGED_TREE_SHORT_WINDOWS_TEMP_PATH"
        )
    else:
        return False
    expected_gates = {
        "research_saturation_gate": "NOT_READY",
        "target_spec": "BLOCKED",
        "controlled_execution": "NONE",
    }
    return bool(
        repository_gate
        and update.get("next_gate") == NEXT_GATE
        and update.get("scope_file_count") == len(DECLARED_SCOPE_FILES)
        and set(update.get("scope_files", ())) == DECLARED_SCOPE_FILES
        and verification.get("focused_fixture_and_adversarial_tests") == "PASS_20"
        and verification.get("changed_scope_ruff") == "PASS"
        and verification.get("changed_scope_mypy_strict") == "PASS"
        and verification.get("deterministic_ledger_gate") == "PASS"
        and receipt.get("aslm_gates") == expected_gates
        and update.get("aslm_gates") == expected_gates
        and str(stage) in report
        and NEXT_GATE in report
        and all(label in report for label in ("VERIFIED", "INFERENCE", "OPEN"))
        and "ASLM Research is a separate project" in report
    )


def _implementation_boundary_truth() -> bool:
    source = (ROOT / "src/luna/parallel_cognition/shadow_evaluation.py").read_text(encoding="utf-8")
    runtime_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "src/luna/runtime").glob("*.py")
    )
    forbidden = (
        "LocalNativeDriverAdapter",
        "SubprocessWorkerBackend",
        "LunaNativeWorker",
        "subprocess.Popen",
        "luna.runtime",
    )
    return bool(
        all(item not in source for item in forbidden)
        and "shadow_evaluation" not in runtime_sources
        and "SQLiteShadowEvaluationLedger" not in runtime_sources
        and "BEGIN IMMEDIATE" in source
        and "PRAGMA synchronous = FULL" in source
        and "PRAGMA journal_mode = WAL" in source
        and "append_completed_run" in source
        and "raw_output_persisted: Literal[False]" in source
        and "non_inferiority_established: Literal[False]" in source
    )


def _governance_truth() -> bool:
    documents = tuple(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "LUNA_HANDOFF.md",
            ROOT / "docs/LUNA_ROADMAP.md",
            ROOT / "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
        )
    )
    check = (ROOT / "scripts/check.bat").read_text(encoding="utf-8")
    return bool(
        all(ACCEPTED in document or READY in document for document in documents)
        and all(NEXT_GATE in document for document in documents)
        and all("controlled C-011 execution: NONE" in document for document in documents)
        and all("Research Saturation Gate: NOT_READY" in document for document in documents)
        and all("Target Spec: BLOCKED" in document for document in documents)
        and "scripts\\verify_c011_s5c.py" in check
        and "[47/62]" in check
        and "S5C" in check
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
        "c011_capability_remains_queued": c011.status is CapabilityStatus.QUEUED,
        "deterministic_fixture_ledger_truthful": _fixture_truth(),
        "receipt_truthful": _receipt_truth(),
        "scope_verification_and_gates_truthful": _verification_truth(),
        "passive_non_authoritative_boundary": _implementation_boundary_truth(),
        "governance_boundaries_truthful": _governance_truth(),
    }
    print(
        json.dumps(
            {
                "capability": "C-011",
                "stage": "S5C_SHADOW_EVALUATION_LEDGER",
                "stage_status": _receipt().get("stage_status"),
                "checks": checks,
                "missing": missing,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
