"""Deterministic Phase 13 real-model compatibility and controlled-rollout gate."""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.conformance import RUNTIME_CONFORMANCE_SUITE_SHA256  # noqa: E402
from luna.conformance.runtime_executor import _build_runtime, _policy, _request  # noqa: E402
from luna.modeling import (  # noqa: E402
    ControlledModelBackend,
    LocalOpenAICompatibleBackend,
    MessageRole,
    ModelBackendError,
    ModelBackendErrorCode,
    ModelCompatibilityProbe,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRolloutGate,
    ModelRolloutHealth,
    ModelRolloutPolicy,
    ModelRolloutStage,
    ModelToolCall,
    ScriptedModelOutput,
    ScriptedTestBackend,
    ScriptedTurn,
)
from luna.runtime import RuntimeStopReason  # noqa: E402

REQUIRED_FILES = (
    "src/luna/modeling/errors.py",
    "src/luna/modeling/compatibility.py",
    "src/luna/modeling/rollout.py",
    "tests/test_phase13_model_compatibility_rollout.py",
    "scripts/verify_phase13.py",
    "docs/rfcs/RFC-013_REAL_MODEL_COMPATIBILITY_CONTROLLED_ROLLOUT.md",
    "docs/PHASE_13_REPORT.md",
    "phase_13_verification.json",
)

EXPECTED_PHASE12G_SUITE_SHA = "52346f987ad274b02b265c431d309be0dd83e2bc100fb497634474f294ab644e"


class _FailingBackend:
    def __init__(self, *, code: ModelBackendErrorCode, retryable: bool) -> None:
        self._code = code
        self._retryable = retryable
        self.calls = 0

    @property
    def backend_id(self) -> str:
        return "phase13-verifier-failing"

    def generate(self, request: ModelRequest) -> ModelResponse:
        del request
        self.calls += 1
        raise ModelBackendError(
            code=self._code,
            backend_id=self.backend_id,
            safe_reason="deterministic verifier backend failure",
            retryable=self._retryable,
        )


def _compatible_backend() -> ScriptedTestBackend:
    return ScriptedTestBackend(
        turns=(
            ScriptedTurn(
                output=ScriptedModelOutput(
                    text="LUNA_COMPAT_OK",
                    finish_reason=ModelFinishReason.STOP,
                )
            ),
            ScriptedTurn(
                output=ScriptedModelOutput(
                    tool_calls=(
                        ModelToolCall(
                            call_id="phase13-verifier-tool",
                            tool_name="compat.echo",
                            arguments={"message": "LUNA_TOOL_OK"},
                        ),
                    ),
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                )
            ),
        ),
        backend_id="phase13-verifier-compatible",
    )


def _canonical_metadata_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return raw
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _metadata_integrity() -> bool:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    phase = str(manifest.get("phase", ""))
    match = re.fullmatch(r"(\d+)(?:[A-Z])?", phase)
    if match is None or int(match.group(1)) < 13:
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
        return False
    if any(str(relative).endswith(".log") for relative in files):
        return False

    sums: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            return False
        digest, relative = line.split("  ", 1)
        sums[relative] = digest
    if set(sums) != set(files):
        return False

    for relative, metadata in files.items():
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            return False
        target = ROOT / relative
        if not target.is_file():
            return False
        canonical = _canonical_metadata_bytes(target)
        digest = sha256(canonical).hexdigest()
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {"required_files_present": not missing}

    backend = _compatible_backend()
    report = ModelCompatibilityProbe().run(backend)
    second_report = ModelCompatibilityProbe().run(_compatible_backend())
    checks["required_compatibility_cases_pass"] = (
        report.required_passed
        and report.eligible_for_rollout
        and len(report.results) == 4
    )
    checks["compatibility_fingerprint_stable"] = (
        report.fingerprint() == second_report.fingerprint()
        and re.fullmatch(r"[0-9a-f]{64}", report.fingerprint()) is not None
    )

    fingerprint = report.fingerprint()
    gate = ModelRolloutGate()
    task_id = uuid4()
    shadow_policy = ModelRolloutPolicy(
        backend_id=report.backend_id,
        approved_compatibility_fingerprint=fingerprint,
        stage=ModelRolloutStage.SHADOW,
    )
    active_policy = ModelRolloutPolicy(
        backend_id=report.backend_id,
        approved_compatibility_fingerprint=fingerprint,
        stage=ModelRolloutStage.ACTIVE,
    )
    canary_policy = ModelRolloutPolicy(
        backend_id=report.backend_id,
        approved_compatibility_fingerprint=fingerprint,
        stage=ModelRolloutStage.CANARY,
        canary_percent=25,
    )

    shadow = gate.decide(
        task_id=task_id,
        policy=shadow_policy,
        compatibility=report,
        health=ModelRolloutHealth(),
    )
    active = gate.decide(
        task_id=task_id,
        policy=active_policy,
        compatibility=report,
        health=ModelRolloutHealth(),
    )
    canary_a = gate.decide(
        task_id=task_id,
        policy=canary_policy,
        compatibility=report,
        health=ModelRolloutHealth(),
    )
    canary_b = gate.decide(
        task_id=task_id,
        policy=canary_policy,
        compatibility=report,
        health=ModelRolloutHealth(),
    )
    tripwire = gate.decide(
        task_id=task_id,
        policy=active_policy,
        compatibility=report,
        health=ModelRolloutHealth(false_successes=1),
    )
    checks["shadow_has_no_authoritative_power"] = not shadow.authorized
    checks["active_requires_approved_compatibility"] = active.authorized
    checks["canary_allocation_is_deterministic"] = (
        canary_a == canary_b and canary_a.canary_bucket is not None
    )
    checks["critical_health_tripwire_blocks"] = not tripwire.authorized

    inner = _compatible_backend()
    inner_report = ModelCompatibilityProbe().run(inner)
    calls_before = inner.call_count
    controlled = ControlledModelBackend(
        backend=inner,
        compatibility=inner_report,
        policy=ModelRolloutPolicy(
            backend_id=inner.backend_id,
            approved_compatibility_fingerprint=inner_report.fingerprint(),
            stage=ModelRolloutStage.SHADOW,
        ),
    )
    blocked = False
    try:
        request = ModelRequest(
            task_id=uuid4(),
            trace_id=uuid4(),
            messages=(
                ModelMessage(
                    role=MessageRole.USER,
                    content="phase13 verifier",
                ),
            ),
        )
        controlled.generate(request)
    except ModelBackendError as exc:
        blocked = exc.code is ModelBackendErrorCode.ROLLOUT_BLOCKED
    checks["rollout_block_prevents_inner_model_call"] = blocked and inner.call_count == calls_before

    with TemporaryDirectory(prefix="luna-phase13-verifier-") as temp:
        root = Path(temp)
        workspace = root / "workspace"
        workspace.mkdir()
        failing = _FailingBackend(
            code=ModelBackendErrorCode.TIMEOUT,
            retryable=True,
        )
        harness = _build_runtime(
            workspace=workspace,
            state_root=root / "state",
            backend=failing,
        )
        runtime_request = _request(
            workspace,
            allowed_tools=("filesystem.read_text",),
        )
        outcome = harness.runtime.run(
            request=runtime_request,
            tool_policy=_policy(allowed_tools=("filesystem.read_text",)),
        )
        checks["retryable_backend_failure_suspends_no_retry"] = (
            outcome.stop_reason is RuntimeStopReason.RESOURCE_SUSPENDED
            and outcome.usage.model_calls == 1
            and outcome.usage.tool_calls == 0
            and failing.calls == 1
            and any("never blindly retried" in reason for reason in outcome.reasons)
        )

    non_loopback_blocked = False
    try:
        LocalOpenAICompatibleBackend(
            endpoint="https://example.com/v1/chat/completions",
            model="forbidden",
        )
    except ValueError:
        non_loopback_blocked = True
    checks["live_probe_adapter_remains_loopback_only"] = non_loopback_blocked

    phase12g = json.loads((ROOT / "phase_12g_verification.json").read_text(encoding="utf-8"))
    checks["phase12g_foundation_remains_locked"] = (
        phase12g.get("status") == "PASS"
        and phase12g.get("suite_sha256") == EXPECTED_PHASE12G_SUITE_SHA
        and RUNTIME_CONFORMANCE_SUITE_SHA256 == EXPECTED_PHASE12G_SUITE_SHA
    )
    checks["metadata_hashes_current"] = _metadata_integrity()

    payload = {
        "phase": "13",
        "checks": checks,
        "compatibility_fingerprint": report.fingerprint(),
        "missing_files": missing,
        "status": "PASS" if all(checks.values()) else "BLOCKED",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
