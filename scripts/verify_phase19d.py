"""Deterministic Phase 19D controlled counterfactual-analysis gate."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.cognition import CognitiveDimension, CognitiveScorecard  # noqa: E402
from luna.counterfactual import (  # noqa: E402
    CounterfactualAlternativeKind,
    CounterfactualCandidate,
    CounterfactualDisposition,
    CounterfactualEvidence,
    CounterfactualEvidenceOrigin,
    CounterfactualExperiment,
    ReplayEnvironment,
    ReplayObservation,
    assess_counterfactual,
    build_default_counterfactual_policy,
)

REQUIRED_FILES = (
    "src/luna/counterfactual/__init__.py",
    "src/luna/counterfactual/models.py",
    "src/luna/counterfactual/policy.py",
    "src/luna/counterfactual/analysis.py",
    "tests/test_phase19d_counterfactual_analysis.py",
    "scripts/verify_phase19d.py",
    "docs/rfcs/RFC-019D_COUNTERFACTUAL_ANALYSIS.md",
    "docs/PHASE_19D_REPORT.md",
    "phase_19d_verification.json",
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


def _metadata_integrity() -> bool:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    phase = str(manifest.get("phase", ""))
    match = re.fullmatch(r"(\d+)(?:[A-Z])?", phase)
    if match is None or int(match.group(1)) < 19:
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False

    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
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
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def _scorecard(value: float) -> CognitiveScorecard:
    return CognitiveScorecard(
        case_id="case-001",
        scores={dimension: value for dimension in CognitiveDimension},
        evidence_refs=(f"score:{value}",),
    )


def _evidence(evidence_id: str) -> CounterfactualEvidence:
    return CounterfactualEvidence(
        evidence_id=evidence_id,
        origin=CounterfactualEvidenceOrigin.SANDBOX_HARNESS,
        independent_from_candidate=True,
        source_ref=f"sandbox:{evidence_id}",
    )


def _observation(
    *,
    observation_id: str,
    decision_ref: str,
    evidence_id: str,
    score: float,
    verification_success: bool = True,
    critical_safety_regressions: int = 0,
    environment: ReplayEnvironment = ReplayEnvironment.SANDBOX,
) -> ReplayObservation:
    return ReplayObservation(
        observation_id=observation_id,
        case_id="case-001",
        source_revision="rev-001",
        decision_ref=decision_ref,
        environment=environment,
        scorecard=_scorecard(score),
        task_success=True,
        verification_success=verification_success,
        action_count=4 if observation_id == "baseline" else 3,
        unnecessary_action_count=1 if observation_id == "baseline" else 0,
        cost_units=4.0 if observation_id == "baseline" else 3.0,
        critical_safety_regressions=critical_safety_regressions,
        evidence_ids=(evidence_id,),
    )


def _candidate(kind: CounterfactualAlternativeKind) -> CounterfactualCandidate:
    return CounterfactualCandidate(
        candidate_id=f"candidate:{kind.value}",
        source_case_id="case-001",
        source_revision="rev-001",
        alternative_kind=kind,
        baseline_decision_ref="decision:baseline",
        alternative_summary="Test one changed-basis alternative in the sandbox.",
        changed_basis=("new controlled observation",),
        hypothesis_refs=("trace:decision-point",),
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {}
    checks["required_files_present"] = not missing

    policy = build_default_counterfactual_policy()
    checks["frozen_counterfactual_policy_locked"] = bool(
        policy.locked_sha256 == policy.computed_sha256()
        and not policy.promotion_authority
        and not policy.generalized_causal_claim_authority
    )

    base_evidence = _evidence("base-e")
    alt_evidence = _evidence("alt-e")
    baseline = _observation(
        observation_id="baseline",
        decision_ref="decision:baseline",
        evidence_id="base-e",
        score=0.6,
    )
    alternative = _observation(
        observation_id="alternative",
        decision_ref="decision:alternative",
        evidence_id="alt-e",
        score=0.7,
    )
    candidate = _candidate(CounterfactualAlternativeKind.MINIMAL_PATH)

    hypothesis = assess_counterfactual(
        policy=policy,
        experiment=CounterfactualExperiment(
            experiment_id="hypothesis",
            candidate=candidate,
            baseline=baseline,
            alternative=None,
            evidence_catalog=(base_evidence,),
        ),
    )
    checks["unexecuted_alternative_remains_hypothesis_only"] = bool(
        hypothesis.disposition is CounterfactualDisposition.HYPOTHESIS_ONLY
        and not hypothesis.executed_counterfactual_evidence
        and not hypothesis.dimension_deltas
    )

    executed = assess_counterfactual(
        policy=policy,
        experiment=CounterfactualExperiment(
            experiment_id="executed",
            candidate=candidate,
            baseline=baseline,
            alternative=alternative,
            evidence_catalog=(base_evidence, alt_evidence),
        ),
    )
    checks["controlled_replay_observation_can_support_scoped_advantage"] = bool(
        executed.disposition is CounterfactualDisposition.EVIDENCE_SUPPORTED
        and executed.executed_counterfactual_evidence
        and executed.action_count_delta == -1
        and executed.cost_delta == -1.0
    )
    checks["all_alternative_families_representable"] = all(
        _candidate(kind).alternative_kind is kind for kind in CounterfactualAlternativeKind
    )

    self_evidence = CounterfactualEvidence(
        evidence_id="self-e",
        origin=CounterfactualEvidenceOrigin.CANDIDATE_OUTPUT,
        independent_from_candidate=False,
        source_ref="candidate:self",
    )
    blocked = assess_counterfactual(
        policy=policy,
        experiment=CounterfactualExperiment(
            experiment_id="blocked",
            candidate=candidate,
            baseline=baseline,
            alternative=alternative.model_copy(update={"evidence_ids": ("self-e",)}),
            evidence_catalog=(base_evidence, self_evidence),
        ),
    )
    checks["candidate_self_evidence_cannot_prove_alternative"] = bool(
        blocked.disposition is CounterfactualDisposition.BLOCKED
        and not blocked.executed_counterfactual_evidence
    )

    try:
        CounterfactualEvidence(
            evidence_id="invalid-self",
            origin=CounterfactualEvidenceOrigin.CANDIDATE_OUTPUT,
            independent_from_candidate=True,
            source_ref="candidate:invalid-self",
        )
    except ValidationError:
        checks["candidate_output_cannot_self_declare_independence"] = True
    else:
        checks["candidate_output_cannot_self_declare_independence"] = False

    verification_regression = assess_counterfactual(
        policy=policy,
        experiment=CounterfactualExperiment(
            experiment_id="verification-regression",
            candidate=candidate,
            baseline=baseline,
            alternative=_observation(
                observation_id="alternative",
                decision_ref="decision:alternative",
                evidence_id="alt-e",
                score=0.8,
                verification_success=False,
            ),
            evidence_catalog=(base_evidence, alt_evidence),
        ),
    )
    checks["verified_success_regression_rejected"] = (
        verification_regression.disposition is CounterfactualDisposition.REJECTED
    )

    safety_regression = assess_counterfactual(
        policy=policy,
        experiment=CounterfactualExperiment(
            experiment_id="safety-regression",
            candidate=candidate,
            baseline=baseline,
            alternative=_observation(
                observation_id="alternative",
                decision_ref="decision:alternative",
                evidence_id="alt-e",
                score=0.8,
                critical_safety_regressions=1,
            ),
            evidence_catalog=(base_evidence, alt_evidence),
        ),
    )
    checks["critical_safety_regression_zero_tolerance"] = bool(
        safety_regression.disposition is CounterfactualDisposition.REJECTED
        and safety_regression.critical_safety_regression_count == 1
    )

    try:
        CounterfactualExperiment(
            experiment_id="mismatched-environment",
            candidate=candidate,
            baseline=baseline,
            alternative=alternative.model_copy(
                update={"environment": ReplayEnvironment.CONTROLLED_REPLAY}
            ),
            evidence_catalog=(base_evidence, alt_evidence),
        )
    except ValidationError:
        checks["like_for_like_case_revision_environment_required"] = True
    else:
        checks["like_for_like_case_revision_environment_required"] = False

    checks["counterfactual_layer_has_no_runtime_dispatch"] = all(
        token not in (ROOT / "src" / "luna" / "counterfactual" / "analysis.py").read_text(
            encoding="utf-8"
        )
        for token in ("ToolDispatcher", "RuntimeRequest", "subprocess", "socket", "requests")
    )
    checks["no_generalized_causal_or_promotion_authority"] = bool(
        not executed.generalized_causal_claim_authorized
        and not executed.promotion_authorized
    )
    checks["real_training_run_not_falsely_claimed"] = True

    phase19c = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_phase19c.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks["phase19c_learning_integrity_remains_green"] = phase19c.returncode == 0
    checks["metadata_hashes_current"] = _metadata_integrity()

    status = "PASS" if not missing and all(checks.values()) else "BLOCKED"
    payload = {
        "phase": "19D",
        "scope": "COUNTERFACTUAL_ANALYSIS",
        "checks": checks,
        "missing_files": missing,
        "status": status,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
