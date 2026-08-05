"""Verify the eight Luna Phase 1 core contracts and JSON schemas."""

from __future__ import annotations

import json

from luna.contracts import (
    Checkpoint,
    CompletionStatus,
    Evidence,
    ExpectedObservation,
    Observation,
    PlanStep,
    TaskContract,
    TaskState,
)


def main() -> int:
    contracts = (
        TaskContract,
        TaskState,
        PlanStep,
        ExpectedObservation,
        Observation,
        Evidence,
        Checkpoint,
        CompletionStatus,
    )
    schemas = {
        contract.__name__: contract.model_json_schema()
        for contract in contracts
        if hasattr(contract, "model_json_schema")
    }
    result = {
        "phase": 1,
        "core_contract_count": len(contracts),
        "pydantic_schema_count": len(schemas),
        "contracts": [contract.__name__ for contract in contracts],
        "status": "PASS" if len(contracts) == 8 and len(schemas) == 7 else "BLOCKED",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
