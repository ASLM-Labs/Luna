from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from luna.conformance.runtime_executor import _build_runtime, _policy, _request
from luna.context import (
    ContextInterpretation,
    ContextLayer,
    ContextSource,
    ContextSourceKind,
    LayeredContextCandidate,
    LayeredContextEntry,
)
from luna.context.window import render_context_entry
from luna.modeling import MessageRole, ModelFinishReason, ModelRequest, ModelResponse
from luna.runtime.policy_agent import ModelPolicyAgent
from luna.skills import (
    SkillActivationError,
    SkillActivationProjector,
    SkillDiscoveryIndex,
    SkillPackageError,
    SkillProvenance,
    SkillRegistry,
    SkillScope,
    SkillTrustState,
    load_skill_package,
)


def _write_skill(
    root: Path,
    *,
    name: str = "code-review",
    description: str = "Review Python code and explain defects. Use for code review tasks.",
    allowed_tools: str | None = None,
    body: str = "Inspect the code before proposing changes.",
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "license: Apache-2.0",
        "compatibility: Luna local runtime",
        "metadata:",
        "  author: aslm-tests",
        '  version: "1.0"',
    ]
    if allowed_tools is not None:
        lines.append(f"allowed-tools: {allowed_tools}")
    lines.extend(("---", "", body, ""))
    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
    return skill_dir


def _trusted_version(tmp_path: Path, *, scope: SkillScope = SkillScope.USER):
    package = load_skill_package(_write_skill(tmp_path / "skills"))
    registry = SkillRegistry()
    version = registry.install(
        package,
        scope=scope,
        provenance=SkillProvenance.USER_AUTHORED,
        trust_state=SkillTrustState.TRUSTED,
    )
    return package, registry, version


def test_package_parses_canonical_frontmatter_and_non_authoritative_hints(
    tmp_path: Path,
) -> None:
    skill_dir = _write_skill(
        tmp_path,
        allowed_tools="filesystem.write_text filesystem.read_text",
    )
    package = load_skill_package(skill_dir)

    assert package.name == "code-review"
    assert package.metadata == (("author", "aslm-tests"), ("version", "1.0"))
    assert package.allowed_tool_hints == (
        "filesystem.write_text",
        "filesystem.read_text",
    )
    assert package.body == "Inspect the code before proposing changes."
    assert len(package.package_digest) == 64
    payload = package.model_dump(mode="json")
    assert "tool_policy" not in payload
    assert "authority" not in payload


def test_package_rejects_directory_name_mismatch_and_unknown_field(tmp_path: Path) -> None:
    wrong = _write_skill(tmp_path, name="code-review")
    renamed = tmp_path / "renamed"
    wrong.rename(renamed)
    with pytest.raises(SkillPackageError, match="must match"):
        load_skill_package(renamed)

    invalid = tmp_path / "bad-skill"
    invalid.mkdir()
    (invalid / "SKILL.md").write_text(
        "---\nname: bad-skill\ndescription: test\nrequires: shell\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillPackageError, match="unexpected"):
        load_skill_package(invalid)


def test_package_rejects_unsupported_yaml_construct(tmp_path: Path) -> None:
    skill_dir = tmp_path / "yaml-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: yaml-skill\ndescription: >\n  multiline\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillPackageError):
        load_skill_package(skill_dir)


def test_package_digest_changes_when_resource_changes(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path)
    refs = skill_dir / "references"
    refs.mkdir()
    reference = refs / "GUIDE.md"
    reference.write_text("version one\n", encoding="utf-8")
    first = load_skill_package(skill_dir)
    reference.write_text("version two\n", encoding="utf-8")
    second = load_skill_package(skill_dir)

    assert first.package_digest != second.package_digest
    assert first.resources[0].relative_path == "references/GUIDE.md"
    assert first.resources[0].sha256 != second.resources[0].sha256


def test_package_symlink_is_rejected_when_platform_allows_creation(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path)
    target = skill_dir / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = skill_dir / "references-link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("platform does not allow test symlink creation")
    with pytest.raises(SkillPackageError, match="symlink"):
        load_skill_package(skill_dir)


def test_registry_defaults_to_quarantine_and_versions_are_immutable(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path)
    first_package = load_skill_package(skill_dir)
    registry = SkillRegistry()
    first = registry.install(
        first_package,
        scope=SkillScope.USER,
        provenance=SkillProvenance.USER_AUTHORED,
    )
    assert first.trust_state is SkillTrustState.QUARANTINED

    same = registry.install(
        first_package,
        scope=SkillScope.USER,
        provenance=SkillProvenance.USER_AUTHORED,
        skill_id=first.skill_id,
    )
    assert same.version_id == first.version_id

    (skill_dir / "SKILL.md").write_text(
        (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        + "\nAdditional immutable guidance.\n",
        encoding="utf-8",
    )
    second_package = load_skill_package(skill_dir)
    second = registry.install(
        second_package,
        scope=SkillScope.USER,
        provenance=SkillProvenance.USER_AUTHORED,
        skill_id=first.skill_id,
    )
    assert second.skill_id == first.skill_id
    assert second.version_id != first.version_id
    assert registry.get_version(first.version_id).package == first_package


def test_discovery_filters_trust_scope_and_exposes_metadata_only(tmp_path: Path) -> None:
    package = load_skill_package(_write_skill(tmp_path / "trusted"))
    registry = SkillRegistry()
    trusted = registry.install(
        package,
        scope=SkillScope.USER,
        provenance=SkillProvenance.USER_AUTHORED,
        trust_state=SkillTrustState.TRUSTED,
    )
    quarantined = registry.install(
        package,
        scope=SkillScope.PROJECT,
        provenance=SkillProvenance.UNTRUSTED_PROJECT,
    )

    result = SkillDiscoveryIndex().search(
        query="code review",
        versions=registry.versions(),
        allowed_scopes=(SkillScope.USER, SkillScope.PROJECT),
    )
    assert tuple(item.version_id for item in result.candidates) == (trusted.version_id,)
    assert quarantined.version_id not in tuple(item.version_id for item in result.candidates)
    payload = result.candidates[0].model_dump(mode="json")
    assert "body" not in payload
    assert "resources" not in payload
    assert "allowed_tool_hints" not in payload
    assert result.authority_granted is False
    assert result.candidates[0].authority_granted is False

    hidden = SkillDiscoveryIndex().search(
        query="code review",
        versions=registry.versions(),
        allowed_scopes=(SkillScope.PROJECT,),
    )
    assert hidden.candidates == ()


def test_discovery_bounds_and_no_catalog_fallback(tmp_path: Path) -> None:
    _, registry, _ = _trusted_version(tmp_path)
    with pytest.raises(ValueError, match="blank"):
        SkillDiscoveryIndex().search(
            query="   ",
            versions=registry.versions(),
            allowed_scopes=(SkillScope.USER,),
        )
    with pytest.raises(ValueError, match="between 1 and 16"):
        SkillDiscoveryIndex().search(
            query="review",
            versions=registry.versions(),
            allowed_scopes=(SkillScope.USER,),
            limit=17,
        )
    no_match = SkillDiscoveryIndex().search(
        query="astronomy",
        versions=registry.versions(),
        allowed_scopes=(SkillScope.USER,),
    )
    assert no_match.candidates == ()


def test_activation_requires_trust_and_allowed_scope(tmp_path: Path) -> None:
    package = load_skill_package(_write_skill(tmp_path))
    registry = SkillRegistry()
    quarantined = registry.install(
        package,
        scope=SkillScope.USER,
        provenance=SkillProvenance.USER_AUTHORED,
    )
    projector = SkillActivationProjector(registry)
    with pytest.raises(SkillActivationError, match="quarantined"):
        projector.activate(
            task_id=uuid4(),
            version_id=quarantined.version_id,
            allowed_scopes=(SkillScope.USER,),
        )

    trusted = registry.install(
        package,
        scope=SkillScope.PROJECT,
        provenance=SkillProvenance.TRUSTED_PROJECT,
        trust_state=SkillTrustState.TRUSTED,
    )
    with pytest.raises(SkillActivationError, match="scope"):
        projector.activate(
            task_id=uuid4(),
            version_id=trusted.version_id,
            allowed_scopes=(SkillScope.USER,),
        )


def test_activation_projects_exact_body_as_workspace_procedural_guidance(
    tmp_path: Path,
) -> None:
    package, registry, version = _trusted_version(tmp_path)
    projector = SkillActivationProjector(registry)
    activation = projector.activate(
        task_id=uuid4(),
        version_id=version.version_id,
        allowed_scopes=(SkillScope.USER,),
    )
    candidate = projector.project(activation)

    assert activation.authority_granted is False
    assert candidate.layer is ContextLayer.WORKSPACE
    assert candidate.interpretation is ContextInterpretation.PROCEDURAL_GUIDANCE
    assert candidate.source.content_excerpt == package.body
    assert candidate.source.verified is False
    assert candidate.source.locator.startswith(f"skill://{version.version_id}/")
    assert candidate.source.metadata["skill_version_id"] == str(version.version_id)


def test_procedural_guidance_cannot_be_promoted_to_control_layers() -> None:
    source = ContextSource.from_text(
        kind=ContextSourceKind.DOCUMENT,
        locator="skill://test/guidance",
        text="Follow a bounded procedure.",
        verified=True,
    )
    for layer in (
        ContextLayer.ACTIVE,
        ContextLayer.TASK,
        ContextLayer.RUNTIME_CONTINUITY,
        ContextLayer.VERIFIED_MEMORY,
    ):
        with pytest.raises(ValidationError, match="WORKSPACE"):
            LayeredContextCandidate(
                layer=layer,
                source=source,
                interpretation=ContextInterpretation.PROCEDURAL_GUIDANCE,
                relevance_basis=(
                    "required-for-memory"
                    if layer is ContextLayer.VERIFIED_MEMORY
                    else None
                ),
            )


def test_existing_context_render_bytes_remain_unchanged_and_procedure_is_marked() -> None:
    source = ContextSource.from_text(
        kind=ContextSourceKind.DOCUMENT,
        locator="doc:test",
        text="context text",
        verified=True,
    )
    data = LayeredContextEntry(
        layer=ContextLayer.WORKSPACE,
        source=source,
        priority=50,
        required=False,
        interpretation=ContextInterpretation.DATA_ONLY,
        age_seconds=0,
    )
    procedure = data.model_copy(
        update={"interpretation": ContextInterpretation.PROCEDURAL_GUIDANCE}
    )
    assert render_context_entry(data) == "[WORKSPACE] DOCUMENT doc:test\ncontext text"
    assert render_context_entry(procedure) == (
        "[PROCEDURAL_GUIDANCE] [WORKSPACE] DOCUMENT doc:test\ncontext text"
    )
    message = ModelPolicyAgent._render_context_entries((procedure,))[0]
    assert message.role is MessageRole.TOOL
    assert message.content.startswith("[PROCEDURAL_GUIDANCE]")


class _CaptureBackend:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    @property
    def backend_id(self) -> str:
        return "minimal-skills-capture"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            request_id=request.request_id,
            backend_id=self.backend_id,
            text="No action proposed.",
            finish_reason=ModelFinishReason.STOP,
        )


def test_skill_guidance_reaches_model_without_widening_tool_policy(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
    package = load_skill_package(
        _write_skill(
            tmp_path / "skills",
            allowed_tools="filesystem.write_text",
            body="If a change is needed, write the file only after normal host approval.",
        )
    )
    registry = SkillRegistry()
    version = registry.install(
        package,
        scope=SkillScope.USER,
        provenance=SkillProvenance.USER_AUTHORED,
        trust_state=SkillTrustState.TRUSTED,
    )
    backend = _CaptureBackend()
    harness = _build_runtime(
        workspace=workspace,
        state_root=tmp_path / "state",
        backend=backend,
    )
    base_request = _request(workspace, allowed_tools=("filesystem.read_text",))
    activation = SkillActivationProjector(registry).activate(
        task_id=base_request.task_id,
        version_id=version.version_id,
        allowed_scopes=(SkillScope.USER,),
    )
    candidate = SkillActivationProjector(registry).project(activation)
    raw_request = base_request.model_dump(mode="python")
    raw_request["layered_context_candidates"] = (candidate,)
    request = type(base_request).model_validate(raw_request)
    policy = _policy(allowed_tools=("filesystem.read_text",))

    harness.runtime.run(request=request, tool_policy=policy)

    assert backend.requests
    first = backend.requests[0]
    assert any(
        "[PROCEDURAL_GUIDANCE]" in message.content
        and "normal host approval" in message.content
        for message in first.messages
    )
    available = tuple(spec.name for spec in first.available_tools)
    assert "filesystem.read_text" in available
    assert "filesystem.write_text" not in available
    assert policy.allowed_tools == ("filesystem.read_text",)
