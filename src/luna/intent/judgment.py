"""C4 intent reconstruction, constraint reconciliation, and trade-off judgment."""

from __future__ import annotations

import re
import unicodedata
from hashlib import sha256
from uuid import UUID

from luna.context import ContextClaimType
from luna.contracts.decision import AssumptionStatus
from luna.contracts.enums import RiskLevel
from luna.contracts.specification import (
    ConstraintConflict,
    ConstraintKind,
    ConstraintStrength,
    IntentConstraintJudgment,
    SpecificationConstraint,
    SpecificationControlAction,
)
from luna.contracts.state import TaskState
from luna.contracts.task import TaskContract, TaskScope
from luna.decision_state import DecisionStateService
from luna.intent.models import IntentResolution
from luna.intent.resolver import DeterministicIntentResolver
from luna.tasking.models import TaskContractDraft

_SPACE_RE = re.compile(r"\s+")
_CONTEXT_BASIS_CLAIM_TYPES = {
    ContextClaimType.CONTINUITY_STATE.value,
    ContextClaimType.CURRENT_STATE.value,
    ContextClaimType.EXECUTION_STATE.value,
    ContextClaimType.PROJECT_POLICY.value,
    ContextClaimType.REPOSITORY_STATE.value,
    ContextClaimType.USER_INTENT.value,
}
_SOLUTION_SHAPED_TERMS = (
    "baştan yaz",
    "bastan yaz",
    "convert ",
    "kullanarak",
    "migrate ",
    "refactor",
    "replace ",
    "rewrite",
    "yeniden yaz",
)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _SPACE_RE.sub(" ", normalized).strip()


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\0".join(str(part) for part in parts)
    return f"{prefix}:sha256:{sha256(payload.encode('utf-8')).hexdigest()}"


def _assumption_value(*, key: str, statement: str) -> str:
    prefix = f"{key}="
    return statement[len(prefix) :] if statement.startswith(prefix) else statement


def _bounded_outcome_objective(required: tuple[str, ...], literal: str) -> str:
    if not required:
        return literal
    joined = "; ".join(required)
    if len(joined) <= 4000:
        return joined
    selected: list[str] = []
    used = 0
    for item in required:
        extra = len(item) + (2 if selected else 0)
        if used + extra > 4000:
            break
        selected.append(item)
        used += extra
    return "; ".join(selected) if selected else required[0][:4000]


class IntentConstraintJudge:
    """Build deterministic C4 advisory state from explicit owner-controlled inputs."""

    @staticmethod
    def _constraint(
        *,
        kind: ConstraintKind,
        strength: ConstraintStrength,
        statement: str,
        source_ref: str,
        provenance_refs: tuple[str, ...] = (),
    ) -> SpecificationConstraint:
        cleaned = statement.strip()
        provenance = tuple(dict.fromkeys((source_ref, *provenance_refs)))
        return SpecificationConstraint(
            constraint_id=_stable_id(
                "constraint",
                kind.value,
                strength.value,
                cleaned,
                source_ref,
            ),
            kind=kind,
            strength=strength,
            statement=cleaned,
            source_ref=source_ref,
            provenance_refs=provenance,
        )

    def _constraints(
        self,
        *,
        required_conditions: tuple[str, ...],
        forbidden_outcomes: tuple[str, ...],
        evidence_required: tuple[str, ...],
        soft_preferences: tuple[str, ...],
        scope: TaskScope,
        risk_level: RiskLevel,
        source_prefix: str,
    ) -> tuple[SpecificationConstraint, ...]:
        constraints: list[SpecificationConstraint] = []
        for index, statement in enumerate(required_conditions):
            constraints.append(
                self._constraint(
                    kind=ConstraintKind.REQUIRED_OUTCOME,
                    strength=ConstraintStrength.HARD,
                    statement=statement,
                    source_ref=f"{source_prefix}:required_condition:{index}",
                )
            )
        for index, statement in enumerate(forbidden_outcomes):
            constraints.append(
                self._constraint(
                    kind=ConstraintKind.FORBIDDEN_OUTCOME,
                    strength=ConstraintStrength.HARD,
                    statement=statement,
                    source_ref=f"{source_prefix}:forbidden_outcome:{index}",
                )
            )
        for index, statement in enumerate(evidence_required):
            constraints.append(
                self._constraint(
                    kind=ConstraintKind.EVIDENCE_REQUIREMENT,
                    strength=ConstraintStrength.HARD,
                    statement=statement,
                    source_ref=f"{source_prefix}:evidence_requirement:{index}",
                )
            )

        authority_statements = (
            f"risk_level:{risk_level.value}",
            f"write_allowed:{str(scope.write_allowed).lower()}",
            f"network_allowed:{str(scope.network_allowed).lower()}",
            f"process_allowed:{str(scope.process_allowed).lower()}",
            *(f"allowed_path:{path}" for path in scope.allowed_paths),
            *(f"protected_path:{path}" for path in scope.protected_paths),
        )
        for index, statement in enumerate(authority_statements):
            constraints.append(
                self._constraint(
                    kind=ConstraintKind.AUTHORITY_BOUNDARY,
                    strength=ConstraintStrength.HARD,
                    statement=statement,
                    source_ref=f"{source_prefix}:scope_boundary:{index}",
                )
            )
        for index, statement in enumerate(soft_preferences):
            constraints.append(
                self._constraint(
                    kind=ConstraintKind.PREFERENCE,
                    strength=ConstraintStrength.SOFT,
                    statement=statement,
                    source_ref=f"{source_prefix}:soft_preference:{index}",
                )
            )
        return tuple(constraints)

    @staticmethod
    def _solution_shaped(raw_request: str) -> bool:
        lowered = _normalize(raw_request)
        return any(term in lowered for term in _SOLUTION_SHAPED_TERMS)

    @staticmethod
    def _conflict(
        *,
        refs: tuple[str, ...],
        hard_conflict: bool,
        reason_code: str,
    ) -> ConstraintConflict:
        ordered_refs = tuple(sorted(refs))
        return ConstraintConflict(
            conflict_id=_stable_id("conflict", reason_code, *ordered_refs),
            constraint_refs=ordered_refs,
            hard_conflict=hard_conflict,
            reason_code=reason_code,
        )

    def _reconcile(
        self,
        constraints: tuple[SpecificationConstraint, ...],
    ) -> tuple[tuple[ConstraintConflict, ...], tuple[str, ...], tuple[str, ...]]:
        required = {
            _normalize(item.statement): item
            for item in constraints
            if item.kind is ConstraintKind.REQUIRED_OUTCOME
        }
        forbidden = {
            _normalize(item.statement): item
            for item in constraints
            if item.kind is ConstraintKind.FORBIDDEN_OUTCOME
        }
        preferences = tuple(
            item for item in constraints if item.kind is ConstraintKind.PREFERENCE
        )
        boundaries = {
            _normalize(item.statement): item
            for item in constraints
            if item.kind is ConstraintKind.AUTHORITY_BOUNDARY
        }
        project_policies = {
            _normalize(item.statement): item
            for item in constraints
            if item.kind is ConstraintKind.PROJECT_POLICY
        }

        conflicts: list[ConstraintConflict] = []
        traded: list[str] = []
        for statement in sorted(set(required) & set(forbidden)):
            conflicts.append(
                self._conflict(
                    refs=(
                        required[statement].constraint_id,
                        forbidden[statement].constraint_id,
                    ),
                    hard_conflict=True,
                    reason_code="required_outcome_is_forbidden",
                )
            )

        policy_expansions = {
            "write_allowed:true": "write_allowed:false",
            "network_allowed:true": "network_allowed:false",
            "process_allowed:true": "process_allowed:false",
        }
        for policy_statement, boundary_statement in policy_expansions.items():
            if policy_statement in project_policies and boundary_statement in boundaries:
                conflicts.append(
                    self._conflict(
                        refs=(
                            project_policies[policy_statement].constraint_id,
                            boundaries[boundary_statement].constraint_id,
                        ),
                        hard_conflict=True,
                        reason_code="project_policy_cannot_widen_authority_boundary",
                    )
                )

        for preference in preferences:
            normalized = _normalize(preference.statement)
            if normalized in forbidden:
                conflicts.append(
                    self._conflict(
                        refs=(preference.constraint_id, forbidden[normalized].constraint_id),
                        hard_conflict=False,
                        reason_code="soft_preference_conflicts_with_hard_prohibition",
                    )
                )
                traded.append(preference.constraint_id)
                continue

            opposites = {
                "write_allowed:true": "write_allowed:false",
                "network_allowed:true": "network_allowed:false",
                "process_allowed:true": "process_allowed:false",
            }
            opposite = opposites.get(normalized)
            hard_restriction = (
                boundaries.get(opposite) if opposite is not None else None
            ) or (project_policies.get(opposite) if opposite is not None else None)
            if hard_restriction is not None:
                reason = (
                    "soft_preference_conflicts_with_authority_boundary"
                    if hard_restriction.kind is ConstraintKind.AUTHORITY_BOUNDARY
                    else "soft_preference_conflicts_with_project_policy"
                )
                conflicts.append(
                    self._conflict(
                        refs=(preference.constraint_id, hard_restriction.constraint_id),
                        hard_conflict=False,
                        reason_code=reason,
                    )
                )
                traded.append(preference.constraint_id)
                continue

            if normalized.startswith("write:"):
                path = normalized.removeprefix("write:").strip().replace("\\", "/")
                protected_key = f"protected_path:{path}"
                if protected_key in boundaries:
                    conflicts.append(
                        self._conflict(
                            refs=(
                                preference.constraint_id,
                                boundaries[protected_key].constraint_id,
                            ),
                            hard_conflict=False,
                            reason_code="soft_preference_targets_protected_path",
                        )
                    )
                    traded.append(preference.constraint_id)

        traded_set = set(traded)
        accepted = tuple(
            item.constraint_id
            for item in preferences
            if item.constraint_id not in traded_set
        )
        return tuple(conflicts), accepted, tuple(dict.fromkeys(traded))

    def _judge(
        self,
        *,
        task_id: UUID,
        raw_request: str,
        request_fingerprint: str,
        literal_objective: str,
        required_conditions: tuple[str, ...],
        forbidden_outcomes: tuple[str, ...],
        evidence_required: tuple[str, ...],
        soft_preferences: tuple[str, ...],
        scope: TaskScope,
        risk_level: RiskLevel,
        unresolved_ambiguities: tuple[str, ...],
        blocking_ambiguities: tuple[str, ...],
        source_prefix: str,
    ) -> IntentConstraintJudgment:
        constraints = self._constraints(
            required_conditions=required_conditions,
            forbidden_outcomes=forbidden_outcomes,
            evidence_required=evidence_required,
            soft_preferences=soft_preferences,
            scope=scope,
            risk_level=risk_level,
            source_prefix=source_prefix,
        )
        conflicts, accepted_preferences, traded_preferences = self._reconcile(constraints)
        hard_conflicts = tuple(item for item in conflicts if item.hard_conflict)
        solution_shaped = self._solution_shaped(raw_request)
        reconstructed = (
            _bounded_outcome_objective(required_conditions, literal_objective)
            if solution_shaped and required_conditions
            else literal_objective
        )

        blockers = tuple(
            dict.fromkeys(
                (
                    *(f"c4:ambiguity:{item}" for item in blocking_ambiguities),
                    *(f"c4:conflict:{item.conflict_id}" for item in hard_conflicts),
                )
            )
        )
        reasons = ["hard_constraints_preserved", "authority_boundaries_preserved"]
        if blockers:
            action = SpecificationControlAction.STOP_VERIFY
            reasons.append("critical_specification_issue_requires_stop_verify")
        elif traded_preferences:
            action = SpecificationControlAction.TRADE_OFF
            reasons.extend(
                (
                    "soft_preference_traded_against_hard_constraint",
                    "hard_constraint_wins_over_preference",
                )
            )
        elif solution_shaped and reconstructed != literal_objective:
            action = SpecificationControlAction.RECONSTRUCT
            reasons.extend(
                (
                    "solution_shaped_request_detected",
                    "outcome_conditions_define_reconstructed_objective",
                )
            )
        else:
            action = SpecificationControlAction.ACCEPT_LITERAL
            reasons.append("literal_objective_is_compatible_with_explicit_contract")

        hard_refs = tuple(
            item.constraint_id
            for item in constraints
            if item.strength is ConstraintStrength.HARD
        )
        basis_fingerprint = IntentConstraintJudgment.compute_basis_fingerprint(
            task_id=task_id,
            request_fingerprint=request_fingerprint,
            literal_objective=literal_objective,
            reconstructed_objective=reconstructed,
            constraints=constraints,
            conflicts=conflicts,
            unresolved_ambiguities=unresolved_ambiguities,
        )
        return IntentConstraintJudgment(
            task_id=task_id,
            request_fingerprint=request_fingerprint,
            specification_basis_fingerprint=basis_fingerprint,
            literal_objective=literal_objective,
            reconstructed_objective=reconstructed,
            action=action,
            solution_shaped_request=solution_shaped,
            constraints=constraints,
            conflicts=conflicts,
            preserved_hard_constraint_refs=hard_refs,
            accepted_preference_refs=accepted_preferences,
            traded_off_preference_refs=traded_preferences,
            unresolved_ambiguities=unresolved_ambiguities,
            blocker_refs=blockers,
            reason_codes=tuple(reasons),
        )

    def from_draft(
        self,
        *,
        intent: IntentResolution,
        draft: TaskContractDraft,
    ) -> IntentConstraintJudgment:
        """Judge a pre-finalization draft so blockers can stop planning."""
        if intent.raw_request.strip() == "":
            raise ValueError("C4 intent request cannot be empty")
        return self._judge(
            task_id=draft.task_id,
            raw_request=intent.raw_request,
            request_fingerprint=intent.request_fingerprint,
            literal_objective=draft.objective,
            required_conditions=draft.required_conditions,
            forbidden_outcomes=draft.forbidden_outcomes,
            evidence_required=draft.evidence_required,
            soft_preferences=draft.soft_preferences,
            scope=draft.scope,
            risk_level=draft.risk_level,
            unresolved_ambiguities=draft.unresolved_unknowns,
            blocking_ambiguities=draft.blocking_unknowns,
            source_prefix="task_input",
        )

    def from_contract(
        self,
        *,
        raw_request: str,
        contract: TaskContract,
        soft_preferences: tuple[str, ...] = (),
    ) -> IntentConstraintJudgment:
        """Rebuild C4 judgment from the immutable task contract when needed."""
        normalized = DeterministicIntentResolver.normalize(raw_request)
        fingerprint = sha256(normalized.encode("utf-8")).hexdigest()
        return self._judge(
            task_id=contract.task_id,
            raw_request=raw_request,
            request_fingerprint=fingerprint,
            literal_objective=contract.objective,
            required_conditions=contract.required_conditions,
            forbidden_outcomes=contract.forbidden_outcomes,
            evidence_required=contract.evidence_required,
            soft_preferences=soft_preferences,
            scope=contract.scope,
            risk_level=contract.risk_level,
            unresolved_ambiguities=contract.unknowns,
            blocking_ambiguities=(),
            source_prefix="task_input",
        )

    def refine_from_state(
        self,
        *,
        base: IntentConstraintJudgment,
        state: TaskState,
    ) -> IntentConstraintJudgment:
        """Bind only current supported C1 context into the C4 advisory basis.

        Verified project policy becomes a preserved hard C4 constraint. Other supported
        task-relevant context is fingerprinted as decision basis without being promoted to
        a hard requirement. Unsupported or contradicted assumptions never gain authority here.
        """
        if base.task_id != state.task_id:
            raise ValueError("C4 specification task does not match task state")
        if base.literal_objective != state.contract.objective:
            raise ValueError("C4 specification literal objective does not match task contract")

        snapshot = DecisionStateService.ensure(state.task_id, state.decision_state)
        current = DecisionStateService.current_assumptions(snapshot)
        supported = tuple(
            item
            for item in current
            if item.status is AssumptionStatus.SUPPORTED
            and item.claim_type in _CONTEXT_BASIS_CLAIM_TYPES
        )
        supported = tuple(
            sorted(
                supported,
                key=lambda item: (item.claim_type, item.key, str(item.assumption_id)),
            )
        )

        base_constraints = tuple(
            item
            for item in base.constraints
            if not (
                item.kind is ConstraintKind.PROJECT_POLICY
                and item.source_ref.startswith("c1:assumption:")
            )
        )
        project_policies: list[SpecificationConstraint] = []
        context_basis_refs: list[str] = []
        for assumption in supported:
            assumption_ref = f"c1:assumption:{assumption.assumption_id}"
            context_basis_refs.append(assumption_ref)
            if assumption.claim_type != ContextClaimType.PROJECT_POLICY.value:
                continue
            project_policies.append(
                self._constraint(
                    kind=ConstraintKind.PROJECT_POLICY,
                    strength=ConstraintStrength.HARD,
                    statement=_assumption_value(
                        key=assumption.key,
                        statement=assumption.statement,
                    ),
                    source_ref=assumption_ref,
                    provenance_refs=(
                        *assumption.evidence_refs,
                        *assumption.provenance_refs,
                    ),
                )
            )

        constraints = (*base_constraints, *project_policies)
        conflicts, accepted_preferences, traded_preferences = self._reconcile(constraints)
        hard_conflicts = tuple(item for item in conflicts if item.hard_conflict)
        inherited_blockers = tuple(
            ref for ref in base.blocker_refs if not ref.startswith("c4:conflict:")
        )
        blockers = tuple(
            dict.fromkeys(
                (
                    *inherited_blockers,
                    *(f"c4:conflict:{item.conflict_id}" for item in hard_conflicts),
                )
            )
        )

        reasons = ["hard_constraints_preserved", "authority_boundaries_preserved"]
        if project_policies:
            reasons.append("verified_project_policy_bound")
        if context_basis_refs:
            reasons.append("verified_context_basis_bound")
        if blockers:
            action = SpecificationControlAction.STOP_VERIFY
            reasons.append("critical_specification_issue_requires_stop_verify")
        elif traded_preferences:
            action = SpecificationControlAction.TRADE_OFF
            reasons.extend(
                (
                    "soft_preference_traded_against_hard_constraint",
                    "hard_constraint_wins_over_preference",
                )
            )
        elif (
            base.solution_shaped_request
            and base.reconstructed_objective != base.literal_objective
        ):
            action = SpecificationControlAction.RECONSTRUCT
            reasons.extend(
                (
                    "solution_shaped_request_detected",
                    "outcome_conditions_define_reconstructed_objective",
                )
            )
        else:
            action = SpecificationControlAction.ACCEPT_LITERAL
            reasons.append("literal_objective_is_compatible_with_explicit_contract")

        hard_refs = tuple(
            item.constraint_id
            for item in constraints
            if item.strength is ConstraintStrength.HARD
        )
        context_refs = tuple(context_basis_refs)
        basis_fingerprint = IntentConstraintJudgment.compute_basis_fingerprint(
            task_id=base.task_id,
            request_fingerprint=base.request_fingerprint,
            literal_objective=base.literal_objective,
            reconstructed_objective=base.reconstructed_objective,
            constraints=constraints,
            conflicts=conflicts,
            unresolved_ambiguities=base.unresolved_ambiguities,
            context_basis_refs=context_refs,
        )
        return IntentConstraintJudgment(
            task_id=base.task_id,
            request_fingerprint=base.request_fingerprint,
            specification_basis_fingerprint=basis_fingerprint,
            literal_objective=base.literal_objective,
            reconstructed_objective=base.reconstructed_objective,
            action=action,
            solution_shaped_request=base.solution_shaped_request,
            constraints=constraints,
            conflicts=conflicts,
            preserved_hard_constraint_refs=hard_refs,
            accepted_preference_refs=accepted_preferences,
            traded_off_preference_refs=traded_preferences,
            unresolved_ambiguities=base.unresolved_ambiguities,
            context_basis_refs=context_refs,
            blocker_refs=blockers,
            reason_codes=tuple(reasons),
        )
