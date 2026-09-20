"""Trusted tool metadata and the deterministic approval rule."""

from collections.abc import Mapping
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from jev_router.models import Model


class ToolDefinition(Model):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    domain: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str = Field(min_length=1)
    read_only: bool = False
    risk: Literal["low", "medium", "high"] = "medium"
    required_arguments: tuple[str, ...] = ()
    input_schema: dict[str, JsonValue] = Field(default_factory=dict)
    output_schema: dict[str, JsonValue] = Field(default_factory=dict)


ALWAYS_APPROVAL = frozenset(
    {
        "files_delete",
        "github_create_issue",
        "browser_submit_form",
        "calendar_create_event",
        "calendar_delete_event",
    }
)


def tool_requires_approval(name: str, catalog: Mapping[str, ToolDefinition]) -> bool:
    definition = catalog[name]
    return name in ALWAYS_APPROVAL or not definition.read_only or definition.risk == "high"
