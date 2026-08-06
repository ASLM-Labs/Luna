"""Structural and behavioral verifier for Luna Phase 6."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from luna.audit import (
    AuditEventKind,
    AuditSession,
    AuditedToolDispatcher,
    EvidenceBuilder,
)
from luna.contracts import RiskLevel, TaskContract, TaskScope
from luna.tools import AutonomyLevel, ToolPolicy, ToolRequest, build_phase4_registry

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required_files = [
        ROOT / "src" / "luna" / "audit" / "ledger.py",
        ROOT / "src" / "luna" / "audit" / "store.py",
        ROOT / "src" / "luna" / "audit" / "redaction.py",
        ROOT / "src" / "luna" / "audit" / "evidence.py",
        ROOT / "src" / "luna" / "audit" / "dispatcher.py",
    ]
    missing = [path.relative_to(ROOT).as_posix() for path in required_files if not path.is_file()]
    secret = "phase6-verifier-secret"

    with TemporaryDirectory(prefix="luna-phase6-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        contract = TaskContract(
            task_id=task_id,
            objective="Verify append-only redacted audit behavior.",
            required_conditions=("Echo output must be captured without secrets.",),
            evidence_required=("Observation and Evidence",),
            scope=TaskScope(workspace_root=str(root)),
            risk_level=RiskLevel.LOW,
            owner="user",
        )
        audit = AuditSession(root / "audit", explicit_secrets=(secret,))
        audit.record_task_contract(contract=contract, trace_id=trace_id)
        outcome = AuditedToolDispatcher(build_phase4_registry(), audit).dispatch(
            request=ToolRequest(
                task_id=task_id,
                trace_id=trace_id,
                tool_name="core.echo",
                arguments={"message": f"token={secret}"},
                max_output_chars=8,
            ),
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=("core.echo",),
                autonomy_level=AutonomyLevel.OBSERVE_ONLY,
                max_risk=RiskLevel.LOW,
                max_output_chars=8,
            ),
        )
        evidence = EvidenceBuilder.from_observation(
            task_id=task_id,
            requirement_id="echo-observed",
            observation=outcome.observation,
            environment_fingerprint="phase6-verifier",
            revision="phase6",
            freshness_seconds=0,
            reproducible=True,
            confidence=1.0,
        )
        audit.record_evidence(
            evidence=evidence,
            trace_id=trace_id,
            observation_id=outcome.observation.observation_id,
        )
        events = audit.events_for_task(task_id)
        verification = audit.verify_integrity()
        persisted = audit.ledger.path.read_text(encoding="utf-8")
        full_output = audit.logs.read_text(outcome.observation.stdout_ref or "")

        checks = {
            "required_files_present": not missing,
            "append_only_chain_valid": verification.valid,
            "expected_event_count": verification.event_count == 6,
            "common_trace_id": all(event.trace_id == trace_id for event in events),
            "tool_and_evidence_events_present": {
                AuditEventKind.TOOL_REQUEST,
                AuditEventKind.TOOL_RESULT,
                AuditEventKind.TOOL_EVENT,
                AuditEventKind.OBSERVATION,
                AuditEventKind.EVIDENCE,
            }.issubset({event.kind for event in events}),
            "secret_absent_from_jsonl": secret not in persisted,
            "secret_absent_from_log_artifact": secret not in full_output,
            "full_output_hash_reference_readable": bool(full_output),
            "completion_verifier_still_disabled": not (
                ROOT / "src" / "luna" / "verification"
            ).exists(),
        }
        status = "PASS" if all(checks.values()) else "BLOCKED"
        result = {
            "phase": 6,
            "checks": checks,
            "missing_files": missing,
            "event_count": verification.event_count,
            "status": status,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
