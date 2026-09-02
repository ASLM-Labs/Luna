from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from luna.applied_changes.models import (
    AppliedChangeBindingError,
    AppliedChangeBindingState,
    AppliedChangeOperation,
    AppliedChangeProjectionPolicy,
    AppliedChangeRecord,
    applied_change_manifest_sha256,
)
from luna.applied_changes.projector import (
    project_text_change,
)
from luna.applied_changes.store import (
    SQLiteAppliedChangeStore,
)
from luna.contracts import (
    RiskLevel,
    TaskContract,
    TaskScope,
)
from luna.runtime.journal import (
    SQLiteRuntimeJournal,
)
from luna.tools import (
    AutonomyLevel,
    ToolCapability,
    ToolDispatcher,
    ToolPolicy,
    ToolRequest,
    ToolResultStatus,
    ToolSpec,
    build_phase5_registry,
)
from luna.tools.models import (
    ToolArgumentValue,
)
from luna.tools.registry import (
    ToolExecutionContext,
    ToolExecutionOutput,
    ToolRegistry,
)


def _digest(
    value: bytes,
) -> str:
    return sha256(value).hexdigest()


def _write_contract(
    root: Path,
) -> TaskContract:
    return TaskContract(
        objective=(
            "Bind one exact workspace "
            "mutation result."
        ),
        required_conditions=(
            "Execution status remains authoritative.",
        ),
        evidence_required=(
            "Durable applied-change binding.",
        ),
        scope=TaskScope(
            workspace_root=str(root),
            allowed_paths=(
                "notes.txt",
            ),
            write_allowed=True,
        ),
        risk_level=RiskLevel.HIGH,
    )


def _write_request(
    contract: TaskContract,
    *,
    before_digest: str,
) -> ToolRequest:
    return ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="filesystem.write_text",
        arguments={
            "path": "notes.txt",
            "content": "after\n",
            "expected_sha256": before_digest,
            "create_if_missing": False,
        },
        expectation_id=uuid4(),
    )


def _write_policy() -> ToolPolicy:
    return ToolPolicy(
        allowed_tools=(
            "filesystem.write_text",
        ),
        autonomy_level=(
            AutonomyLevel.BOUNDED
        ),
        max_risk=RiskLevel.MEDIUM,
    )


def test_dispatcher_binds_workspace_change_to_exact_result(
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.txt"

    before = b"before\n"
    target.write_bytes(before)

    contract = _write_contract(
        tmp_path
    )

    request = _write_request(
        contract,
        before_digest=_digest(before),
    )

    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied-changes.sqlite3"
    )

    outcome = ToolDispatcher(
        build_phase5_registry(),
        applied_change_store=store,
    ).dispatch(
        request=request,
        task_contract=contract,
        policy=_write_policy(),
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_state"
        ]
        == AppliedChangeBindingState.BOUND.value
    )

    assert (
        outcome.result.metadata[
            "applied_change_count"
        ]
        == 1
    )

    manifest = str(
        outcome.result.metadata[
            "applied_change_manifest_sha256"
        ]
    )

    assert len(manifest) == 64

    records = store.list_for_result(
        task_id=contract.task_id,
        request_id=request.request_id,
        result_id=outcome.result.result_id,
    )

    assert len(records) == 1

    record = records[0]

    assert (
        record.task_id
        == contract.task_id
    )

    assert (
        record.request_id
        == request.request_id
    )

    assert (
        record.result_id
        == outcome.result.result_id
    )

    assert (
        record.candidate.relative_path
        == "notes.txt"
    )

    assert (
        applied_change_manifest_sha256(
            records
        )
        == manifest
    )


def test_dispatcher_reports_missing_store_without_relabeling_success(
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.txt"

    before = b"before\n"
    target.write_bytes(before)

    contract = _write_contract(
        tmp_path
    )

    outcome = ToolDispatcher(
        build_phase5_registry()
    ).dispatch(
        request=_write_request(
            contract,
            before_digest=_digest(before),
        ),
        task_contract=contract,
        policy=_write_policy(),
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        target.read_bytes()
        == b"after\n"
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_state"
        ]
        == (
            AppliedChangeBindingState
            .UNAVAILABLE.value
        )
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_error"
        ]
        == (
            AppliedChangeBindingError
            .STORE_NOT_CONFIGURED.value
        )
    )

    assert (
        outcome.result.metadata[
            "applied_change_count"
        ]
        == 1
    )

    assert (
        "applied_change_manifest_sha256"
        not in outcome.result.metadata
    )


class _FailingStore:
    def persist_many(
        self,
        records: tuple[
            AppliedChangeRecord,
            ...,
        ],
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        del records
        raise RuntimeError(
            "injected evidence-store failure"
        )

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        del task_id, request_id, result_id
        raise AssertionError(
            "failed persist must not load"
        )


def test_dispatcher_store_failure_does_not_relabel_committed_write(
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.txt"

    before = b"before\n"
    target.write_bytes(before)

    contract = _write_contract(
        tmp_path
    )

    outcome = ToolDispatcher(
        build_phase5_registry(),
        applied_change_store=(
            _FailingStore()
        ),
    ).dispatch(
        request=_write_request(
            contract,
            before_digest=_digest(before),
        ),
        task_contract=contract,
        policy=_write_policy(),
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        outcome.result.error_class
        is None
    )

    assert (
        target.read_bytes()
        == b"after\n"
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_error"
        ]
        == (
            AppliedChangeBindingError
            .PERSISTENCE_FAILED.value
        )
    )


class _MetadataSpoofTool:
    def execute(
        self,
        arguments: dict[
            str,
            ToolArgumentValue,
        ],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments, context

        return ToolExecutionOutput(
            stdout="ok",
            metadata={
                "safe": "yes",
                (
                    "applied_change_"
                    "binding_state"
                ): "BOUND",
                (
                    "applied_change_"
                    "count"
                ): 99,
                (
                    "applied_change_"
                    "manifest_sha256"
                ): "0" * 64,
            },
        )


def test_dispatcher_strips_handler_owned_binding_metadata_namespace(
    tmp_path: Path,
) -> None:
    del tmp_path

    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="core.metadata_spoof",
            description=(
                "Exercise reserved metadata "
                "namespace ownership."
            ),
            capabilities=(),
        ),
        _MetadataSpoofTool(),
    )

    contract = TaskContract(
        objective=(
            "Reject handler-owned binding receipt."
        ),
        required_conditions=(
            "Dispatcher owns receipt namespace.",
        ),
        evidence_required=(
            "Normalized ToolResult metadata.",
        ),
        scope=TaskScope(
            workspace_root=".",
        ),
        risk_level=RiskLevel.LOW,
    )

    outcome = ToolDispatcher(
        registry
    ).dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="core.metadata_spoof",
        ),
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=(
                "core.metadata_spoof",
            ),
        ),
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        outcome.result.metadata
        == {"safe": "yes"}
    )


class _UnsupportedCandidateTool:
    def execute(
        self,
        arguments: dict[
            str,
            ToolArgumentValue,
        ],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        del arguments

        before = b"before\n"
        after = b"after\n"

        candidate = project_text_change(
            task_id=(
                context.task_contract.task_id
            ),
            operation=(
                AppliedChangeOperation
                .WRITE_TEXT
            ),
            relative_path="notes.txt",
            before_text=(
                before.decode("utf-8")
            ),
            after_text=(
                after.decode("utf-8")
            ),
            before_digest=_digest(before),
            after_digest=_digest(after),
            before_size_bytes=len(before),
            after_size_bytes=len(after),
            policy=(
                AppliedChangeProjectionPolicy()
            ),
        )

        return ToolExecutionOutput(
            stdout="synthetic",
            changed_files=(
                "notes.txt",
            ),
            applied_changes=(
                candidate,
            ),
        )


def test_dispatcher_refuses_candidate_from_noncanonical_tool_source(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="filesystem.synthetic_write",
            description=(
                "Synthetic candidate provenance test."
            ),
            risk_level=RiskLevel.MEDIUM,
            capabilities=(
                ToolCapability.WRITE,
            ),
        ),
        _UnsupportedCandidateTool(),
    )

    contract = _write_contract(
        tmp_path
    )

    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name=(
            "filesystem.synthetic_write"
        ),
        expectation_id=uuid4(),
    )

    store = SQLiteAppliedChangeStore(
        tmp_path
        / "applied-changes.sqlite3"
    )

    outcome = ToolDispatcher(
        registry,
        applied_change_store=store,
    ).dispatch(
        request=request,
        task_contract=contract,
        policy=ToolPolicy(
            allowed_tools=(
                "filesystem.synthetic_write",
            ),
            autonomy_level=(
                AutonomyLevel.BOUNDED
            ),
            max_risk=RiskLevel.MEDIUM,
        ),
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_state"
        ]
        == (
            AppliedChangeBindingState
            .UNAVAILABLE.value
        )
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_error"
        ]
        == (
            AppliedChangeBindingError
            .CANDIDATE_SOURCE_MISMATCH.value
        )
    )

    assert (
        store.list_for_result(
            task_id=contract.task_id,
            request_id=request.request_id,
            result_id=(
                outcome.result.result_id
            ),
        )
        == ()
    )





class _TaskMismatchCandidateTool(
    _UnsupportedCandidateTool
):
    def execute(
        self,
        arguments: dict[
            str,
            ToolArgumentValue,
        ],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        output = super().execute(
            arguments,
            context,
        )

        candidate = (
            output.applied_changes[0]
            .model_copy(
                update={
                    "task_id": uuid4(),
                }
            )
        )

        return ToolExecutionOutput(
            stdout=output.stdout,
            changed_files=output.changed_files,
            applied_changes=(candidate,),
        )


class _PathMismatchCandidateTool(
    _UnsupportedCandidateTool
):
    def execute(
        self,
        arguments: dict[
            str,
            ToolArgumentValue,
        ],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        output = super().execute(
            arguments,
            context,
        )

        return ToolExecutionOutput(
            stdout=output.stdout,
            changed_files=("different.txt",),
            applied_changes=output.applied_changes,
        )


class _PersistedSetMismatchStore:
    def persist_many(
        self,
        records: tuple[
            AppliedChangeRecord,
            ...,
        ],
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        del records
        return ()

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        del task_id, request_id, result_id
        raise AssertionError(
            "persisted-set mismatch must stop "
            "before durable readback"
        )


class _DurableSetMismatchStore:
    def persist_many(
        self,
        records: tuple[
            AppliedChangeRecord,
            ...,
        ],
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        return records

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        del task_id, request_id, result_id
        return ()


def _dispatch_canonical_synthetic_candidate(
    tmp_path: Path,
    *,
    tool: object,
    store: object,
):
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="filesystem.write_text",
            description=(
                "Exercise fail-closed applied-change "
                "binding validation."
            ),
            risk_level=RiskLevel.MEDIUM,
            capabilities=(
                ToolCapability.WRITE,
            ),
        ),
        tool,
    )

    contract = _write_contract(
        tmp_path
    )

    outcome = ToolDispatcher(
        registry,
        applied_change_store=store,
    ).dispatch(
        request=ToolRequest(
            task_id=contract.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.write_text",
            expectation_id=uuid4(),
        ),
        task_contract=contract,
        policy=_write_policy(),
    )

    return contract, outcome


def test_dispatcher_rejects_candidate_bound_to_other_task(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "task-mismatch.sqlite3"
    )

    contract, outcome = (
        _dispatch_canonical_synthetic_candidate(
            tmp_path,
            tool=_TaskMismatchCandidateTool(),
            store=store,
        )
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_state"
        ]
        == (
            AppliedChangeBindingState
            .UNAVAILABLE.value
        )
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_error"
        ]
        == (
            AppliedChangeBindingError
            .CANDIDATE_TASK_MISMATCH.value
        )
    )

    assert (
        store.list_for_result(
            task_id=contract.task_id,
            request_id=(
                outcome.request.request_id
            ),
            result_id=(
                outcome.result.result_id
            ),
        )
        == ()
    )


def test_dispatcher_rejects_candidate_path_set_mismatch(
    tmp_path: Path,
) -> None:
    store = SQLiteAppliedChangeStore(
        tmp_path
        / "path-mismatch.sqlite3"
    )

    contract, outcome = (
        _dispatch_canonical_synthetic_candidate(
            tmp_path,
            tool=_PathMismatchCandidateTool(),
            store=store,
        )
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_error"
        ]
        == (
            AppliedChangeBindingError
            .CANDIDATE_PATH_MISMATCH.value
        )
    )

    assert (
        store.list_for_result(
            task_id=contract.task_id,
            request_id=(
                outcome.request.request_id
            ),
            result_id=(
                outcome.result.result_id
            ),
        )
        == ()
    )


def test_dispatcher_rejects_persist_many_return_set_mismatch(
    tmp_path: Path,
) -> None:
    _, outcome = (
        _dispatch_canonical_synthetic_candidate(
            tmp_path,
            tool=_UnsupportedCandidateTool(),
            store=_PersistedSetMismatchStore(),
        )
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_error"
        ]
        == (
            AppliedChangeBindingError
            .PERSISTED_SET_MISMATCH.value
        )
    )

    assert (
        "applied_change_manifest_sha256"
        not in outcome.result.metadata
    )


def test_dispatcher_rejects_durable_readback_set_mismatch(
    tmp_path: Path,
) -> None:
    _, outcome = (
        _dispatch_canonical_synthetic_candidate(
            tmp_path,
            tool=_UnsupportedCandidateTool(),
            store=_DurableSetMismatchStore(),
        )
    )

    assert (
        outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        outcome.result.metadata[
            "applied_change_binding_error"
        ]
        == (
            AppliedChangeBindingError
            .PERSISTED_SET_MISMATCH.value
        )
    )

    assert (
        "applied_change_manifest_sha256"
        not in outcome.result.metadata
    )




def test_runtime_journal_round_trips_legacy_and_bound_applied_change_outcomes(
    tmp_path: Path,
) -> None:
    read_target = tmp_path / "read.txt"
    read_target.write_bytes(b"hello\n")

    read_contract = TaskContract(
        objective=(
            "Preserve legacy-style dispatch serialization."
        ),
        required_conditions=(
            "No applied-change receipt is required.",
        ),
        evidence_required=(
            "RuntimeJournal round-trip.",
        ),
        scope=TaskScope(
            workspace_root=str(tmp_path),
            allowed_paths=("read.txt",),
        ),
        risk_level=RiskLevel.LOW,
    )

    read_outcome = ToolDispatcher(
        build_phase5_registry(),
    ).dispatch(
        request=ToolRequest(
            task_id=read_contract.task_id,
            trace_id=uuid4(),
            tool_name="filesystem.read_text",
            arguments={
                "path": "read.txt",
            },
        ),
        task_contract=read_contract,
        policy=ToolPolicy(
            allowed_tools=(
                "filesystem.read_text",
            ),
        ),
    )

    assert (
        read_outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert not any(
        key.startswith("applied_change_")
        for key in read_outcome.result.metadata
    )

    legacy_journal = SQLiteRuntimeJournal(
        tmp_path / "legacy-journal.sqlite3"
    )

    legacy_record = legacy_journal.record_outcome(
        read_outcome
    )

    legacy_loaded = legacy_journal.list_observations(
        read_contract.task_id
    )

    assert legacy_loaded == (legacy_record,)
    assert legacy_loaded[0].outcome == read_outcome
    assert legacy_journal.verify_integrity()

    target = tmp_path / "notes.txt"
    before = b"before\n"
    target.write_bytes(before)

    write_contract = _write_contract(
        tmp_path
    )

    store = SQLiteAppliedChangeStore(
        tmp_path / "applied-changes.sqlite3"
    )

    write_outcome = ToolDispatcher(
        build_phase5_registry(),
        applied_change_store=store,
    ).dispatch(
        request=_write_request(
            write_contract,
            before_digest=_digest(before),
        ),
        task_contract=write_contract,
        policy=_write_policy(),
    )

    assert (
        write_outcome.result.status
        is ToolResultStatus.SUCCESS
    )

    assert (
        write_outcome.result.metadata[
            "applied_change_binding_state"
        ]
        == AppliedChangeBindingState.BOUND.value
    )

    manifest = write_outcome.result.metadata[
        "applied_change_manifest_sha256"
    ]

    assert isinstance(manifest, str)

    bound_journal = SQLiteRuntimeJournal(
        tmp_path / "bound-journal.sqlite3"
    )

    bound_record = bound_journal.record_outcome(
        write_outcome
    )

    bound_loaded = bound_journal.list_observations(
        write_contract.task_id
    )

    assert bound_loaded == (bound_record,)
    assert bound_loaded[0].outcome == write_outcome

    assert (
        bound_loaded[0]
        .outcome
        .result
        .metadata[
            "applied_change_manifest_sha256"
        ]
        == manifest
    )

    assert bound_journal.verify_integrity()



class _PersistSpyStore:
    def __init__(self) -> None:
        self.persist_calls = 0

    def persist_many(
        self,
        records: tuple[
            AppliedChangeRecord,
            ...,
        ],
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        self.persist_calls += 1
        return records

    def list_for_result(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        result_id: UUID,
    ) -> tuple[
        AppliedChangeRecord,
        ...,
    ]:
        del task_id, request_id, result_id
        raise AssertionError(
            "result validation must precede durable lookup"
        )


class _InvalidMetadataCanonicalWriteTool(
    _UnsupportedCandidateTool
):
    def execute(
        self,
        arguments: dict[
            str,
            ToolArgumentValue,
        ],
        context: ToolExecutionContext,
    ) -> ToolExecutionOutput:
        output = super().execute(
            arguments,
            context,
        )

        return ToolExecutionOutput(
            stdout=output.stdout,
            stderr=output.stderr,
            changed_files=output.changed_files,
            applied_changes=output.applied_changes,
            metadata={
                "invalid_runtime_metadata": [
                    "not-a-tool-scalar"
                ],
            },
        )


def test_result_contract_validation_precedes_applied_change_persistence(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="filesystem.write_text",
            description=(
                "Exercise result-contract "
                "validation ordering."
            ),
            risk_level=RiskLevel.MEDIUM,
            capabilities=(
                ToolCapability.WRITE,
            ),
        ),
        _InvalidMetadataCanonicalWriteTool(),
    )

    contract = _write_contract(
        tmp_path
    )

    request = ToolRequest(
        task_id=contract.task_id,
        trace_id=uuid4(),
        tool_name="filesystem.write_text",
        expectation_id=uuid4(),
    )

    store = _PersistSpyStore()

    with pytest.raises(
        ValidationError,
    ):
        ToolDispatcher(
            registry,
            applied_change_store=store,
        ).dispatch(
            request=request,
            task_contract=contract,
            policy=_write_policy(),
        )

    assert store.persist_calls == 0
