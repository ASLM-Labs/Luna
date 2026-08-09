"""Deterministic C-002 capability-lineage gate."""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import (  # noqa: E402
    CapabilityRegistry,
    CapabilityStatus,
    EvidenceFreshness,
    build_canonical_capability_registry,
)

REQUIRED_FILES = (
    "src/luna/capabilities/__init__.py",
    "src/luna/capabilities/models.py",
    "src/luna/capabilities/registry.py",
    "src/luna/capabilities/catalog.py",
    "tests/test_c002_capability_lineage.py",
    "scripts/verify_c002.py",
    "docs/rfcs/RFC-C002_CAPABILITY_LINEAGE_MAPPING.md",
    "docs/C002_CAPABILITY_LINEAGE_REPORT.md",
    "c002_verification.json",
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
    if manifest.get("phase") != "19F":
        return False
    if manifest.get("capability") != "C-002":
        return False
    if manifest.get("capability_status") != "IMPLEMENTED_UNVERIFIED":
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
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            return False
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


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
    }

    registry = build_canonical_capability_registry()
    ids = tuple(record.capability_id for record in registry.records)
    checks["canonical_identity_inventory_c001_c012"] = ids == tuple(
        f"C-{index:03d}" for index in range(1, 13)
    )
    checks["canonical_roadmap_titles_preserved"] = bool(
        registry.get("C-005").name == "Experience <-> Capability Flywheel"
        and registry.get("C-006").name == "Vicarious Experience Inheritance"
        and registry.get("C-007").name == "Debugging Capability Decomposition & Transfer"
        and registry.get("C-009").name == "Cross-Agent Experience Mining"
    )

    c002 = registry.get("C-002")
    checks["c002_implemented_unverified_not_self_verified"] = bool(
        c002.status is CapabilityStatus.IMPLEMENTED_UNVERIFIED
        and c002.evidence_freshness is EvidenceFreshness.PARTIAL
        and c002.implementation_components
        and c002.verifier_refs
        and c002.evidence_refs
    )
    checks["runtime_and_promotion_authority_remain_absent"] = bool(
        "no runtime or promotion authority" in registry.get("C-001").authority_boundary
        and "cannot grant runtime authority" in c002.authority_boundary
        and "promote a model" in c002.authority_boundary
    )

    c002_impact = registry.blast_radius("C-002")
    checks["blast_radius_query_is_nonempty_and_deterministic"] = bool(
        c002_impact.direct_dependents
        and c002_impact == registry.blast_radius("C-002")
    )

    invalid_unknown_blocked = False
    try:
        CapabilityRegistry(
            (
                registry.get("C-001").model_copy(
                    update={"hard_prerequisites": ("C-999",)}
                ),
            )
        )
    except ValueError:
        invalid_unknown_blocked = True
    checks["unknown_dependency_is_rejected"] = invalid_unknown_blocked

    report_text = (ROOT / "docs" / "C002_CAPABILITY_LINEAGE_REPORT.md").read_text(
        encoding="utf-8"
    )
    checks["roadmap_identity_conflict_is_explicit_not_silently_remapped"] = bool(
        "C-005" in report_text
        and "C-006" in report_text
        and "C-007" in report_text
        and "C-009" in report_text
        and "not silently remap" in report_text
    )

    passed = all(checks.values())
    payload = {
        "capability": "C-002",
        "name": "Capability Lineage & Dependency Mapping",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "missing_files": missing,
        "runtime_authority": False,
        "promotion_authority": False,
        "automatic_roadmap_mutation": False,
    }
    (ROOT / "c002_verification.json").write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
