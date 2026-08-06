"""Expected-observation comparison."""

from __future__ import annotations

from luna.contracts.observation import Observation
from luna.contracts.plan import ExpectedObservation
from luna.planning.models import ExpectationAssessment


class ExpectationEvaluator:
    """Compare structured observation fields without model judgment."""

    def assess(
        self,
        expectation: ExpectedObservation,
        observation: Observation,
    ) -> ExpectationAssessment:
        mismatches: list[str] = []

        if (
            expectation.expected_status is not None
            and observation.status is not expectation.expected_status
        ):
            mismatches.append(
                "status:expected="
                f"{expectation.expected_status.value},actual={observation.status.value}"
            )

        if (
            expectation.expected_exit_codes
            and observation.exit_code not in expectation.expected_exit_codes
        ):
            mismatches.append(
                f"exit_code:expected={expectation.expected_exit_codes},"
                f"actual={observation.exit_code}"
            )

        changed_paths = set(observation.changed_files)
        missing_paths = [
            path
            for path in expectation.expected_changed_paths
            if path not in changed_paths
        ]
        if missing_paths:
            mismatches.append("missing_changed_paths:" + ",".join(missing_paths))

        observed_errors = "\n".join(observation.errors).casefold()
        matched_failure_signals = [
            signal
            for signal in expectation.failure_signals
            if signal.casefold() in observed_errors
        ]
        if matched_failure_signals:
            mismatches.append(
                "failure_signals:" + ",".join(matched_failure_signals)
            )

        return ExpectationAssessment(
            expectation_id=expectation.expectation_id,
            observation_id=observation.observation_id,
            matched=not mismatches,
            mismatches=tuple(mismatches),
        )
