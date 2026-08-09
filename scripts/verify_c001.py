"""Deterministic C-001 Adaptive Knowledge Retrieval gate."""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from luna.capabilities import (  # noqa: E402
    CapabilityStatus,
    EvidenceFreshness,
    build_canonical_capability_registry,
)
from luna.retrieval import (  # noqa: E402
    AdaptiveKnowledgeRouter,
    KnowledgeRequestProfile,
    KnowledgeSource,
    KnowledgeUncertainty,
    KnowledgeVolatility,
    RetrievalDecision,
)

REQUIRED_FILES = (
    "src/luna/retrieval/__init__.py",
    "src/luna/retrieval/models.py",
    "src/luna/retrieval/router.py",
    "tests/test_c001_adaptive_knowledge_retrieval.py",
    "scripts/verify_c001.py",
    "docs/rfcs/RFC-C001_ADAPTIVE_KNOWLEDGE_RETRIEVAL.md",
    "docs/C001_ADAPTIVE_KNOWLEDGE_RETRIEVAL_REPORT.md",
    "c001_verification.json",
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
    capability = str(manifest.get("capability", ""))
    if re.fullmatch(r"C-[0-9]{3}", capability) is None:
        return False
    if manifest.get("capability_status") not in {"IMPLEMENTED_UNVERIFIED", "VERIFIED"}:
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


def _profile(**updates: object) -> KnowledgeRequestProfile:
    payload: dict[str, object] = {
        "task_id": uuid4(),
        "query": "C-001 verifier fixture",
    }
    payload.update(updates)
    return KnowledgeRequestProfile.model_validate(payload)


def main() -> int:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    checks: dict[str, bool] = {
        "required_files_present": not missing,
        "metadata_integrity": _metadata_integrity(),
    }

    registry = build_canonical_capability_registry()
    c001 = registry.get("C-001")
    checks["c001_implemented_unverified_not_self_verified"] = bool(
        c001.status is CapabilityStatus.IMPLEMENTED_UNVERIFIED
        and c001.evidence_freshness is EvidenceFreshness.PARTIAL
        and c001.preferred_prerequisites == ("C-002",)
        and c001.implementation_components
        and c001.verifier_refs
        and c001.evidence_refs
    )

    router = AdaptiveKnowledgeRouter()
    stable = router.route(
        _profile(
            volatility=KnowledgeVolatility.STABLE,
            uncertainty=KnowledgeUncertainty.LOW,
            internal_knowledge_sufficient=True,
        )
    )
    context = router.route(
        _profile(
            working_context_sufficient=True,
            volatility=KnowledgeVolatility.STABLE,
            uncertainty=KnowledgeUncertainty.LOW,
        )
    )
    memory = router.route(_profile(user_specific=True, verified_memory_available=True))
    rag = router.route(_profile(document_specific=True, project_rag_available=True))
    api = router.route(
        _profile(
            currentness_required=True,
            volatility=KnowledgeVolatility.DYNAMIC,
            structured_data_suitable=True,
            structured_api_available=True,
            research_gateway_available=True,
        )
    )
    research = router.route(
        _profile(
            uncertainty=KnowledgeUncertainty.HIGH,
            research_gateway_available=True,
        )
    )
    contradiction = router.route(
        _profile(
            contradictory_evidence=True,
            working_context_sufficient=True,
            research_gateway_available=True,
        )
    )
    no_fresh_source = router.route(
        _profile(
            currentness_required=True,
            volatility=KnowledgeVolatility.DYNAMIC,
            internal_knowledge_sufficient=True,
        )
    )
    private_no_public_fallback = router.route(
        _profile(user_specific=True, research_gateway_available=True)
    )

    checks["stable_known_uses_internal_without_unnecessary_retrieval"] = bool(
        stable.decision is RetrievalDecision.ANSWER_DIRECT
        and stable.primary_source is KnowledgeSource.INTERNAL
    )
    checks["working_context_is_used_when_sufficient"] = bool(
        context.decision is RetrievalDecision.ANSWER_DIRECT
        and context.primary_source is KnowledgeSource.WORKING_CONTEXT
    )
    checks["user_specific_uses_verified_memory"] = (
        memory.primary_source is KnowledgeSource.VERIFIED_MEMORY
    )
    checks["document_specific_uses_project_rag"] = (
        rag.primary_source is KnowledgeSource.PROJECT_RAG
    )
    checks["current_structured_prefers_api"] = bool(
        api.primary_source is KnowledgeSource.STRUCTURED_API
        and api.requires_freshness
        and api.requires_citation
    )
    checks["high_uncertainty_routes_to_research"] = bool(
        research.primary_source is KnowledgeSource.RESEARCH_GATEWAY
        and research.requires_freshness
        and research.requires_citation
    )
    checks["contradictory_evidence_stops_and_reinspects"] = bool(
        contradiction.decision is RetrievalDecision.STOP_REINSPECT
        and contradiction.primary_source is None
    )
    checks["current_request_without_fresh_source_stops"] = (
        no_fresh_source.decision is RetrievalDecision.STOP_REINSPECT
    )
    checks["user_specific_does_not_leak_to_public_research"] = (
        private_no_public_fallback.decision is RetrievalDecision.STOP_REINSPECT
    )
    checks["retrieval_has_no_runtime_or_memory_commit_authority"] = bool(
        research.runtime_authority is False
        and research.external_action_allowed is False
        and research.automatic_memory_commit_allowed is False
        and research.memory_review_required is True
    )
    checks["routing_is_deterministic"] = api == router.route(
        _profile(
            task_id=api.task_id,
            currentness_required=True,
            volatility=KnowledgeVolatility.DYNAMIC,
            structured_data_suitable=True,
            structured_api_available=True,
            research_gateway_available=True,
        )
    )

    passed = all(checks.values())
    payload = {
        "capability": "C-001",
        "name": "Adaptive Knowledge Retrieval",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "missing_files": missing,
        "network_execution": False,
        "runtime_authority": False,
        "external_action_authority": False,
        "automatic_memory_commit": False,
    }
    verification_path = ROOT / "c001_verification.json"
    existing_payload: object | None = None
    if verification_path.is_file():
        try:
            existing_payload = json.loads(verification_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing_payload = None
    if existing_payload != payload:
        verification_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
