"""Hard runtime budgets for one Luna task execution."""

from __future__ import annotations

from pydantic import Field, model_validator

from luna.contracts.base import LunaContractModel


class RuntimeBudget(LunaContractModel):
    """Bound one runtime execution before any model or tool side effect."""

    max_steps: int = Field(default=8, ge=1, le=256)
    max_model_calls: int = Field(default=8, ge=0, le=512)
    max_tool_calls: int = Field(default=16, ge=0, le=1024)
    max_replans: int = Field(default=3, ge=0, le=64)
    max_elapsed_seconds: int = Field(default=1800, ge=1, le=86400)
    max_model_input_tokens: int = Field(default=16000, ge=0, le=2000000)
    max_model_request_estimated_tokens: int = Field(default=32768, ge=0, le=2000000)
    max_model_output_tokens: int = Field(default=8000, ge=0, le=1000000)
    max_changed_files: int = Field(default=0, ge=0, le=10000)
    max_added_lines: int = Field(default=0, ge=0, le=1000000)
    max_deleted_lines: int = Field(default=0, ge=0, le=1000000)
    max_questions: int = Field(default=2, ge=0, le=100)
    max_network_requests: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def validate_change_budget(self) -> RuntimeBudget:
        if self.max_changed_files == 0 and any(
            (self.max_added_lines, self.max_deleted_lines)
        ):
            raise ValueError("line change budgets require max_changed_files greater than zero")
        if self.max_changed_files > 0 and not any(
            (self.max_added_lines, self.max_deleted_lines)
        ):
            raise ValueError("write budget requires at least one non-zero line budget")
        return self

    @classmethod
    def controlled_write(
        cls,
        *,
        max_changed_files: int = 5,
        max_added_lines: int = 500,
        max_deleted_lines: int = 500,
        **overrides: int,
    ) -> RuntimeBudget:
        """Create an explicit bounded-write budget; read-only remains the default."""
        payload: dict[str, object] = {
            "max_changed_files": max_changed_files,
            "max_added_lines": max_added_lines,
            "max_deleted_lines": max_deleted_lines,
        }
        payload.update(overrides)
        return cls.model_validate(payload)
