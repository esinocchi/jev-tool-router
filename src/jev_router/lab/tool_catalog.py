"""Trusted local catalog and inert execution. No service clients belong here."""

import re
from types import MappingProxyType
from typing import Literal

from jev_router.models import (
    MockArguments,
    MockResult,
    RoutingDecision,
    ToolCallPreparation,
    ToolDomain,
)
from jev_router.tools import ToolDefinition, tool_requires_approval


def tool(
    name: str,
    domain: ToolDomain,
    description: str,
    read_only: bool = True,
    risk: Literal["low", "medium", "high"] = "low",
    required_arguments: tuple[str, ...] = (),
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        domain=domain,
        description=description,
        read_only=read_only,
        risk=risk,
        required_arguments=required_arguments,
        input_schema=MockArguments.model_json_schema(),
        output_schema=MockResult.model_json_schema(),
    )


_TOOLS = (
    tool(
        "github_search_code",
        "github",
        "Search source code across GitHub repositories by query.",
        required_arguments=("query",),
    ),
    tool(
        "github_read_file",
        "github",
        "Read a known file path in a specified GitHub repository.",
        required_arguments=("repository", "path"),
    ),
    tool(
        "github_search_issues",
        "github",
        "Find or inspect GitHub issues by query, status, or number.",
        required_arguments=("query",),
    ),
    tool(
        "github_create_issue",
        "github",
        "Create a new issue in a specified GitHub repository.",
        False,
        "high",
        ("repository", "title"),
    ),
    tool(
        "browser_search_web",
        "browser",
        "Search the public web for information or websites.",
        required_arguments=("query",),
    ),
    tool(
        "browser_open_page",
        "browser",
        "Open and read a specified web page URL.",
        required_arguments=("url",),
    ),
    tool(
        "browser_click",
        "browser",
        "Click a specified element on the current web page; may change state.",
        False,
        "medium",
        ("element",),
    ),
    tool(
        "browser_submit_form",
        "browser",
        "Submit a web form with supplied information.",
        False,
        "high",
        ("url", "form_data"),
    ),
    tool(
        "files_search",
        "files",
        "Find local files by name, path pattern, or content query.",
        required_arguments=("query",),
    ),
    tool(
        "files_read",
        "files",
        "Read contents of a known local file path.",
        required_arguments=("path",),
    ),
    tool(
        "files_write",
        "files",
        "Create or replace contents at a specified local file path.",
        False,
        "medium",
        ("path", "content"),
    ),
    tool("files_delete", "files", "Delete a specified local file.", False, "high", ("path",)),
    tool(
        "calendar_search_events",
        "calendar",
        "Find or read calendar events by title, date, or participant.",
        required_arguments=("query",),
    ),
    tool(
        "calendar_check_availability",
        "calendar",
        "Check free and busy time over a specified interval.",
        required_arguments=("time_window",),
    ),
    tool(
        "calendar_create_event",
        "calendar",
        "Create a calendar event with title, time, and participants.",
        False,
        "high",
        ("title", "time_window"),
    ),
    tool(
        "calendar_delete_event",
        "calendar",
        "Delete or cancel an identified calendar event.",
        False,
        "high",
        ("event_id",),
    ),
)
CATALOG = MappingProxyType({t.name: t for t in _TOOLS})
if len(CATALOG) != len(_TOOLS):
    raise ValueError("Duplicate catalog name")

SAFE_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
SAFE_PATH = re.compile(r"/[A-Za-z0-9._/-]+")


def execute_mock(
    decision: RoutingDecision,
    *,
    prepared: ToolCallPreparation | None = None,
    approved: bool = False,
) -> MockResult:
    if decision.outcome != "route" or decision.selected_tool not in CATALOG:
        raise ValueError("Only a valid routed catalog tool can be simulated")
    assert decision.selected_tool is not None
    definition = CATALOG[decision.selected_tool]
    if definition.domain != decision.selected_domain:
        raise ValueError("Tool and domain mismatch")
    if prepared is None or prepared.tool != definition.name or prepared.status != "ready":
        raise ValueError("A ready prepared tool call is required")
    if set(prepared.arguments) != set(definition.required_arguments):
        raise ValueError("Prepared arguments do not match the tool schema")
    if any(not value.strip() for value in prepared.arguments.values()):
        raise ValueError("Prepared arguments must not be empty")
    if "url" in prepared.arguments and not SAFE_URL.fullmatch(prepared.arguments["url"]):
        raise ValueError("Prepared URL is invalid")
    if "path" in prepared.arguments and not SAFE_PATH.fullmatch(prepared.arguments["path"]):
        raise ValueError("Prepared file path is invalid")
    if (
        decision.requires_approval or tool_requires_approval(definition.name, CATALOG)
    ) and approved is not True:
        raise PermissionError("Explicit approved=True is required")
    return MockResult(
        tool=definition.name,
        arguments=MockArguments(target=f"mock://{definition.name}", fields=prepared.arguments),
    )
