from __future__ import annotations

import ctypes
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from luna.neural import native_worker_process as legacy_native
from luna.parallel_cognition import native_abi_v2

ROOT = Path(__file__).resolve().parents[1]

LEGACY_CONTRACT = ROOT / "native" / "neural_bridge" / "bridge_contract.json"
LEGACY_SOURCE = ROOT / "native" / "neural_bridge" / "luna_nr2b_shim_harmony.cpp"
LEGACY_BUILD = ROOT / "scripts" / "build_neural_native_bridge.ps1"

C011_V2_CONTRACT = (
    ROOT / "native" / "neural_bridge" / "c011_v2" / "bridge_contract.json"
)
C011_V2_SOURCE = (
    ROOT
    / "native"
    / "neural_bridge"
    / "c011_v2"
    / "luna_c011_nr2b_shim_harmony_v2.cpp"
)
C011_V2_BUILD = ROOT / "scripts" / "build_c011_neural_native_bridge_v2.ps1"


class _FakeFunction:
    def __init__(self, callback: object) -> None:
        self._callback = callback
        self.argtypes: list[object] = []
        self.restype: object = None

    def __call__(self, *args: object) -> object:
        callback = self._callback
        assert callable(callback)
        return callback(*args)


class _FakeAbiV2Library:
    def __init__(self, *, version: int = 2) -> None:
        self.created_batch: int | None = None
        self.destroyed = False
        self.luna_nr2b_abi_version = _FakeFunction(lambda: version)
        self.luna_nr2b_engine_create_v2 = _FakeFunction(self._create_v2)
        self.luna_nr2b_generate_v2 = _FakeFunction(self._generate_v2)
        self.luna_nr2b_engine_destroy = _FakeFunction(self._destroy)

    def _create_v2(self, *args: object) -> int:
        self.created_batch = int(args[4])
        ctypes.cast(args[5], ctypes.POINTER(ctypes.c_void_p))[0] = 1234
        return 0

    @staticmethod
    def _generate_v2(*args: object) -> int:
        raw = b"<|channel|>final<|message|>Ready.<|return|>"
        ctypes.memmove(args[3], raw, len(raw))
        ctypes.cast(args[5], ctypes.POINTER(ctypes.c_size_t))[0] = len(raw)
        ctypes.cast(args[6], ctypes.POINTER(ctypes.c_uint64))[0] = 11
        ctypes.cast(args[7], ctypes.POINTER(ctypes.c_uint64))[0] = 7
        ctypes.cast(args[8], ctypes.POINTER(ctypes.c_uint64))[0] = 18
        return 0

    def _destroy(self, _engine: object) -> None:
        self.destroyed = True


def test_common_v1_python_native_seam_remains_legacy_only() -> None:
    assert not hasattr(legacy_native, "NativeTokenUsage")
    assert not hasattr(legacy_native, "DirectNativeGeneration")

    parameters = inspect.signature(legacy_native._DirectShim.start).parameters

    assert tuple(parameters) == (
        "self",
        "runtime_dir",
        "model_path",
        "cpu_threads",
        "max_context_tokens",
    )
    assert "batch_size" not in parameters


def test_c011_v2_adapter_uses_versioned_entrypoints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _FakeAbiV2Library()

    monkeypatch.setattr(
        native_abi_v2.ctypes,
        "CDLL",
        lambda _path: library,
    )

    shim = native_abi_v2.NativeAbiV2Shim(
        shim_path=tmp_path / "c011-v2-shim.dll"
    )

    shim.start(
        runtime_dir=tmp_path,
        model_path=tmp_path / "model.gguf",
        cpu_threads=4,
        max_context_tokens=512,
        batch_size=128,
    )

    generation = shim.generate(
        prompt="hello",
        max_output_tokens=64,
    )

    shim.close()

    assert library.created_batch == 128
    assert library.destroyed is True
    assert generation.text == "Ready."
    assert generation.usage == native_abi_v2.NativeTokenUsage(
        input_tokens=11,
        output_tokens=7,
        total_tokens=18,
    )


def test_c011_v2_adapter_rejects_non_v2_bridge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _FakeAbiV2Library(version=1)

    monkeypatch.setattr(
        native_abi_v2.ctypes,
        "CDLL",
        lambda _path: library,
    )

    shim = native_abi_v2.NativeAbiV2Shim(
        shim_path=tmp_path / "wrong-version.dll"
    )

    with pytest.raises(RuntimeError, match="ABI version mismatch"):
        shim.start(
            runtime_dir=tmp_path,
            model_path=tmp_path / "model.gguf",
            cpu_threads=4,
            max_context_tokens=512,
            batch_size=128,
        )


def test_bridge_contracts_are_physically_and_semantically_isolated() -> None:
    legacy = json.loads(LEGACY_CONTRACT.read_text(encoding="utf-8"))
    c011_v2 = json.loads(C011_V2_CONTRACT.read_text(encoding="utf-8"))

    legacy_hash = hashlib.sha256(
        LEGACY_SOURCE.read_bytes()
    ).hexdigest().upper()

    c011_v2_hash = hashlib.sha256(
        C011_V2_SOURCE.read_bytes()
    ).hexdigest().upper()

    assert legacy["abi_version"] == 1
    assert legacy_hash == (
        "6D130A9B53B6014ECBAE91276E15478E4424DE7EA72CCFC35E087D8DDAFA8FF1"
    )

    assert set(legacy["required_exports"]) == {
        "luna_nr2b_abi_version",
        "luna_nr2b_engine_create",
        "luna_nr2b_generate",
        "luna_nr2b_engine_destroy",
    }

    assert c011_v2["abi_version"] == 2
    assert c011_v2_hash == (
        "D0054F5773890A17123F9764774D00C941C186E3B0F50E9244224E8F581D077A"
    )

    assert c011_v2["bridge_source"] == (
        "native/neural_bridge/c011_v2/"
        "luna_c011_nr2b_shim_harmony_v2.cpp"
    )

    isolation = c011_v2["isolation"]

    assert isolation["common_v1_bridge_replaced"] is False
    assert isolation["common_v1_python_transport_modified"] is False
    assert isolation["ultra_path_protected"] is True

    upstream = c011_v2["upstream_c011"]

    assert upstream["tip_commit"] == (
        "a4bb9f20abe2a2eff1227fb6f76f008c1c2b0e5a"
    )
    assert upstream["abi_v2_origin_commit"] == (
        "00a684f600e5dba74ce7e991e4583af6bc8b0bab"
    )
    assert upstream["source_sha256"] == (
        "D0054F5773890A17123F9764774D00C941C186E3B0F50E9244224E8F581D077A"
    )

    upstream_verification = upstream["verification"]

    assert upstream_verification[
        "historical_v1_full_chain_proof_locked"
    ] is True

    assert upstream_verification[
        "current_v2_real_proof_locked"
    ] is True

    assert upstream_verification["current_v2_proof_status"] == (
        "PASS_C011_NATIVE_ABI_V2_ENGINE_NATIVE_USAGE_FULL_CHAIN"
    )

    assert upstream_verification[
        "current_v2_repo_built_bridge_sha256"
    ] == (
        "E3CE30308489D2C1CC75B020AFE38A013DD2262B48C4ACE0FB07A190FF429466"
    )

    local_verification = c011_v2["verification"]

    assert local_verification == {
        "reconciled_isolated_build_proof_locked": False,
        "upstream_c011_proof_reused_as_local_proof": False,
        "primary_path_promoted": False,
        "persistent_residency_claimed": False,
        "gpu_budget_enforcement_claimed": False,
        "identity_test_executed": False,
    }

    assert not any(c011_v2["authority"].values())


def test_v1_and_c011_v2_build_governance_are_separate() -> None:
    legacy = LEGACY_BUILD.read_text(encoding="utf-8")
    c011_v2 = C011_V2_BUILD.read_text(encoding="utf-8")

    assert "c011_v2" not in legacy
    assert "luna_c011_neural_bridge_v2.dll" not in legacy

    assert (
        r"native\neural_bridge\c011_v2\bridge_contract.json"
        in c011_v2
    )

    assert "luna_c011_neural_bridge_v2.dll" in c011_v2
