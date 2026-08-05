from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.contracts import (
    Checkpoint,
    Evidence,
    EvidenceResult,
    EvidenceSourceKind,
    TaskPhase,
)


def test_model_inference_cannot_be_pass_evidence() -> None:
    with pytest.raises(ValidationError, match="cannot be PASS"):
        Evidence(
            task_id=uuid4(),
            requirement_id="REQ-1",
            source_kind=EvidenceSourceKind.MODEL_INFERENCE,
            source_ref="model-output:12",
            result=EvidenceResult.PASS,
            environment_fingerprint="env-1",
            reproducible=False,
            confidence=0.4,
        )


def test_checkpoint_rejects_step_overlap() -> None:
    step_id = uuid4()
    with pytest.raises(ValidationError, match="both completed and open"):
        Checkpoint(
            task_id=uuid4(),
            workspace_fingerprint="workspace-sha",
            environment_fingerprint="environment-sha",
            last_verified_phase=TaskPhase.ACTING,
            completed_step_ids=(step_id,),
            open_step_ids=(step_id,),
            next_step="Continue",
        )


def test_non_closed_checkpoint_requires_next_step() -> None:
    with pytest.raises(ValidationError, match="requires next_step"):
        Checkpoint(
            task_id=uuid4(),
            workspace_fingerprint="workspace-sha",
            environment_fingerprint="environment-sha",
            last_verified_phase=TaskPhase.VERIFYING,
        )
