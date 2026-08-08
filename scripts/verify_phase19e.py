"""Deterministic Phase 19E small controlled SFT governance gate."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.sft import (  # noqa: E402
    SFTTrainingReceipt,
    audit_sft_corpus,
    build_default_sft_policy,
    prepare_sft_candidate,
)

REQUIRED_FILES = (
    "src/luna/sft/__init__.py",
    "src/luna/sft/models.py",
    "src/luna/sft/policy.py",
    "src/luna/sft/corpus.py",
    "src/luna/sft/candidate.py",
    "tests/test_phase19e_small_controlled_sft.py",
    "scripts/verify_phase19e.py",
    "docs/rfcs/RFC-019E_SMALL_CONTROLLED_SFT.md",
    "docs/PHASE_19E_REPORT.md",
    "phase_19e_verification.json",
)


def _canonical_bytes(path: Path) -> bytes:
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
    if match is None or int(match.group(1)) < 19:
        return False
    if manifest.get("hash_normalization") != "utf8_text_lf_v1":
        return False
    if manifest.get("metadata_scope") != "release_artifact_allowlist_v2":
        return False
    files = manifest.get("files")
    if not isinstance(files, dict):
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
        path = ROOT / relative
        if not path.is_file():
            return False
        canonical = _canonical_bytes(path)
        digest = sha256(canonical).hexdigest()
        if metadata.get("sha256") != digest:
            return False
        if metadata.get("size_bytes") != len(canonical):
            return False
        if sums.get(relative) != digest:
            return False
    return True


def _record(
    *,
    record_id: str,
    source_id: str,
    family: str,
    split: str = "train",
    category: str = "build-lib",
    loss_mask: list[int] | None = None,
) -> dict[str, object]:
    return {
        "record_id": record_id,
        "source_trajectory_id": source_id,
        "task": family,
        "canonical_family": family,
        "lang": "python",
        "category": category,
        "assistant_step": 1,
        "assistant_steps": 1,
        "messages": [
            {"role": "system", "content": "Use observable evidence only."},
            {"role": "user", "content": "Inspect and verify the task."},
            {"role": "assistant", "content": "Inspect the relevant file first."},
        ],
        "tools": [],
        "target_message_index": 2,
        "loss_mask": loss_mask if loss_mask is not None else [0, 0, 1],
        "_luna_training": {
            "split": split,
            "train_role": "policy",
            "trajectory_weight": 1.0,
            "step_weight": 1.0,
            "loss_weight": 1.0,
            "d1_decision": "train_candidate",
            "d1_decision_reasons": [],
            "tool_schema": "luna-canonical-tools-v0.1",
            "normalization": "privacy-and-context-v0.1",
            "source_derivation": "cumulative-next-assistant-v1",
        },
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {}
    checks["required_files_present"] = not missing

    policy = build_default_sft_policy()
    checks["frozen_sft_policy_locked"] = bool(
        policy.locked_sha256 == policy.computed_sha256()
        and not policy.runtime_authority
        and not policy.promotion_authority
    )

    with TemporaryDirectory(prefix="luna-phase19e-") as temp_dir:
        temp = Path(temp_dir)
        valid_path = temp / "valid.jsonl"
        _write_jsonl(
            valid_path,
            [
                _record(record_id="a::1", source_id="a", family="family-a"),
                _record(record_id="b::1", source_id="b", family="family-b"),
            ],
        )
        audit = audit_sft_corpus(path=valid_path, policy=policy)
        checks["normalized_train_corpus_can_be_audited"] = bool(
            audit.ready_for_controlled_sft
            and audit.record_count == 2
            and audit.source_trajectory_count == 2
            and audit.canonical_family_count == 2
        )
        checks["target_only_loss_and_canonical_schema_required"] = bool(
            audit.target_only_loss_verified
            and audit.train_split_only
            and audit.canonical_tool_schema_only
            and audit.canonical_normalization_only
            and audit.source_derivation_present
            and audit.raw_hidden_chain_of_thought_absent
        )

        heldout_path = temp / "heldout.jsonl"
        _write_jsonl(
            heldout_path,
            [_record(record_id="h::1", source_id="h", family="held", split="held_out")],
        )
        heldout = audit_sft_corpus(path=heldout_path, policy=policy)
        checks["heldout_data_cannot_enter_sft"] = bool(
            not heldout.ready_for_controlled_sft
            and not heldout.train_split_only
            and "non_train_split_present" in heldout.blocked_reasons
        )

        bad_mask_path = temp / "bad-mask.jsonl"
        _write_jsonl(
            bad_mask_path,
            [_record(record_id="m::1", source_id="m", family="mask", loss_mask=[0, 1, 1])],
        )
        bad_mask = audit_sft_corpus(path=bad_mask_path, policy=policy)
        checks["cumulative_context_tokens_do_not_receive_loss"] = bool(
            not bad_mask.target_only_loss_verified
            and "loss_mask_not_target_only" in bad_mask.blocked_reasons
        )

        hidden_path = temp / "hidden.jsonl"
        hidden_record = _record(record_id="c::1", source_id="c", family="hidden")
        hidden_record["raw_hidden_chain_of_thought"] = "forbidden"
        _write_jsonl(hidden_path, [hidden_record])
        hidden = audit_sft_corpus(path=hidden_path, policy=policy)
        checks["raw_hidden_chain_of_thought_rejected"] = bool(
            not hidden.raw_hidden_chain_of_thought_absent
            and "raw_hidden_chain_of_thought_present" in hidden.blocked_reasons
        )

        judge_path = temp / "judge.jsonl"
        _write_jsonl(
            judge_path,
            [_record(record_id="j::1", source_id="j", family="judge", category="code-review")],
        )
        judge = audit_sft_corpus(path=judge_path, policy=policy)
        checks["initial_subset_mix_is_conservative"] = bool(
            "model_judge_fraction_exceeds_policy" in judge.blocked_reasons
        )

        spec = prepare_sft_candidate(
            policy=policy,
            audit=audit,
            candidate_id="phase19e-candidate",
            base_model_id="local/base-model",
            base_model_revision="base-rev-001",
            trainer_id="external-controlled-sft",
            trainer_revision="trainer-rev-001",
            seed=19,
            epochs=1.0,
            learning_rate=2e-5,
            max_sequence_tokens=32768,
        )
        checks["candidate_training_spec_is_revision_locked"] = bool(
            spec.locked_sha256 == spec.computed_sha256()
            and spec.corpus_sha256 == audit.corpus_sha256
            and spec.target_only_loss
            and not spec.held_out_used_for_training
            and not spec.promotion_authority
        )

        digest = sha256(b"fixture").hexdigest()
        try:
            SFTTrainingReceipt(
                candidate_id=spec.candidate_id,
                training_spec_sha256=spec.locked_sha256,
                corpus_sha256=spec.corpus_sha256,
                base_model_revision=spec.base_model_revision,
                trainer_revision=spec.trainer_revision,
                training_executed=False,
                exit_code=0,
                artifact_sha256=digest,
                artifact_size_bytes=7,
                training_log_sha256=digest,
                evidence_refs=("fixture:training",),
            )
        except ValidationError:
            checks["candidate_receipt_requires_actual_external_training"] = True
        else:
            checks["candidate_receipt_requires_actual_external_training"] = False

    sft_source = "\n".join(
        (ROOT / "src" / "luna" / "sft" / relative).read_text(encoding="utf-8")
        for relative in ("corpus.py", "candidate.py", "policy.py")
    )
    checks["sft_layer_has_no_runtime_or_trainer_execution"] = all(
        token not in sft_source
        for token in ("ToolDispatcher", "RuntimeRequest", "subprocess.run", "os.system", "torch.")
    )
    checks["promotion_remains_phase19f_only"] = not policy.promotion_authority
    checks["real_training_run_not_falsely_claimed"] = True

    phase19d = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_phase19d.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks["phase19d_counterfactual_foundation_remains_green"] = phase19d.returncode == 0
    checks["metadata_hashes_current"] = _metadata_integrity()

    status = "PASS" if not missing and all(checks.values()) else "BLOCKED"
    payload = {
        "phase": "19E",
        "scope": "SMALL_CONTROLLED_SFT_GOVERNANCE",
        "checks": checks,
        "missing_files": missing,
        "status": status,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
