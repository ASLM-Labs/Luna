from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from luna.audit import AuditEventKind, AuditSession, EvidenceBuilder
from luna.contracts import Observation, ObservationStatus, TestSummary
from luna.contracts.enums import EvidenceResult, EvidenceSourceKind


def test_observation_builds_current_traceable_test_evidence(tmp_path: Path) -> None:
    task_id = uuid4()
    trace_id = uuid4()
    observation = Observation(
        trace_id=trace_id,
        status=ObservationStatus.SUCCESS,
        exit_code=0,
        tests=TestSummary(passed=12),
        stdout_ref="sha256:" + "a" * 64,
        stderr_ref="sha256:" + "b" * 64,
    )
    evidence = EvidenceBuilder.from_observation(
        task_id=task_id,
        requirement_id="tests-pass",
        observation=observation,
        environment_fingerprint="windows-python312",
        revision="abc123",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )
    session = AuditSession(tmp_path / "audit")
    event = session.record_evidence(
        evidence=evidence,
        trace_id=trace_id,
        observation_id=observation.observation_id,
    )

    assert evidence.result is EvidenceResult.PASS
    assert evidence.source_kind is EvidenceSourceKind.TEST_RESULT
    assert event.kind is AuditEventKind.EVIDENCE
    assert event.task_id == task_id
    assert event.trace_id == trace_id
    assert event.payload["observation_id"] == str(observation.observation_id)


def test_failed_observation_never_becomes_pass_evidence() -> None:
    observation = Observation(
        trace_id=uuid4(),
        status=ObservationStatus.FAILURE,
        exit_code=1,
        errors=("test failed",),
    )
    evidence = EvidenceBuilder.from_observation(
        task_id=uuid4(),
        requirement_id="tests-pass",
        observation=observation,
        environment_fingerprint="windows-python312",
        revision="abc123",
        freshness_seconds=0,
        reproducible=True,
        confidence=1.0,
    )

    assert evidence.result is EvidenceResult.FAIL
