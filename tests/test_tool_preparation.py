import pytest

from jev_router.models import RoutingDecision, RoutingRequest
from jev_router.tool_catalog import execute_mock
from jev_router.tool_preparation import prepare_tool_call


def routed(tool: str, domain: str) -> RoutingDecision:
    return RoutingDecision(
        router="test",
        model="test",
        outcome="route",
        selected_domain=domain,  # type: ignore[arg-type]
        selected_tool=tool,
    )


def test_preparation_extracts_explicit_file_path_for_read_only_tool():
    decision = routed("files_read", "files")

    prepared = prepare_tool_call(
        decision, RoutingRequest(user_request="Read /tmp/reports/weekly.txt")
    )

    assert prepared.status == "ready"
    assert prepared.arguments == {"path": "/tmp/reports/weekly.txt"}
    assert execute_mock(decision, prepared=prepared).arguments.fields == prepared.arguments


def test_preparation_requests_the_specific_missing_field():
    decision = routed("browser_open_page", "browser")

    prepared = prepare_tool_call(decision, RoutingRequest(user_request="Open that website"))

    assert prepared.status == "needs_clarification"
    assert prepared.missing_fields == ["url"]
    assert prepared.clarification == "Please provide the URL to open."


def test_executor_refuses_an_unprepared_tool_call():
    decision = routed("files_read", "files")

    with pytest.raises(ValueError, match="prepared"):
        execute_mock(decision)


def test_mutating_prepared_call_still_requires_explicit_approval():
    decision = routed("files_delete", "files")
    prepared = prepare_tool_call(
        decision, RoutingRequest(user_request="Delete /tmp/reports/weekly.txt")
    )

    with pytest.raises(PermissionError):
        execute_mock(decision, prepared=prepared)
    assert execute_mock(decision, prepared=prepared, approved=True).tool == "files_delete"


def test_quoted_path_is_not_mistaken_for_file_content():
    prepared = prepare_tool_call(
        routed("files_write", "files"),
        RoutingRequest(user_request='Write to "/tmp/report.txt"'),
    )

    assert prepared.status == "needs_clarification"
    assert prepared.missing_fields == ["content"]


def test_path_extraction_stops_before_following_prose():
    prepared = prepare_tool_call(
        routed("files_read", "files"),
        RoutingRequest(user_request="Read /tmp/report.txt and summarize it"),
    )

    assert prepared.arguments == {"path": "/tmp/report.txt"}


def test_unsafe_labeled_url_requires_clarification():
    prepared = prepare_tool_call(
        routed("browser_open_page", "browser"),
        RoutingRequest(user_request="Open url=javascript:alert(1)"),
    )

    assert prepared.status == "needs_clarification"
    assert prepared.missing_fields == ["url"]


def test_executor_rejects_a_forged_empty_prepared_argument():
    decision = routed("files_read", "files")
    prepared = prepare_tool_call(decision, RoutingRequest(user_request="Read /tmp/a"))
    prepared.arguments["path"] = ""

    with pytest.raises(ValueError, match="empty"):
        execute_mock(decision, prepared=prepared)
