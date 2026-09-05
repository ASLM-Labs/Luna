"""Deterministic repository gate for the C-011 real equal-compute runner."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Lock
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import CapabilityStatus, build_canonical_capability_registry  # noqa: E402
from luna.parallel_cognition import (  # noqa: E402
    REAL_EQUAL_COMPUTE_RUBRIC_SHA256,
    REPRESENTATIVE_DIMENSIONS,
    EqualComputeBudget,
    FrozenRealEqualComputeSuite,
    RealEqualComputeCallRole,
    RealEqualComputeEvidenceClass,
    RealEqualComputeEvidenceReference,
    RealEqualComputeEvidenceState,
    RealEqualComputeGenerationCall,
    RealEqualComputeGenerationResult,
    RealEqualComputePreflightPolicy,
    RealEqualComputePreflightSnapshot,
    RealEqualComputePrerequisite,
    RealEqualComputePrerequisiteEvidence,
    RealEqualComputeRunDisposition,
    RealRuntimeAssetBinding,
    RealRuntimeConfigurationSet,
    ShadowConfiguration,
    build_c011_bounded_representative_suite,
    build_default_real_runtime_configuration_set,
    execute_real_equal_compute,
)
from luna.parallel_cognition.live import LiveNativeTokenUsage  # noqa: E402

READY = "C011_REAL_EQUAL_COMPUTE_RUNNER_AND_FROZEN_SUITE_READY_FOR_REPOSITORY_GATE"
ACCEPTED = (
    "C011_REAL_EQUAL_COMPUTE_RUNNER_AND_FROZEN_SUITE_"
    "ACCEPTED_BLOCKED_EXTERNAL_EVIDENCE"
)
NEXT_GATE = "C011_REAL_EQUAL_COMPUTE_EXTERNAL_ATTESTATIONS_AND_EXECUTION_BLOCKED"
BASELINE_COMMIT = "6550d6fa50c59e8eb60e8aa68778cd433217d5c7"
BASELINE_TREE = "edfc4629acd86d40d791d78dfaf4d69e3153040a"
TARGET_BRANCH = "capability/c011-single-voice-parallel-cognition"
EVALUATED_AT = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
SUITE_ID = (
    "c011-real-equal-compute-suite:sha256:"
    "2631da6488995b0620ab2457b24bd9969165466867b2fe8af2352ae6b101b79d"
)

REQUIRED_FILES = frozenset(
    {
        "c011_equal_compute_runner_verification.json",
        "docs/C011_REAL_EQUAL_COMPUTE_FROZEN_SUITE_RECEIPT.json",
        "docs/C011_REAL_EQUAL_COMPUTE_RUNNER_REPORT.md",
        "docs/C011_REAL_EQUAL_COMPUTE_RUNNER_UPDATE_MANIFEST.json",
        "scripts/verify_c011_equal_compute_runner.py",
        "src/luna/parallel_cognition/equal_compute_runner.py",
        "tests/test_c011_equal_compute_runner.py",
    }
)


def _canonical_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _meta(path: Path) -> tuple[str, int]:
    content = _canonical_bytes(path)
    return sha256(content).hexdigest(), len(content)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _json(relative: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((ROOT / relative).read_text(encoding="utf-8")),
    )


def _metadata_truth() -> bool:
    manifest = _json("MANIFEST.json")
    files = manifest.get("files")
    if (
        manifest.get("hash_normalization") != "utf8_text_lf_v1"
        or manifest.get("metadata_scope") != "release_artifact_allowlist_v2"
        or not isinstance(files, dict)
    ):
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
        digest, size = _meta(path)
        if metadata != {"sha256": digest, "size_bytes": size}:
            return False
        if sums.get(relative) != digest:
            return False
    return True


def _configuration(parallel_workers: int) -> RealRuntimeConfigurationSet:
    proof = _json("docs/C011_RUNTIME_CONFIGURATION_REAL_PROOF_RECEIPT.json")
    assets = cast(dict[str, Any], proof["assets"])
    binding = RealRuntimeAssetBinding(
        backend_id=cast(str, proof["backend_id"]),
        provider_profile_id=cast(str, proof["profile_id"]),
        provider_binding_id=cast(str, proof["member_binding_id"]),
        model_identity=f"{assets['model_source_identity']}@sha256:{assets['model_sha256']}",
        model_artifact_sha256=cast(str, assets["model_sha256"]),
        bridge_artifact_sha256=cast(str, assets["bridge_sha256"]),
        driver_artifact_sha256=cast(str, assets["driver_sha256"]),
        runtime_bundle_sha256=cast(str, assets["runtime_bundle_sha256"]),
        environment_sha256=cast(str, assets["environment_sha256"]),
        sampling_sha256=_digest("greedy:temperature=0:seed=0:abi-v2"),
    )
    return build_default_real_runtime_configuration_set(
        asset_binding=binding,
        equal_compute_budget=EqualComputeBudget(
            max_total_tokens=2048,
            max_tool_calls=0,
            max_compute_units=1000,
            max_context_bytes=32768,
            max_wall_time_ms=240000,
        ),
        parallel_workers=cast("Any", parallel_workers),
    )


def _suite() -> FrozenRealEqualComputeSuite:
    return build_c011_bounded_representative_suite(
        target_branch=TARGET_BRANCH,
        source_commit_oid=BASELINE_COMMIT,
        source_tree_oid=BASELINE_TREE,
    )


def _policy() -> RealEqualComputePreflightPolicy:
    return RealEqualComputePreflightPolicy(
        target_branch=TARGET_BRANCH,
        target_commit_oid=BASELINE_COMMIT,
        target_tree_oid=BASELINE_TREE,
        evaluated_at_utc=EVALUATED_AT,
    )


def _reference(
    prerequisite: RealEqualComputePrerequisite,
    digest: str,
    *,
    synthetic: bool = False,
) -> RealEqualComputeEvidenceReference:
    prefix = "synthetic-verifier" if synthetic else "repository"
    return RealEqualComputeEvidenceReference(
        locator=f"{prefix}:{prerequisite.value.lower()}",
        content_sha256=digest,
        source_revision="c011-e5-verifier-v1",
    )


def _items(
    configuration: RealRuntimeConfigurationSet,
    *,
    external_ready: bool,
) -> tuple[RealEqualComputePrerequisiteEvidence, ...]:
    suite = _suite()
    arm_digests = {
        ShadowConfiguration.SOLO: configuration.arms[0].configuration_sha256,
        ShadowConfiguration.ULTRA_SOLO: configuration.arms[1].configuration_sha256,
        ShadowConfiguration.PARALLEL: configuration.arms[2].configuration_sha256,
    }
    local: dict[
        RealEqualComputePrerequisite,
        tuple[RealEqualComputeEvidenceClass, str],
    ] = {
        RealEqualComputePrerequisite.CURRENT_ASSET_BINDING: (
            RealEqualComputeEvidenceClass.REAL_PROVIDER_MEASUREMENT,
            configuration.asset_binding.asset_binding_id.rsplit(":", maxsplit=1)[-1],
        ),
        RealEqualComputePrerequisite.MEASURED_TOKEN_ACCOUNTING: (
            RealEqualComputeEvidenceClass.REAL_PROVIDER_MEASUREMENT,
            _digest("accepted-native-abi-v2-engine-counters"),
        ),
        RealEqualComputePrerequisite.SOLO_RUNTIME_CONTRACT: (
            RealEqualComputeEvidenceClass.REPOSITORY_SOURCE,
            arm_digests[ShadowConfiguration.SOLO],
        ),
        RealEqualComputePrerequisite.ULTRA_SOLO_RUNTIME_CONTRACT: (
            RealEqualComputeEvidenceClass.REPOSITORY_SOURCE,
            arm_digests[ShadowConfiguration.ULTRA_SOLO],
        ),
        RealEqualComputePrerequisite.PARALLEL_RUNTIME_CONTRACT: (
            RealEqualComputeEvidenceClass.REPOSITORY_SOURCE,
            arm_digests[ShadowConfiguration.PARALLEL],
        ),
        RealEqualComputePrerequisite.REPRESENTATIVE_FROZEN_SUITE: (
            RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT,
            suite.suite_sha256,
        ),
    }
    partial = {
        RealEqualComputePrerequisite.HARDWARE_RESOURCE_ATTESTATION,
        RealEqualComputePrerequisite.SAFETY_CONTAINMENT_ATTESTATION,
    }
    values: list[RealEqualComputePrerequisiteEvidence] = []
    for prerequisite in RealEqualComputePrerequisite:
        if prerequisite in local:
            evidence_class, digest = local[prerequisite]
            values.append(
                RealEqualComputePrerequisiteEvidence(
                    prerequisite=prerequisite,
                    state=RealEqualComputeEvidenceState.VERIFIED,
                    evidence_class=evidence_class,
                    evidence_refs=(_reference(prerequisite, digest),),
                    observed_at_utc=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
                    provenance_complete=True,
                )
            )
        elif external_ready:
            values.append(
                RealEqualComputePrerequisiteEvidence(
                    prerequisite=prerequisite,
                    state=RealEqualComputeEvidenceState.VERIFIED,
                    evidence_class=RealEqualComputeEvidenceClass.EXTERNAL_ATTESTATION,
                    evidence_refs=(
                        _reference(
                            prerequisite,
                            _digest(f"synthetic:{prerequisite.value}"),
                            synthetic=True,
                        ),
                    ),
                    observed_at_utc=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
                    provenance_complete=True,
                    independently_attested=True,
                )
            )
        elif prerequisite in partial:
            values.append(
                RealEqualComputePrerequisiteEvidence(
                    prerequisite=prerequisite,
                    state=RealEqualComputeEvidenceState.PARTIAL,
                    evidence_class=RealEqualComputeEvidenceClass.REPOSITORY_RECEIPT,
                    evidence_refs=(
                        _reference(prerequisite, _digest(prerequisite.value)),
                    ),
                    observed_at_utc=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
                    limitations=("repository evidence is not external attestation",),
                )
            )
        else:
            values.append(
                RealEqualComputePrerequisiteEvidence(
                    prerequisite=prerequisite,
                    state=RealEqualComputeEvidenceState.OPEN,
                    evidence_class=RealEqualComputeEvidenceClass.NONE,
                    limitations=("external attestation is absent",),
                )
            )
    return tuple(values)


def _snapshot(
    configuration: RealRuntimeConfigurationSet,
    *,
    external_ready: bool,
) -> RealEqualComputePreflightSnapshot:
    return RealEqualComputePreflightSnapshot(
        target_branch=TARGET_BRANCH,
        target_commit_oid=BASELINE_COMMIT,
        target_tree_oid=BASELINE_TREE,
        evaluated_at_utc=EVALUATED_AT,
        items=_items(configuration, external_ready=external_ready),
    )


@dataclass(slots=True)
class _DeterministicExecutor:
    configuration_set_id: str
    parallel_workers: int
    calls: list[RealEqualComputeGenerationCall] = field(default_factory=list)
    maximum: int = 0
    _active: int = 0
    _lock: Lock = field(default_factory=Lock)
    _barriers: dict[str, Barrier] = field(default_factory=dict)

    def execute(
        self,
        *,
        call: RealEqualComputeGenerationCall,
    ) -> RealEqualComputeGenerationResult:
        with self._lock:
            self.calls.append(call)
            self._active += 1
            self.maximum = max(self.maximum, self._active)
            barrier = self._barriers.setdefault(
                call.case_id,
                Barrier(self.parallel_workers),
            )
        parallel_roles = (
            RealEqualComputeCallRole.PARALLEL_EVIDENCE,
            RealEqualComputeCallRole.PARALLEL_ADVERSARIAL,
            RealEqualComputeCallRole.PARALLEL_ALTERNATIVE,
        )
        try:
            if call.role in parallel_roles[: self.parallel_workers]:
                barrier.wait(timeout=5)
            return RealEqualComputeGenerationResult(
                call_id=call.call_id,
                final_text=f"verified-final:{call.case_id}:{call.role.value}",
                native_usage=LiveNativeTokenUsage(
                    input_tokens=2,
                    output_tokens=1,
                    total_tokens=3,
                ),
                runtime_ms=1,
            )
        finally:
            with self._lock:
                self._active -= 1


@dataclass(slots=True)
class _NeverExecutor:
    configuration_set_id: str
    calls: int = 0

    def execute(
        self,
        *,
        call: RealEqualComputeGenerationCall,
    ) -> RealEqualComputeGenerationResult:
        del call
        self.calls += 1
        raise AssertionError("blocked E5 verifier reached the provider boundary")


def _runner_truth() -> bool:
    expectations = {2: 36, 3: 42}
    for workers, expected_calls in expectations.items():
        configuration = _configuration(workers)
        executor = _DeterministicExecutor(
            configuration_set_id=configuration.configuration_set_id,
            parallel_workers=workers,
        )
        receipt = execute_real_equal_compute(
            policy=_policy(),
            snapshot=_snapshot(configuration, external_ready=True),
            configuration_set=configuration,
            suite=_suite(),
            executor=executor,
        )
        serialized = receipt.model_dump_json()
        if not (
            receipt.disposition is RealEqualComputeRunDisposition.EXECUTED
            and receipt.provider_calls_executed == expected_calls
            and len(executor.calls) == expected_calls
            and len({item.call_id for item in executor.calls}) == expected_calls
            and receipt.max_concurrent_generations_observed == workers
            and executor.maximum == workers
            and receipt.full_triplet_completed
            and "verified-final" not in serialized
            and "final_text" not in serialized
            and not receipt.raw_output_persisted
            and not receipt.raw_analysis_persisted
            and not receipt.controlled_c011_execution
            and not receipt.promotion_authority
        ):
            return False
    return True


def _current_block_truth() -> bool:
    configuration = _configuration(2)
    executor = _NeverExecutor(configuration_set_id=configuration.configuration_set_id)
    receipt = execute_real_equal_compute(
        policy=_policy(),
        snapshot=_snapshot(configuration, external_ready=False),
        configuration_set=configuration,
        suite=_suite(),
        executor=executor,
    )
    return bool(
        receipt.disposition is RealEqualComputeRunDisposition.BLOCKED_PREFLIGHT
        and executor.calls == 0
        and receipt.provider_calls_executed == 0
        and not receipt.case_receipts
        and not receipt.full_triplet_completed
        and not receipt.controlled_c011_execution
        and not receipt.promotion_authority
    )


def _suite_truth() -> bool:
    suite = _suite()
    receipt = _json("docs/C011_REAL_EQUAL_COMPUTE_FROZEN_SUITE_RECEIPT.json")
    expected_cases = [
        {
            "case_id": item.case_id,
            "case_content_sha256": item.case_content_sha256,
            "partition": item.partition.value,
            "task_family": item.task_family,
            "source_trajectory_id": item.source_trajectory_id,
        }
        for item in suite.cases
    ]
    evaluator = receipt.get("evaluator")
    execution = receipt.get("execution")
    authority = receipt.get("authority")
    return bool(
        suite.suite_id == SUITE_ID
        and receipt.get("status") == "PASS_C011_BOUNDED_FROZEN_SUITE_BUILT"
        and receipt.get("source_commit_oid") == BASELINE_COMMIT
        and receipt.get("source_tree_oid") == BASELINE_TREE
        and receipt.get("suite_id") == suite.suite_id
        and receipt.get("suite_sha256") == suite.suite_sha256
        and receipt.get("case_count") == 6
        and receipt.get("representative_dimensions") == list(REPRESENTATIVE_DIMENSIONS)
        and receipt.get("cases") == expected_cases
        and isinstance(evaluator, dict)
        and evaluator.get("rubric_sha256") == REAL_EQUAL_COMPUTE_RUBRIC_SHA256
        and evaluator.get("independent_evaluator_attested") is False
        and evaluator.get("contamination_provenance_attested") is False
        and evaluator.get("external_ledger_anchored") is False
        and evaluator.get("hidden_reasoning_required") is False
        and isinstance(execution, dict)
        and execution.get("provider_calls_executed") == 0
        and execution.get("real_equal_compute_triplet_executed") is False
        and execution.get("controlled_c011_execution") is False
        and isinstance(authority, dict)
        and authority
        and all(value is False for value in authority.values())
    )


def _source_truth(receipt: dict[str, Any]) -> bool:
    basis = receipt.get("source_basis")
    if not isinstance(basis, dict) or len(basis) != 5:
        return False
    for item in basis.values():
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return False
        path = ROOT / item["path"]
        if not path.is_file():
            return False
        digest, size = _meta(path)
        if item.get("canonical_text_lf_sha256") != digest:
            return False
        if item.get("size_bytes") != size:
            return False
    return True


def _verification_truth(
    stage: str,
    receipt: dict[str, Any],
    update: dict[str, Any],
) -> bool:
    verification = receipt.get("verification")
    full = verification.get("repository_full_gate") if isinstance(verification, dict) else None
    if not isinstance(verification, dict) or not isinstance(full, dict):
        return False
    if stage == READY:
        full_truth = bool(
            full.get("status") == "PENDING"
            and full.get("pytest_passed") is None
            and full.get("ruff") == "PENDING"
            and full.get("mypy_strict") == "PENDING"
            and full.get("verifier_and_cli_chain") == "PENDING"
        )
    elif stage == ACCEPTED:
        full_truth = bool(
            full.get("status") == "PASS"
            and full.get("pytest_passed") == 1539
            and full.get("pytest_skipped_platform") == 1
            and full.get("ruff") == "PASS"
            and full.get("mypy_strict") == "PASS_318_FILES"
            and full.get("verifier_and_cli_chain") == "PASS_62_OF_62"
            and full.get("execution_environment")
            == "EXACT_STAGED_TREE_SHORT_WINDOWS_TEMP_PATH"
        )
    else:
        return False
    return bool(
        stage == update.get("stage_status")
        and full_truth
        and verification.get("focused_runner_and_adversarial_tests") == "PASS_17"
        and verification.get("changed_scope_ruff") == "PASS"
        and verification.get("changed_scope_mypy_strict") == "PASS_3_FILES"
        and verification.get("deterministic_schedule_proof") == "PASS_36_AND_42_CALLS"
        and verification.get("current_preflight_block") == "PASS_ZERO_PROVIDER_CALLS"
    )


def _governance_truth(stage: str) -> bool:
    documents = tuple(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "LUNA_HANDOFF.md",
            ROOT / "docs/LUNA_ROADMAP.md",
            ROOT / "docs/rfcs/RFC-C011_SINGLE_VOICE_PARALLEL_COGNITION.md",
            ROOT / "docs/C011_REAL_EQUAL_COMPUTE_RUNNER_REPORT.md",
        )
    )
    check = (ROOT / "scripts/check.bat").read_text(encoding="utf-8")
    return bool(
        all(stage in document and NEXT_GATE in document for document in documents)
        and all("controlled C-011 execution: NONE" in document for document in documents)
        and all("Research Saturation Gate: NOT_READY" in document for document in documents)
        and all("Target Spec: BLOCKED" in document for document in documents)
        and all("chain-of-thought access" in document.lower() for document in documents)
        and "scripts\\verify_c011_equal_compute_runner.py" in check
        and "[53/62]" in check
        and "S5D-E5" in check
    )


def main() -> int:
    receipt = _json("c011_equal_compute_runner_verification.json")
    update = _json("docs/C011_REAL_EQUAL_COMPUTE_RUNNER_UPDATE_MANIFEST.json")
    stage = cast(str, receipt.get("stage_status"))
    scope_files = update.get("scope_files")
    authority = receipt.get("authority")
    prerequisites = receipt.get("preflight_prerequisites_after")
    c011 = build_canonical_capability_registry().get("C-011")
    checks = {
        "required_files_present": all((ROOT / item).is_file() for item in REQUIRED_FILES),
        "metadata_integrity": _metadata_truth(),
        "receipt_identity": receipt.get("stage")
        == "S5D_E5_REAL_EQUAL_COMPUTE_RUNNER_AND_FROZEN_SUITE"
        and stage in {READY, ACCEPTED}
        and receipt.get("baseline_commit") == BASELINE_COMMIT
        and receipt.get("baseline_tree") == BASELINE_TREE
        and receipt.get("target_branch") == TARGET_BRANCH,
        "declared_scope_complete": isinstance(scope_files, list)
        and len(scope_files) == len(set(scope_files))
        and REQUIRED_FILES.issubset(scope_files)
        and update.get("scope_file_count") == len(scope_files),
        "c011_remains_queued_default_off": c011.status is CapabilityStatus.QUEUED
        and receipt.get("capability_status") == "QUEUED"
        and receipt.get("default_enabled") is False
        and receipt.get("rollout_stage") == "BLOCKED",
        "source_basis_content_addressed": _source_truth(receipt),
        "bounded_frozen_suite_content_addressed": _suite_truth(),
        "deterministic_runner_schedules_fail_closed": _runner_truth(),
        "current_external_gaps_block_before_provider": _current_block_truth(),
        "preflight_state_truthful": prerequisites
        == {
            "verified_local": [
                "CURRENT_ASSET_BINDING",
                "MEASURED_TOKEN_ACCOUNTING",
                "PARALLEL_RUNTIME_CONTRACT",
                "REPRESENTATIVE_FROZEN_SUITE",
                "SOLO_RUNTIME_CONTRACT",
                "ULTRA_SOLO_RUNTIME_CONTRACT",
            ],
            "partial": [
                "HARDWARE_RESOURCE_ATTESTATION",
                "SAFETY_CONTAINMENT_ATTESTATION",
            ],
            "open_external": [
                "CONTAMINATION_PROVENANCE_ATTESTATION",
                "EXTERNAL_LEDGER_ANCHOR",
                "INDEPENDENT_EVALUATOR_ATTESTATION",
            ],
            "rejected": [],
        },
        "verification_truthful": _verification_truth(stage, receipt, update),
        "authority_remains_absent": isinstance(authority, dict)
        and authority
        and all(value is False for value in authority.values())
        and receipt.get("controlled_c011_execution") is False
        and receipt.get("production_runtime_wiring_added") is False
        and receipt.get("real_equal_compute_triplet_executed") is False
        and receipt.get("hidden_chain_of_thought_access") is False,
        "aslm_gates_unchanged": receipt.get("aslm_gates")
        == {
            "research_saturation_gate": "NOT_READY",
            "target_spec": "BLOCKED",
            "controlled_execution": "NONE",
        }
        and receipt.get("aslm_gates") == update.get("aslm_gates"),
        "next_gate_locked": receipt.get("next_gate") == NEXT_GATE
        and update.get("next_gate") == NEXT_GATE,
        "governance_boundaries_truthful": _governance_truth(stage),
    }
    print(
        json.dumps(
            {
                "capability": "C-011",
                "stage": "S5D_E5_REAL_EQUAL_COMPUTE_RUNNER_AND_FROZEN_SUITE",
                "stage_status": stage,
                "checks": checks,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
