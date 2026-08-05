from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.contracts import (
    ExpectedObservation,
    Observation,
    ObservationStatus,
    PlanStep,
    PlanStepStatus,
    TestSummary,
)


def test_high_impact_expectation_requires_status() -> None:
    with pytest.raises(ValidationError, match="expected_status"):
        ExpectedObservation(
            summary="A file will change",
            failure_signals=("Protected path changed",),
            verification_method="Compare file hashes",
            high_impact=True,
        )


def test_failed_plan_step_requires_reason() -> None:
    with pytest.raises(ValidationError, match="status_reason"):
        PlanStep(
            sequence=1,
            description="Run validation",
            status=PlanStepStatus.FAILED,
        )


def test_success_observation_rejects_failed_tests() -> None:
    with pytest.raises(ValidationError, match="failed test"):
        Observation(
            trace_id=uuid4(),
            status=ObservationStatus.SUCCESS,
            exit_code=0,
            tests=TestSummary(passed=3, failed=1),
        )


def test_failure_observation_requires_signal() -> None:
    with pytest.raises(ValidationError, match="failure signal"):
        Observation(
            trace_id=uuid4(),
            status=ObservationStatus.FAILURE,
        )


def test_valid_observation_round_trip() -> None:
    observation = Observation(
        trace_id=uuid4(),
        status=ObservationStatus.SUCCESS,
        exit_code=0,
        tests=TestSummary(passed=8),
        stdout_ref="logs/task/stdout.log",
    )
    assert Observation.from_json(observation.to_json()) == observation
