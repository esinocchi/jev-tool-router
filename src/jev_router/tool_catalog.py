"""Trusted local catalog and inert execution. No service clients belong here."""

from types import MappingProxyType
from typing import Literal

from pydantic import ConfigDict, JsonValue

from jev_router.models import MockArguments, MockResult, Model, RoutingDecision, ToolDomain


class ToolDefinition(Model):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    domain: ToolDomain
    description: str
    read_only: bool
    risk: Literal["low", "medium", "high"]
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]


def tool(
    name: str,
    domain: ToolDomain,
    description: str,
    read_only: bool = True,
    risk: Literal["low", "medium", "high"] = "low",
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        domain=domain,
        description=description,
        read_only=read_only,
        risk=risk,
        input_schema=MockArguments.model_json_schema(),
        output_schema=MockResult.model_json_schema(),
    )


_TOOLS = (
    tool("github_search_code", "github", "Search source code across GitHub repositories by query."),
    tool("github_read_file", "github", "Read a known file path in a specified GitHub repository."),
    tool(
        "github_search_issues",
        "github",
        "Find or inspect GitHub issues by query, status, or number.",
    ),
    tool(
        "github_create_issue",
        "github",
        "Create a new issue in a specified GitHub repository.",
        False,
        "high",
    ),
    tool("browser_search_web", "browser", "Search the public web for information or websites."),
    tool("browser_open_page", "browser", "Open and read a specified web page URL."),
    tool(
        "browser_click",
        "browser",
        "Click a specified element on the current web page; may change state.",
        False,
        "medium",
    ),
    tool(
        "browser_submit_form",
        "browser",
        "Submit a web form with supplied information.",
        False,
        "high",
    ),
    tool("files_search", "files", "Find local files by name, path pattern, or content query."),
    tool("files_read", "files", "Read contents of a known local file path."),
    tool(
        "files_write",
        "files",
        "Create or replace contents at a specified local file path.",
        False,
        "medium",
    ),
    tool("files_delete", "files", "Delete a specified local file.", False, "high"),
    tool(
        "calendar_search_events",
        "calendar",
        "Find or read calendar events by title, date, or participant.",
    ),
    tool(
        "calendar_check_availability",
        "calendar",
        "Check free and busy time over a specified interval.",
    ),
    tool(
        "calendar_create_event",
        "calendar",
        "Create a calendar event with title, time, and participants.",
        False,
        "high",
    ),
    tool(
        "calendar_delete_event",
        "calendar",
        "Delete or cancel an identified calendar event.",
        False,
        "high",
    ),
)
CATALOG = MappingProxyType({t.name: t for t in _TOOLS})
if len(CATALOG) != len(_TOOLS):
    raise ValueError("Duplicate catalog name")

ALWAYS_APPROVAL = frozenset(
    {
        "files_delete",
        "github_create_issue",
        "browser_submit_form",
        "calendar_create_event",
        "calendar_delete_event",
    }
)


def tool_requires_approval(name: str) -> bool:
    definition = CATALOG[name]
    return name in ALWAYS_APPROVAL or not definition.read_only or definition.risk == "high"


def execute_mock(decision: RoutingDecision, *, approved: bool = False) -> MockResult:
    if decision.outcome != "route" or decision.selected_tool not in CATALOG:
        raise ValueError("Only a valid routed catalog tool can be simulated")
    assert decision.selected_tool is not None
    definition = CATALOG[decision.selected_tool]
    if definition.domain != decision.selected_domain:
        raise ValueError("Tool and domain mismatch")
    if (
        decision.requires_approval or tool_requires_approval(definition.name)
    ) and approved is not True:
        raise PermissionError("Explicit approved=True is required")
    return MockResult(
        tool=definition.name, arguments=MockArguments(target=f"mock://{definition.name}")
    )
