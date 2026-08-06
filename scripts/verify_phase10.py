"""Structural and behavioral verifier for Luna Phase 10."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from pydantic import ValidationError

from luna.audit import AuditEventKind, AuditSession
from luna.autonomy import AutonomyLevel, AutonomyPolicy, FreeResearchContract
from luna.contracts import (
    Evidence,
    EvidenceResult,
    EvidenceSourceKind,
    RiskLevel,
    TaskContract,
    TaskScope,
)
from luna.identity import IdentityProfile
from luna.reporting import FinalReportComposer
from luna.tools import (
    ToolArgumentRule,
    ToolArgumentType,
    ToolCapability,
    ToolDispatcher,
    ToolExecutionContext,
    ToolExecutionOutput,
    ToolOrigin,
    ToolPolicy,
    ToolRegistry,
    ToolRequest,
    ToolSpec,
)
from luna.tools.policy import evaluate_tool_policy
from luna.verification import CompletionGate, VerificationPolicy, required_condition_claim_id

ROOT = Path(__file__).resolve().parents[1]


class _NetworkFixture:
    def execute(
        self,
        arguments: dict[str, str | int | float | bool | list[str] | None],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments, context
        return ToolExecutionOutput(stdout="ok")


def _tool_spec(
    name: str,
    capability: ToolCapability | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Phase 10 verifier fixture.",
        capabilities=() if capability is None else (capability,),
        argument_schema={
            "url": ToolArgumentRule(
                argument_type=ToolArgumentType.STRING,
                required=True,
            )
        }
        if capability is ToolCapability.NETWORK
        else {},
    )


def main() -> int:
    required_files = [
        ROOT / "src" / "luna" / "identity" / "models.py",
        ROOT / "src" / "luna" / "autonomy" / "models.py",
        ROOT / "src" / "luna" / "reporting" / "models.py",
        ROOT / "src" / "luna" / "reporting" / "composer.py",
        ROOT / "tests" / "test_phase10_identity.py",
        ROOT / "tests" / "test_phase10_autonomy.py",
        ROOT / "tests" / "test_phase10_reporting.py",
    ]
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in required_files
        if not path.is_file()
    ]

    with TemporaryDirectory(prefix="luna-phase10-") as directory:
        root = Path(directory)
        task_id = uuid4()
        trace_id = uuid4()
        required = "Phase 10 final report is evidence-bound."
        contract = TaskContract(
            task_id=task_id,
            objective="Verify Phase 10 identity, reporting, and autonomy.",
            required_conditions=(required,),
            evidence_required=("test result",),
            scope=TaskScope(workspace_root=str(root)),
            risk_level=RiskLevel.LOW,
            owner="user",
        )
        audit = AuditSession(root / "audit")
        audit.record_task_contract(contract=contract, trace_id=trace_id)
        gate = CompletionGate(audit).evaluate(
            contract=contract,
            evidence=(
                Evidence(
                    task_id=task_id,
                    requirement_id=required_condition_claim_id(required),
                    source_kind=EvidenceSourceKind.TEST_RESULT,
                    source_ref="phase10-verifier:test",
                    result=EvidenceResult.PASS,
                    environment_fingerprint="phase10-verifier",
                    revision="phase10",
                    freshness_seconds=0,
                    reproducible=True,
                    confidence=1.0,
                ),
            ),
            policy=VerificationPolicy(
                current_revision="phase10",
                expected_environment_fingerprint="phase10-verifier",
            ),
            trace_id=trace_id,
        )
        identity = IdentityProfile()
        final_report = FinalReportComposer(audit).compose(
            contract=contract,
            gate_result=gate,
            identity=identity,
            performed=("Executed the Phase 10 verifier.",),
            changed=("src/luna/identity", "src/luna/reporting", "src/luna/autonomy"),
            trace_id=trace_id,
        )

        no_effect_spec = _tool_spec("fixture.echo")
        model_request = ToolRequest(
            task_id=task_id,
            trace_id=trace_id,
            tool_name=no_effect_spec.name,
            origin=ToolOrigin.MODEL,
        )
        level_zero = evaluate_tool_policy(
            spec=no_effect_spec,
            request=model_request,
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=(no_effect_spec.name,),
                autonomy_level=AutonomyLevel.LEVEL_0_ADVISORY,
            ),
        )
        level_one = evaluate_tool_policy(
            spec=no_effect_spec,
            request=model_request,
            task_contract=contract,
            policy=ToolPolicy(
                allowed_tools=(no_effect_spec.name,),
                autonomy_level=AutonomyLevel.LEVEL_1_READ_ONLY,
            ),
        )

        now = datetime.now(UTC)
        research_task_id = uuid4()
        research_spec = _tool_spec("research.fetch", ToolCapability.NETWORK)
        research_task = TaskContract(
            task_id=research_task_id,
            objective="Verify bounded FREE_RESEARCH.",
            required_conditions=("Only approved domains are allowed.",),
            evidence_required=("policy decision",),
            scope=TaskScope(workspace_root=str(root), network_allowed=True),
            risk_level=RiskLevel.LOW,
            owner="user",
        )
        free_research = FreeResearchContract(
            task_id=research_task_id,
            purpose="Inspect approved documentation.",
            allowed_tools=(research_spec.name,),
            allowed_domains=("example.com",),
            issued_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=5),
        )
        research_policy = ToolPolicy(
            allowed_tools=(research_spec.name,),
            autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH,
            free_research_contract=free_research,
        )
        allowed_research = evaluate_tool_policy(
            spec=research_spec,
            request=ToolRequest(
                task_id=research_task_id,
                trace_id=uuid4(),
                tool_name=research_spec.name,
                arguments={"url": "https://docs.example.com/reference"},
                expectation_id=uuid4(),
                requested_at=now,
            ),
            task_contract=research_task,
            policy=research_policy,
        )
        blocked_domain = evaluate_tool_policy(
            spec=research_spec,
            request=ToolRequest(
                task_id=research_task_id,
                trace_id=uuid4(),
                tool_name=research_spec.name,
                arguments={"url": "https://outside.test/reference"},
                expectation_id=uuid4(),
                requested_at=now,
            ),
            task_contract=research_task,
            policy=research_policy,
        )

        expired_contract = FreeResearchContract(
            task_id=research_task_id,
            purpose="Verify runtime-owned clock.",
            allowed_tools=(research_spec.name,),
            allowed_domains=("example.com",),
            issued_at=now - timedelta(minutes=10),
            expires_at=now - timedelta(minutes=5),
        )
        forged_timestamp = evaluate_tool_policy(
            spec=research_spec,
            request=ToolRequest(
                task_id=research_task_id,
                trace_id=uuid4(),
                tool_name=research_spec.name,
                arguments={"url": "https://example.com/reference"},
                expectation_id=uuid4(),
                requested_at=now - timedelta(minutes=9),
            ),
            task_contract=research_task,
            policy=ToolPolicy(
                allowed_tools=(research_spec.name,),
                autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH,
                free_research_contract=expired_contract,
            ),
            now=now,
        )

        budget_contract = FreeResearchContract(
            task_id=research_task_id,
            purpose="Verify runtime request accounting.",
            allowed_tools=(research_spec.name,),
            allowed_domains=("example.com",),
            max_requests=1,
            issued_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=5),
        )
        registry = ToolRegistry()
        registry.register(research_spec, _NetworkFixture())
        dispatcher = ToolDispatcher(registry)
        budget_policy = ToolPolicy(
            allowed_tools=(research_spec.name,),
            autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH,
            free_research_contract=budget_contract,
        )
        first_budget_call = dispatcher.dispatch(
            request=ToolRequest(
                task_id=research_task_id,
                trace_id=uuid4(),
                tool_name=research_spec.name,
                arguments={"url": "https://example.com/one"},
                expectation_id=uuid4(),
            ),
            task_contract=research_task,
            policy=budget_policy,
        )
        second_budget_call = dispatcher.dispatch(
            request=ToolRequest(
                task_id=research_task_id,
                trace_id=uuid4(),
                tool_name=research_spec.name,
                arguments={"url": "https://example.com/two"},
                expectation_id=uuid4(),
            ),
            task_contract=research_task,
            policy=budget_policy,
        )

        model_grant_rejected = False
        try:
            AutonomyPolicy(
                task_id=task_id,
                level=AutonomyLevel.LEVEL_0_ADVISORY,
                grant_source="MODEL",
            )
        except ValidationError:
            model_grant_rejected = True

        level_four_without_contract_rejected = False
        try:
            ToolPolicy(autonomy_level=AutonomyLevel.LEVEL_4_FREE_RESEARCH)
        except ValidationError:
            level_four_without_contract_rejected = True

        event_kinds = {event.kind for event in audit.events_for_task(task_id)}
        rendered = final_report.render_text()
        audit_integrity = audit.verify_integrity().valid

    checks = {
        "required_files_present": not missing,
        "single_identity_versioned": (
            identity.identity_name == "Luna"
            and identity.identity_version == "0.1.0"
            and identity.single_active_identity
        ),
        "hard_coded_user_absent": identity.user_profile is None,
        "communication_principles_locked": all(
            (
                identity.principles.natural,
                identity.principles.warm,
                identity.principles.clear,
                identity.principles.honest,
                identity.principles.avoid_consciousness_claims,
                identity.principles.avoid_false_certainty,
            )
        ),
        "autonomy_levels_zero_to_four": [item.number for item in AutonomyLevel]
        == [0, 1, 2, 3, 4],
        "model_cannot_grant_authority": model_grant_rejected,
        "level_zero_runtime_blocked": not level_zero.allowed,
        "level_one_runtime_allowed": level_one.allowed,
        "level_four_requires_contract": level_four_without_contract_rejected,
        "free_research_domain_allowed": allowed_research.allowed,
        "free_research_outside_domain_blocked": not blocked_domain.allowed,
        "runtime_clock_cannot_be_forged": not forged_timestamp.allowed,
        "free_research_budget_consumed": (
            first_budget_call.result.status.value == "SUCCESS"
            and second_budget_call.result.status.value == "BLOCKED"
        ),
        "final_report_matches_gate": (
            final_report.completion_status is gate.decision.status
            and final_report.verification_report_id == gate.report.report_id
            and final_report.completion_decision_id == gate.decision.decision_id
        ),
        "final_report_sections_separated": all(
            section in rendered
            for section in (
                "## Yapılan",
                "## Değişen",
                "## Doğrulanan",
                "## Doğrulanamayan",
                "## Risk",
                "## Kanıt",
            )
        ),
        "final_report_audited": AuditEventKind.FINAL_REPORT in event_kinds,
        "audit_integrity_valid": audit_integrity,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    print(
        json.dumps(
            {
                "phase": 10,
                "checks": checks,
                "missing_files": missing,
                "status": status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
