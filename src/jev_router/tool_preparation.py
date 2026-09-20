"""Conservative local argument preparation after a router selects a catalog tool."""

import re
from collections.abc import Mapping

from jev_router.models import RoutingDecision, RoutingRequest, ToolCallPreparation
from jev_router.tool_catalog import CATALOG, ToolDefinition

URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
PATH = re.compile(r"(?<!\w)(/[A-Za-z0-9._/-]+)")
GIT_PATH = re.compile(r"\b([A-Za-z0-9_./-]+\.(?:md|py|toml|json|yaml|yml|txt))\b")
REPOSITORY = re.compile(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b")
QUOTED = re.compile(r"[\"'`]([^\"'`]+)[\"'`]")
LABELED = re.compile(r"\b([a-z_]+)\s*[:=]\s*([^,\n]+)", re.IGNORECASE)

FIELD_PROMPTS = {
    "url": "Please provide the URL to open.",
    "path": "Please provide the local file path.",
    "repository": "Please provide the GitHub repository as owner/repository.",
    "query": "Please provide the search query.",
    "element": "Please identify the page element to interact with.",
    "form_data": "Please provide the form fields to submit.",
    "content": "Please provide the file content to write.",
    "time_window": "Please provide the date or time window.",
    "title": "Please provide the event or issue title.",
    "event_id": "Please provide the calendar event identifier.",
}


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match and match.groups() else (match.group(0) if match else None)


def _values(request: RoutingRequest) -> dict[str, str]:
    text = f"{request.user_request}\n{request.recent_context}"
    labeled = {key.lower(): value.strip() for key, value in LABELED.findall(text)}
    quoted = _first(QUOTED, text)
    return {
        **labeled,
        **({"url": value} if (value := _first(URL, text)) else {}),
        **({"path": value.rstrip(" .")} if (value := _first(PATH, text)) else {}),
        **({"repository": value} if (value := _first(REPOSITORY, text)) else {}),
        **({"quoted": quoted} if quoted else {}),
    }


def _derive(field: str, values: dict[str, str], request: RoutingRequest) -> str | None:
    if field in values:
        value = values[field]
        if field == "url" and not URL.fullmatch(value):
            return None
        if field == "path" and not PATH.fullmatch(value):
            return None
        if field == "repository" and not REPOSITORY.fullmatch(value):
            return None
        if not value:
            return None
        return value
    if field == "query":
        return values.get("quoted") or request.user_request.strip()
    if field in {"element", "title"}:
        return values.get("quoted")
    if field == "content":
        quoted = values.get("quoted")
        return quoted if quoted and not PATH.fullmatch(quoted) else None
    if field == "time_window" and re.search(
        r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"\d{4}-\d{2}-\d{2})\b",
        request.user_request,
        re.IGNORECASE,
    ):
        return request.user_request.strip()
    return None


def prepare_tool_call(
    decision: RoutingDecision,
    request: RoutingRequest,
    catalog: Mapping[str, ToolDefinition] = CATALOG,
) -> ToolCallPreparation:
    """Build a call only from explicit request/context values; never invent values."""
    if decision.outcome != "route" or decision.selected_tool not in catalog:
        raise ValueError("Only a valid routed catalog tool can be prepared")
    assert decision.selected_tool is not None
    definition = catalog[decision.selected_tool]
    if definition.domain != decision.selected_domain:
        raise ValueError("Tool and domain mismatch")
    values = _values(request)
    if definition.name == "github_read_file" and "path" not in values:
        if path := _first(GIT_PATH, request.user_request):
            values["path"] = path
    if definition.name == "browser_click" and "element" not in values:
        if match := re.search(
            r"\b(?:click|expand)\s+(?:the\s+)?(.+?)(?:\s+on\b|$)",
            request.user_request,
            re.IGNORECASE,
        ):
            values["element"] = match.group(1).strip()
    if definition.name == "files_write" and "content" not in values:
        if match := re.search(
            r"\b(?:containing exactly|text)\s+(.+?)\s+(?:into|to)\s+",
            request.user_request,
            re.IGNORECASE,
        ):
            values["content"] = match.group(1).strip()
    arguments = {
        field: value
        for field in definition.required_arguments
        if (value := _derive(field, values, request)) is not None
    }
    missing = [field for field in definition.required_arguments if field not in arguments]
    return ToolCallPreparation(
        tool=definition.name,
        status="needs_clarification" if missing else "ready",
        arguments=arguments,
        missing_fields=missing,
        clarification=(
            FIELD_PROMPTS.get(missing[0], f"Please provide {missing[0]}.") if missing else None
        ),
    )
