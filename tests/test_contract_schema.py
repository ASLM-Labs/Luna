from __future__ import annotations

import json

from luna.contracts import (
    Checkpoint,
    Evidence,
    ExpectedObservation,
    Observation,
    PlanStep,
    TaskContract,
    TaskState,
)


def test_all_core_contracts_generate_json_schema() -> None:
    models = (
        TaskContract,
        TaskState,
        PlanStep,
        ExpectedObservation,
        Observation,
        Evidence,
        Checkpoint,
    )
    for model in models:
        schema = model.model_json_schema()
        assert schema["title"]
        json.dumps(schema)
