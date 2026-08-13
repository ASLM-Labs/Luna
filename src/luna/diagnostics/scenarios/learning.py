"""Learning Luna diagnostic scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from luna.cognition import (
    CognitiveDimension,
    CognitiveScorecard,
    ConfidenceBand,
    EvidenceState,
    FrozenCognitiveBaseline,
    SelfCorrectionAssessment,
    assess_uncertainty,
    compare_to_baseline,
)
from luna.counterfactual import (
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
from luna.diagnostics.models import SmokeReport, legacy_contract_report
from luna.evaluation_governance import (
    EvaluationCase,
    EvaluationPartition,
    EvaluatorKind,
    EvaluatorSpec,
    FrozenEvaluationSuite,
    ReleaseComparisonStatus,
    TrainingExposure,
    build_release_snapshot,
    compare_release_snapshots,
    detect_benchmark_contamination,
    freeze_regression_suite,
)
from luna.improvement_gate import (
    ImprovementGateDecision,
    build_default_improvement_gate_policy,
    evaluate_improvement_gate,
)
from luna.learning_integrity import (
    ClaimEvidenceReview,
    EvaluatorAgreementProbe,
    GeneralizationProfile,
    IntegrityEvidence,
    LearningExposureRecord,
    LearningIntegrityRisk,
    LearningIntegrityStatus,
    ProxyMetricOutcome,
    ShortcutSliceProbe,
    assess_learning_integrity,
    build_default_learning_integrity_policy,
)
from luna.learning_integrity import EvidenceOrigin as IntegrityEvidenceOrigin
from luna.sft import audit_sft_corpus, build_default_sft_policy, prepare_sft_candidate
from luna.trajectories import (
    DatasetSplit,
    DatasetTaxonomy,
    LeakFreeSplitter,
    SourceTraceRow,
    StructuredDecisionTrace,
    TraceStage,
    TrainingTransformer,
    TrajectoryOutcome,
    TrajectoryReconstructor,
)


def run_phase19() -> SmokeReport:
    reconstructor = TrajectoryReconstructor()

    def build_trace(
        source_id: str, task_family: str, trajectory_family: str
    ) -> StructuredDecisionTrace:
        rows = (
            SourceTraceRow(
                source_trajectory_id=source_id,
                sequence=0,
                stage=TraceStage.TASK,
                summary="Repair a failing quality gate.",
            ),
            SourceTraceRow(
                source_trajectory_id=source_id,
                sequence=1,
                stage=TraceStage.PLAN,
                summary="Inspect the failing gate before editing.",
            ),
            SourceTraceRow(
                source_trajectory_id=source_id,
                sequence=2,
                stage=TraceStage.ACTION,
                summary="Run a focused verifier.",
                tool_name="pytest",
                tool_arguments={"argv": ["pytest", "-q"]},
            ),
            SourceTraceRow(
                source_trajectory_id=source_id,
                sequence=3,
                stage=TraceStage.OBSERVATION,
                summary="The observed failure narrows the changed basis.",
                evidence_refs=("gate:evidence",),
            ),
            SourceTraceRow(
                source_trajectory_id=source_id,
                sequence=4,
                stage=TraceStage.REPLAN,
                summary="Change strategy using the new evidence.",
                decision_basis=("gate:evidence",),
            ),
            SourceTraceRow(
                source_trajectory_id=source_id,
                sequence=5,
                stage=TraceStage.VERIFICATION,
                summary="Focused and full verification pass.",
                evidence_refs=("gate:pass",),
            ),
            SourceTraceRow(
                source_trajectory_id=source_id,
                sequence=6,
                stage=TraceStage.FINAL,
                summary="The evidence-bound repair is complete.",
                evidence_refs=("gate:pass",),
            ),
        )
        return reconstructor.reconstruct(
            rows=rows,
            trajectory_family=trajectory_family,
            task_family=task_family,
            repository_family="luna",
            taxonomy=DatasetTaxonomy.IMPLEMENTATION_CODING,
            task_summary="Repair a failing quality gate.",
            outcome=TrajectoryOutcome.SUCCESS,
            provenance_refs=(f"trace:{source_id}",),
            license_reviewed=True,
            pii_reviewed=True,
        )

    known = build_trace("phase19-known", "known-quality-gate", "known-family")
    held = build_trace("phase19-held", "unseen-held-out", "novel-family")
    split_report = LeakFreeSplitter(
        held_out_task_families=("unseen-held-out",), validation_percent=10
    ).assign((known, held))
    held_assignment = next(
        item for item in split_report.assignments if item.source_trajectory_id == "phase19-held"
    )
    training_examples = TrainingTransformer().transform(trace=known, split=DatasetSplit.TRAIN)
    uncertainty = assess_uncertainty(
        confidence=ConfidenceBand.HIGH,
        evidence=EvidenceState.CONTRADICTORY,
        evidence_refs=("verifier:contradiction",),
    )
    correction = SelfCorrectionAssessment(
        failed_assumption_identified=True,
        new_evidence_observed=True,
        strategy_changed=True,
        changed_dimensions=("assumption", "strategy"),
    )
    baseline_scores = {dimension: 0.5 for dimension in CognitiveDimension}
    baseline_card = CognitiveScorecard(
        case_id="held-001", scores=baseline_scores, evidence_refs=("baseline:held-001",)
    )
    baseline = FrozenCognitiveBaseline.freeze(
        baseline_name="phase19-pretraining", revision="1.0.0", scorecards=(baseline_card,)
    )
    candidate_scores = dict(baseline_scores)
    candidate_scores[CognitiveDimension.PLANNING] = 0.6
    candidate = CognitiveScorecard(
        case_id="held-001", scores=candidate_scores, evidence_refs=("candidate:held-001",)
    )
    comparison = compare_to_baseline(baseline=baseline, candidate_scorecards=(candidate,))
    training_example_count = len(training_examples)
    planning_delta = comparison.dimension_deltas[CognitiveDimension.PLANNING]
    payload = {
        "raw_hidden_cot_included": known.raw_hidden_chain_of_thought_included,
        "structured_stage_count": len(known.events),
        "held_out_split": held_assignment.split.value,
        "contamination_detected": split_report.contamination_detected,
        "training_example_count": training_example_count,
        "target_only_loss": all(item.target_only_loss for item in training_examples),
        "uncertainty_directive": uncertainty.directive.value,
        "changed_basis_self_correction": correction.changed_basis,
        "baseline_locked": baseline.locked_sha256 == baseline.computed_sha256(),
        "planning_delta": planning_delta,
        "comparison_verdict": comparison.verdict.value,
        "training_run_executed": False,
    }
    return legacy_contract_report(
        "phase19",
        payload,
        all(
            (
                payload["raw_hidden_cot_included"] is False,
                payload["structured_stage_count"] == 7,
                payload["held_out_split"] == "HELD_OUT",
                payload["contamination_detected"] is False,
                training_example_count >= 4,
                payload["target_only_loss"] is True,
                payload["uncertainty_directive"] == "STOP",
                payload["changed_basis_self_correction"] is True,
                payload["baseline_locked"] is True,
                planning_delta > 0.0,
                payload["comparison_verdict"] == "ACCEPT",
                payload["training_run_executed"] is False,
            )
        ),
    )


def run_phase19b() -> SmokeReport:
    evaluator = EvaluatorSpec(
        evaluator_id="phase19b-deterministic",
        revision="1.0.0",
        kind=EvaluatorKind.DETERMINISTIC,
        implementation_sha256="1" * 64,
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
    )
    cases = (
        EvaluationCase(
            case_id="held-001",
            source_trajectory_id="held-source-001",
            partition=EvaluationPartition.HELD_OUT,
            task_family="held-task-family",
            repository_family="held-repository-family",
            trajectory_family="held-trajectory-family",
            content_sha256="2" * 64,
            evidence_refs=("fixture:held-001",),
        ),
        EvaluationCase(
            case_id="ood-001",
            source_trajectory_id="ood-source-001",
            partition=EvaluationPartition.OOD,
            task_family="ood-task-family",
            repository_family="ood-repository-family",
            trajectory_family="ood-trajectory-family",
            content_sha256="3" * 64,
            evidence_refs=("fixture:ood-001",),
        ),
    )
    suite = FrozenEvaluationSuite.freeze(
        suite_name="phase19b-heldout-ood", revision="1.0.0", evaluator=evaluator, cases=cases
    )
    regression = freeze_regression_suite(
        revision="1.0.0", evaluation_suite=suite, critical_case_ids=("held-001",)
    )
    clean_contamination = detect_benchmark_contamination(
        evaluation_suite=suite,
        training_exposures=(
            TrainingExposure(
                source_trajectory_id="train-source-001",
                task_family="train-task-family",
                repository_family="train-repository-family",
                trajectory_family="train-trajectory-family",
                content_sha256="4" * 64,
            ),
        ),
    )
    contamination_probe = detect_benchmark_contamination(
        evaluation_suite=suite,
        training_exposures=(
            TrainingExposure(
                source_trajectory_id="training-copy",
                task_family=cases[0].task_family,
                repository_family="different-repository",
                trajectory_family="different-trajectory",
                content_sha256=cases[0].content_sha256,
            ),
        ),
    )
    baseline_scores = {dimension: 0.5 for dimension in CognitiveDimension}
    baseline_cards = tuple(
        CognitiveScorecard(
            case_id=case.case_id,
            scores=dict(baseline_scores),
            evidence_refs=(f"baseline:{case.case_id}",),
        )
        for case in cases
    )
    candidate_cards = list(baseline_cards)
    planning_scores = dict(candidate_cards[0].scores)
    planning_scores[CognitiveDimension.PLANNING] = 0.7
    candidate_cards[0] = candidate_cards[0].model_copy(update={"scores": planning_scores})
    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="baseline-model",
        evaluation_suite=suite,
        scorecards=baseline_cards,
    )
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="candidate-model",
        evaluation_suite=suite,
        scorecards=tuple(candidate_cards),
    )
    comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=candidate,
        regression_suite=regression,
        contamination_report=clean_contamination,
    )
    suite_locked = suite.locked_sha256 == suite.computed_sha256()
    held_out_case_count = sum(
        case.partition is EvaluationPartition.HELD_OUT for case in suite.cases
    )
    ood_case_count = sum(case.partition is EvaluationPartition.OOD for case in suite.cases)
    regression_suite_locked = regression.locked_sha256 == regression.computed_sha256()
    evaluator_revision = evaluator.revision
    evaluator_independent = (
        evaluator.independent_from_candidate_artifacts and evaluator.independent_from_training_data
    )
    clean_contamination_detected = clean_contamination.contaminated
    contamination_probe_detected = contamination_probe.contaminated
    comparison_status = comparison.status.value
    planning_delta = comparison.dimension_deltas[CognitiveDimension.PLANNING]
    promotion_authorized = comparison.promotion_authorized
    real_benchmark_run_executed = False
    payload = {
        "suite_locked": suite_locked,
        "held_out_case_count": held_out_case_count,
        "ood_case_count": ood_case_count,
        "regression_suite_locked": regression_suite_locked,
        "evaluator_revision": evaluator_revision,
        "evaluator_independent": evaluator_independent,
        "clean_contamination_detected": clean_contamination_detected,
        "contamination_probe_detected": contamination_probe_detected,
        "comparison_status": comparison_status,
        "planning_delta": planning_delta,
        "promotion_authorized": promotion_authorized,
        "real_benchmark_run_executed": real_benchmark_run_executed,
    }
    return legacy_contract_report(
        "phase19b",
        payload,
        all(
            (
                suite_locked,
                held_out_case_count == 1,
                ood_case_count == 1,
                regression_suite_locked,
                evaluator_revision == "1.0.0",
                evaluator_independent,
                not clean_contamination_detected,
                contamination_probe_detected,
                comparison_status == ReleaseComparisonStatus.COMPARABLE.value,
                planning_delta > 0.0,
                not promotion_authorized,
                not real_benchmark_run_executed,
            )
        ),
    )


def run_phase19c() -> SmokeReport:
    evaluator = EvaluatorSpec(
        evaluator_id="phase19c-primary",
        revision="1.0.0",
        kind=EvaluatorKind.DETERMINISTIC,
        implementation_sha256="5" * 64,
        independent_from_candidate_artifacts=True,
        independent_from_training_data=True,
    )
    cases = (
        EvaluationCase(
            case_id="held-001",
            source_trajectory_id="held-source-001",
            partition=EvaluationPartition.HELD_OUT,
            task_family="held-task-family",
            repository_family="held-repository-family",
            trajectory_family="held-trajectory-family",
            content_sha256="6" * 64,
            evidence_refs=("fixture:held-001",),
        ),
        EvaluationCase(
            case_id="ood-001",
            source_trajectory_id="ood-source-001",
            partition=EvaluationPartition.OOD,
            task_family="ood-task-family",
            repository_family="ood-repository-family",
            trajectory_family="ood-trajectory-family",
            content_sha256="7" * 64,
            evidence_refs=("fixture:ood-001",),
        ),
    )
    suite = FrozenEvaluationSuite.freeze(
        suite_name="phase19c-heldout-ood", revision="1.0.0", evaluator=evaluator, cases=cases
    )
    regression = freeze_regression_suite(
        revision="1.0.0", evaluation_suite=suite, critical_case_ids=("held-001",)
    )
    clean_contamination = detect_benchmark_contamination(
        evaluation_suite=suite,
        training_exposures=(
            TrainingExposure(
                source_trajectory_id="train-source-001",
                task_family="train-task-family",
                repository_family="train-repository-family",
                trajectory_family="train-trajectory-family",
                content_sha256="8" * 64,
            ),
        ),
    )
    baseline_cards = tuple(
        CognitiveScorecard(
            case_id=case.case_id,
            scores={dimension: 0.6 for dimension in CognitiveDimension},
            evidence_refs=(f"baseline:{case.case_id}",),
        )
        for case in cases
    )
    candidate_cards = list(baseline_cards)
    degraded_scores = dict(candidate_cards[0].scores)
    degraded_scores[CognitiveDimension.EVIDENCE_USAGE] = 0.4
    candidate_cards[0] = candidate_cards[0].model_copy(update={"scores": degraded_scores})
    baseline = build_release_snapshot(
        release_id="baseline",
        candidate_model_id="baseline-model",
        evaluation_suite=suite,
        scorecards=baseline_cards,
    )
    candidate = build_release_snapshot(
        release_id="candidate",
        candidate_model_id="candidate-model",
        evaluation_suite=suite,
        scorecards=tuple(candidate_cards),
    )
    comparison = compare_release_snapshots(
        baseline=baseline,
        candidate=candidate,
        regression_suite=regression,
        contamination_report=clean_contamination,
    )
    policy = build_default_learning_integrity_policy()
    candidate_evidence = IntegrityEvidence(
        evidence_id="candidate-self",
        origin=IntegrityEvidenceOrigin.CANDIDATE_OUTPUT,
        independent_from_candidate=False,
    )
    contradiction_evidence = IntegrityEvidence(
        evidence_id="independent-contradiction",
        origin=IntegrityEvidenceOrigin.DETERMINISTIC_VERIFIER,
        independent_from_candidate=True,
    )
    report = assess_learning_integrity(
        policy=policy,
        evaluation_suite=suite,
        release_comparison=comparison,
        generalization_profiles=(
            GeneralizationProfile(
                profile_id="generalization-risk",
                training_score=0.95,
                validation_score=0.88,
                held_out_score=0.6,
                ood_score=0.5,
                evidence_refs=("eval:generalization",),
            ),
        ),
        shortcut_probes=(
            ShortcutSliceProbe(
                probe_id="shortcut-risk",
                shortcut_present_score=0.9,
                shortcut_absent_score=0.5,
                evidence_refs=("eval:shortcut",),
            ),
        ),
        evaluator_agreement_probes=(
            EvaluatorAgreementProbe(
                probe_id="evaluator-risk",
                primary_evaluator_fingerprint=suite.evaluator.fingerprint(),
                independent_evaluator_fingerprint="9" * 64,
                primary_score=0.9,
                independent_score=0.55,
                independent_evaluator_verified=True,
                evidence_refs=("eval:evaluator-agreement",),
            ),
        ),
        learning_exposure=LearningExposureRecord(
            benchmark_case_ids=("held-001",),
            evaluator_fingerprints=(suite.evaluator.fingerprint(),),
            optimization_metric_ids=("training-objective",),
            evidence_refs=("lineage:learning-config",),
        ),
        proxy_metrics=(
            ProxyMetricOutcome(
                metric_id="training-objective",
                baseline_value=0.5,
                candidate_value=0.8,
                evidence_refs=("metric:training-objective",),
            ),
        ),
        evidence_catalog=(candidate_evidence, contradiction_evidence),
        claim_reviews=(
            ClaimEvidenceReview(
                claim_id="candidate-improved",
                supporting_evidence_ids=(candidate_evidence.evidence_id,),
                contradicting_evidence_ids=(contradiction_evidence.evidence_id,),
                considered_evidence_ids=(candidate_evidence.evidence_id,),
            ),
        ),
    )
    risks = report.risk_set
    payload = {
        "policy_locked": policy.locked_sha256 == policy.computed_sha256(),
        "shortcut_learning_detected": LearningIntegrityRisk.SHORTCUT_LEARNING in risks,
        "benchmark_gaming_detected": LearningIntegrityRisk.BENCHMARK_GAMING in risks,
        "evaluator_gaming_detected": LearningIntegrityRisk.EVALUATOR_GAMING in risks,
        "proxy_specification_optimization_detected": (
            LearningIntegrityRisk.PROXY_SPECIFICATION_OPTIMIZATION in risks
        ),
        "confirmation_bias_detected": LearningIntegrityRisk.CONFIRMATION_BIAS in risks,
        "overfitting_detected": LearningIntegrityRisk.OVERFITTING in risks,
        "self_confirmation_detected": LearningIntegrityRisk.SELF_CONFIRMATION in risks,
        "integrity_status": report.status.value,
        "promotion_authorized": report.promotion_authorized,
        "counterfactual_replay_executed": False,
        "real_training_run_executed": False,
    }
    return legacy_contract_report(
        "phase19c",
        payload,
        all(
            (
                payload["policy_locked"] is True,
                payload["shortcut_learning_detected"] is True,
                payload["benchmark_gaming_detected"] is True,
                payload["evaluator_gaming_detected"] is True,
                payload["proxy_specification_optimization_detected"] is True,
                payload["confirmation_bias_detected"] is True,
                payload["overfitting_detected"] is True,
                payload["self_confirmation_detected"] is True,
                payload["integrity_status"] == LearningIntegrityStatus.REJECT_CANDIDATE.value,
                payload["promotion_authorized"] is False,
                payload["counterfactual_replay_executed"] is False,
                payload["real_training_run_executed"] is False,
            )
        ),
    )


def run_phase19d() -> SmokeReport:
    policy = build_default_counterfactual_policy()
    baseline_evidence = CounterfactualEvidence(
        evidence_id="baseline-replay",
        origin=CounterfactualEvidenceOrigin.SANDBOX_HARNESS,
        independent_from_candidate=True,
        source_ref="sandbox:baseline-replay",
    )
    alternative_evidence = CounterfactualEvidence(
        evidence_id="alternative-replay",
        origin=CounterfactualEvidenceOrigin.SANDBOX_HARNESS,
        independent_from_candidate=True,
        source_ref="sandbox:alternative-replay",
    )
    candidate = CounterfactualCandidate(
        candidate_id="phase19d-alt",
        source_case_id="case-001",
        source_revision="rev-001",
        alternative_kind=CounterfactualAlternativeKind.MINIMAL_PATH,
        baseline_decision_ref="decision:baseline",
        alternative_summary="Use a shorter verified path in the same sandbox fixture.",
        changed_basis=("sandbox observation", "minimal action path"),
        hypothesis_refs=("trace:phase19d-decision",),
    )
    baseline = ReplayObservation(
        observation_id="baseline",
        case_id="case-001",
        source_revision="rev-001",
        decision_ref="decision:baseline",
        environment=ReplayEnvironment.SANDBOX,
        scorecard=CognitiveScorecard(
            case_id="case-001",
            scores={dimension: 0.6 for dimension in CognitiveDimension},
            evidence_refs=("score:baseline",),
        ),
        task_success=True,
        verification_success=True,
        action_count=4,
        unnecessary_action_count=1,
        cost_units=4.0,
        critical_safety_regressions=0,
        evidence_ids=(baseline_evidence.evidence_id,),
    )
    alternative = ReplayObservation(
        observation_id="alternative",
        case_id="case-001",
        source_revision="rev-001",
        decision_ref="decision:alternative",
        environment=ReplayEnvironment.SANDBOX,
        scorecard=CognitiveScorecard(
            case_id="case-001",
            scores={dimension: 0.7 for dimension in CognitiveDimension},
            evidence_refs=("score:alternative",),
        ),
        task_success=True,
        verification_success=True,
        action_count=3,
        unnecessary_action_count=0,
        cost_units=3.0,
        critical_safety_regressions=0,
        evidence_ids=(alternative_evidence.evidence_id,),
    )
    executed = assess_counterfactual(
        policy=policy,
        experiment=CounterfactualExperiment(
            experiment_id="phase19d-executed",
            candidate=candidate,
            baseline=baseline,
            alternative=alternative,
            evidence_catalog=(baseline_evidence, alternative_evidence),
        ),
    )
    hypothesis = assess_counterfactual(
        policy=policy,
        experiment=CounterfactualExperiment(
            experiment_id="phase19d-hypothesis",
            candidate=candidate,
            baseline=baseline,
            alternative=None,
            evidence_catalog=(baseline_evidence,),
        ),
    )
    payload = {
        "policy_locked": policy.locked_sha256 == policy.computed_sha256(),
        "executed_disposition": executed.disposition.value,
        "executed_counterfactual_evidence": executed.executed_counterfactual_evidence,
        "hypothesis_disposition": hypothesis.disposition.value,
        "hypothesis_has_replay_evidence": hypothesis.executed_counterfactual_evidence,
        "action_count_delta": executed.action_count_delta,
        "cost_delta": executed.cost_delta,
        "generalized_causal_claim_authorized": executed.generalized_causal_claim_authorized,
        "promotion_authorized": executed.promotion_authorized,
        "real_training_run_executed": False,
    }
    return legacy_contract_report(
        "phase19d",
        payload,
        all(
            (
                payload["policy_locked"] is True,
                payload["executed_disposition"]
                == CounterfactualDisposition.EVIDENCE_SUPPORTED.value,
                payload["executed_counterfactual_evidence"] is True,
                payload["hypothesis_disposition"]
                == CounterfactualDisposition.HYPOTHESIS_ONLY.value,
                payload["hypothesis_has_replay_evidence"] is False,
                payload["action_count_delta"] == -1,
                payload["cost_delta"] == -1.0,
                payload["generalized_causal_claim_authorized"] is False,
                payload["promotion_authorized"] is False,
                payload["real_training_run_executed"] is False,
            )
        ),
    )


def run_phase19e() -> SmokeReport:
    policy = build_default_sft_policy()
    with TemporaryDirectory(prefix="luna-phase19e-smoke-") as temp:
        corpus_path = Path(temp) / "train.jsonl"

        def record(*, suffix: str, task: str) -> dict[str, object]:
            messages: list[dict[str, object]] = [
                {"role": "system", "content": "Luna controlled SFT smoke."},
                {"role": "user", "content": f"Verify {task}."},
                {
                    "role": "assistant",
                    "content": "Inspect the observable contract before changing state.",
                },
            ]
            return {
                "record_id": f"{task}:{suffix}::step-1",
                "source_trajectory_id": f"{task}:{suffix}",
                "task": task,
                "canonical_family": task,
                "lang": "python",
                "category": "debug-runtime",
                "assistant_step": 1,
                "assistant_steps": 1,
                "messages": messages,
                "tools": [],
                "target_message_index": 2,
                "loss_mask": [0, 0, 1],
                "_luna_training": {
                    "split": "train",
                    "train_role": "policy",
                    "trajectory_weight": 1.0,
                    "step_weight": 1.0,
                    "loss_weight": 1.0,
                    "d1_decision": "train_candidate",
                    "d1_decision_reasons": [],
                    "tool_schema": "luna-canonical-tools-v0.1",
                    "normalization": "privacy-and-context-v0.1",
                    "source_derivation": "cumulative-next-assistant-v1",
                },
            }

        rows = (
            record(suffix="source-a", task="phase19e-smoke-a"),
            record(suffix="source-b", task="phase19e-smoke-b"),
        )
        corpus_path.write_text(
            "".join(
                json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n" for row in rows
            ),
            encoding="utf-8",
            newline="\n",
        )
        audit = audit_sft_corpus(path=corpus_path, policy=policy)
        spec = prepare_sft_candidate(
            policy=policy,
            audit=audit,
            candidate_id="luna-phase19e-smoke-candidate",
            base_model_id="fixture/base-model",
            base_model_revision="fixture-base-rev",
            trainer_id="external-controlled-sft",
            trainer_revision="fixture-trainer-rev",
            seed=19,
            epochs=1.0,
            learning_rate=2e-05,
            max_sequence_tokens=4096,
        )
    payload = {
        "policy_locked": policy.locked_sha256 == policy.computed_sha256(),
        "corpus_ready": audit.ready_for_controlled_sft,
        "record_count": audit.record_count,
        "target_only_loss": audit.target_only_loss_verified,
        "train_split_only": audit.train_split_only,
        "canonical_tool_schema": audit.canonical_tool_schema_only,
        "canonical_normalization": audit.canonical_normalization_only,
        "source_derivation_present": audit.source_derivation_present,
        "raw_hidden_chain_of_thought_absent": audit.raw_hidden_chain_of_thought_absent,
        "candidate_spec_locked": spec.locked_sha256 == spec.computed_sha256(),
        "held_out_used_for_training": spec.held_out_used_for_training,
        "real_training_run_executed": False,
        "trained_artifact_registered": False,
        "promotion_authorized": spec.promotion_authority,
        "runtime_authority": spec.runtime_authority,
    }
    return legacy_contract_report(
        "phase19e",
        payload,
        all(
            (
                payload["policy_locked"] is True,
                payload["corpus_ready"] is True,
                payload["record_count"] == 2,
                payload["target_only_loss"] is True,
                payload["train_split_only"] is True,
                payload["canonical_tool_schema"] is True,
                payload["canonical_normalization"] is True,
                payload["source_derivation_present"] is True,
                payload["raw_hidden_chain_of_thought_absent"] is True,
                payload["candidate_spec_locked"] is True,
                payload["held_out_used_for_training"] is False,
                payload["real_training_run_executed"] is False,
                payload["trained_artifact_registered"] is False,
                payload["promotion_authorized"] is False,
                payload["runtime_authority"] is False,
            )
        ),
    )


def run_phase19f() -> SmokeReport:
    policy = build_default_improvement_gate_policy()
    report = evaluate_improvement_gate(policy=policy)
    payload: dict[str, object] = {
        "policy_locked": policy.locked_sha256 == policy.computed_sha256(),
        "confidence_level": policy.confidence_level,
        "critical_regression_zero_tolerance": policy.critical_regression_zero_tolerance,
        "decision": report.decision.value,
        "candidate_evidence_verified": report.candidate_evidence_verified,
        "meaningful_thresholds_frozen": set(policy.dimension_thresholds) == set(CognitiveDimension),
        "runtime_authority": report.runtime_authority,
        "action_executed": report.action_executed,
        "real_training_run_executed": False,
        "real_candidate_evaluation_executed": False,
    }
    return legacy_contract_report(
        "phase19f",
        payload,
        all(
            (
                payload["policy_locked"] is True,
                payload["confidence_level"] == 0.95,
                payload["critical_regression_zero_tolerance"] is True,
                payload["decision"] == ImprovementGateDecision.INSUFFICIENT_EVIDENCE.value,
                payload["candidate_evidence_verified"] is False,
                payload["meaningful_thresholds_frozen"] is True,
                payload["runtime_authority"] is False,
                payload["action_executed"] is False,
                payload["real_training_run_executed"] is False,
                payload["real_candidate_evaluation_executed"] is False,
            )
        ),
    )
