"""Deterministic verifier for R7-B Working Session Continuity v0.1."""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.context import (  # noqa: E402
    CONTEXT_LAYER_ORDER,
    ContextAuthorityRole,
    ContextInterpretation,
    ContextLayer,
)
from luna.sessions import (  # noqa: E402
    SessionEntryRole,
    SQLiteSessionStore,
    WorkingSessionService,
)

_REQUIRED_FILES = (
    "src/luna/sessions/__init__.py",
    "src/luna/sessions/models.py",
    "src/luna/sessions/store.py",
    "src/luna/sessions/service.py",
    "tests/test_r7b_session_continuity.py",
)
_FORBIDDEN_IMPORT_PREFIXES = (
    "luna.memory",
    "luna.continuity",
    "luna.decision_state",
    "luna.verification",
    "luna.tools",
    "luna.autonomy",
    "luna.improvement_gate",
)
_FORBIDDEN_STRUCTURED_NAMES = {
    "reasoning",
    "hidden_reasoning",
    "chain_of_thought",
    "private_context",
    "approval",
    "tool_policy",
    "autonomy",
    "verified",
    "evidence_id",
    "checkpoint_id",
}


def _session_sources_are_boundary_clean() -> bool:
    for relative in (
        "src/luna/sessions/models.py",
        "src/luna/sessions/store.py",
        "src/luna/sessions/service.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = (node.module or "",)
            else:
                names = ()
            if any(
                name == prefix or name.startswith(prefix + ".")
                for name in names
                for prefix in _FORBIDDEN_IMPORT_PREFIXES
            ):
                return False
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
                "resume",
                "approve",
                "authorize",
                "verify_claim",
                "commit_memory",
            }:
                return False
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id.casefold() in _FORBIDDEN_STRUCTURED_NAMES
            ):
                return False
    return True


def main() -> int:
    missing = tuple(relative for relative in _REQUIRED_FILES if not (ROOT / relative).is_file())
    checks: dict[str, bool] = {
        "required_files_present": not missing,
        "canonical_context_layers_unchanged": tuple(layer.value for layer in CONTEXT_LAYER_ORDER)
        == ("ACTIVE", "TASK", "RUNTIME_CONTINUITY", "WORKSPACE", "VERIFIED_MEMORY"),
        "session_source_boundaries_clean": _session_sources_are_boundary_clean(),
    }

    if not missing:
        with tempfile.TemporaryDirectory(prefix="luna-r7b-") as temp:
            root = Path(temp)
            secret = "r7b-verifier-secret"
            service = WorkingSessionService(
                SQLiteSessionStore(root / "session.sqlite3"),
                explicit_secrets=(secret,),
            )
            session = service.open_session(owner_ref="owner:r7b-verifier")
            task_id = uuid4()
            service.append_visible_message(
                session_id=session.session_id,
                owner_ref=session.owner_ref,
                role=SessionEntryRole.USER,
                content=f"Visible token={secret} message.",
                source_task_id=task_id,
            )
            restarted = WorkingSessionService(SQLiteSessionStore(root / "session.sqlite3"))
            snapshot = restarted.snapshot(
                session_id=session.session_id,
                owner_ref=session.owner_ref,
            )
            projected = restarted.project_context(
                session_id=session.session_id,
                owner_ref=session.owner_ref,
            )
            candidate = projected[0]
            checks.update(
                {
                    "restart_safe": len(snapshot.entries) == 1,
                    "redaction_before_persistence": secret
                    not in (root / "session.sqlite3").read_bytes().decode(
                        "utf-8", errors="ignore"
                    ),
                    "runtime_continuity_projection": candidate.layer
                    is ContextLayer.RUNTIME_CONTINUITY,
                    "data_only_projection": candidate.interpretation
                    is ContextInterpretation.DATA_ONLY,
                    "projection_unverified": candidate.source.verified is False,
                    "conversation_semantics": candidate.source.metadata.get("authority_role")
                    == ContextAuthorityRole.CONVERSATION.value,
                }
            )

    failed = tuple(name for name, ok in checks.items() if not ok)
    for name, ok in checks.items():
        print(f"{name}: {'PASS' if ok else 'FAIL'}")
    if missing:
        print("missing_files:")
        for relative in missing:
            print(f"  {relative}")
    if failed:
        print("R7-B Working Session Continuity verifier: FAIL")
        return 2
    print("R7-B Working Session Continuity verifier: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
