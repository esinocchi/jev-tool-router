"""The benchmark exercises the agent loop while keeping tool execution inert."""

from types import SimpleNamespace

import pytest

from jev_router.lab.agent_benchmark import (
    AgentBenchmarkReport,
    AgentTask,
    AgentTaskRecord,
    OpenRouterAgent,
    active_tools,
    load_agent_tasks,
    run_task,
    score_task,
    summarize_records,
    tool_spec,
)
from jev_router.lab.tool_catalog import CATALOG
from jev_router.models import RoutingDecision, TokenUsage


def test_tool_spec_uses_real_argument_names_not_lab_placeholder_schema():
    spec = tool_spec(CATALOG["github_read_file"])
    assert spec["function"]["parameters"]["required"] == ["repository", "path"]
    assert set(spec["function"]["parameters"]["properties"]) == {"repository", "path"}


def test_fallback_restores_all_tools_and_no_tool_hides_them():
    all_tools = list(CATALOG.values())
    fallback = RoutingDecision(router="jev", model="test", outcome="fallback")
    no_tool = RoutingDecision(router="jev", model="test", outcome="no_tool")
    selected = RoutingDecision(
        router="jev", model="test", outcome="route", selected_tool="files_read"
    )
    assert len(active_tools(fallback, all_tools)) == 16
    assert active_tools(no_tool, all_tools) == []
    assert [tool.name for tool in active_tools(selected, all_tools)] == ["files_read"]


def test_scoring_requires_answer_facts_and_all_expected_tools():
    task = AgentTask(
        id="sample",
        request="Find issue and setup command",
        expected_tools=["github_search_issues", "github_read_file"],
        required_facts=["42", "uv sync"],
        mock_results={"github_search_issues": "Issue #42", "github_read_file": "uv sync"},
    )
    assert score_task(task, ["github_read_file", "github_search_issues"], "Issue 42. Use uv sync")
    assert not score_task(task, ["github_search_issues"], "Issue 42. Use uv sync")
    assert not score_task(task, ["github_read_file", "github_search_issues"], "Issue 42")


@pytest.mark.asyncio
async def test_run_task_uses_selected_tool_and_finishes_with_mock_result():
    task = AgentTask(
        id="sample",
        request="Find auth issue",
        expected_tools=["github_search_issues"],
        required_facts=["42"],
        mock_results={"github_search_issues": "Issue #42 is open"},
    )
    calls = []

    async def model_call(messages, offered):
        calls.append((messages, offered))
        if len(calls) == 1:
            return SimpleNamespace(
                content=None,
                tool_calls=[
                    SimpleNamespace(name="github_search_issues", arguments={"query": "auth"})
                ],
                input_tokens=12,
                output_tokens=4,
            )
        return SimpleNamespace(
            content="Issue #42 is open", tool_calls=[], input_tokens=20, output_tokens=6
        )

    async def route(_request, _context):
        return RoutingDecision(
            router="jev", model="test", outcome="route", selected_tool="github_search_issues"
        )

    record = await run_task(task, "jev", model_call, route)
    assert record.success is True
    assert record.called_tools == ["github_search_issues"]
    assert record.routing_decisions[0].selected_tool == "github_search_issues"
    assert [tool.name for tool in calls[0][1]] == ["github_search_issues"]
    assert "Issue #42 is open" in str(calls[1][0])
    assert record.input_tokens == 32
    assert record.output_tokens == 10


@pytest.mark.asyncio
async def test_run_task_blocks_mutating_tool_even_when_model_calls_it():
    task = AgentTask(
        id="sample",
        request="Create issue",
        expected_tools=[],
        required_facts=[],
        mock_results={},
    )

    async def model_call(_messages, _offered):
        return SimpleNamespace(
            content=None,
            tool_calls=[
                SimpleNamespace(
                    name="github_create_issue", arguments={"repository": "x", "title": "y"}
                )
            ],
            input_tokens=1,
            output_tokens=1,
        )

    record = await run_task(task, "flat", model_call)
    assert record.success is False
    assert record.failure_reason == "approval_required"
    assert record.called_tools == []


def test_agent_dataset_has_read_only_mock_results():
    from pathlib import Path

    tasks = load_agent_tasks(Path("experiments/shared_cases.json"))
    assert len(tasks) == 100
    assert len({task.id for task in tasks}) == len(tasks)
    assert any(len(task.expected_tools) > 1 for task in tasks)
    assert any(not task.expected_tools for task in tasks)
    assert {task.agent_expectation for task in tasks} == {
        "complete",
        "no_tool",
        "clarify",
        "approval",
        "unavailable",
    }


def test_shared_dataset_has_identical_prompts_and_ids_in_both_benchmarks():
    from pathlib import Path

    from jev_router.lab.evaluator import load_cases

    path = Path("experiments/shared_cases.json")
    routing = load_cases(path)
    agent = load_agent_tasks(path)
    assert len(routing) == len(agent) == 100
    assert [(case.id, case.request, case.recent_context) for case in routing] == [
        (task.id, task.request, task.recent_context) for task in agent
    ]


def test_report_splits_completion_from_clarification_latency():
    from jev_router.lab.agent_benchmark import summarize_by_expectation

    records = [
        AgentTaskRecord(
            case_id="read", arm="flat", expectation="complete", success=True, latency_ms=100
        ),
        AgentTaskRecord(
            case_id="ask", arm="flat", expectation="clarify", success=True, latency_ms=10
        ),
    ]
    groups = summarize_by_expectation(records, input_price=0.0, output_price=0.0)
    assert groups["complete"].mean_latency_ms == 100
    assert groups["clarify"].mean_latency_ms == 10


@pytest.mark.asyncio
async def test_ambiguity_is_scored_as_question_without_tool_call():
    task = AgentTask(
        id="ambiguous",
        request="Read that file",
        expected_tools=[],
        required_facts=[],
        mock_results={},
        agent_expectation="clarify",
    )

    async def asks(_messages, _offered):
        return SimpleNamespace(
            content="Which file should I read?", tool_calls=[], input_tokens=1, output_tokens=4
        )

    async def guesses(_messages, _offered):
        return SimpleNamespace(
            content="I found the file.", tool_calls=[], input_tokens=1, output_tokens=4
        )

    assert (await run_task(task, "flat", asks)).success
    assert not (await run_task(task, "flat", guesses)).success

    async def clarify(_request, _context):
        return RoutingDecision(router="jev", model="test", outcome="clarify")

    async def must_not_call(_messages, _offered):
        raise AssertionError("Luna should not run after a clarification decision")

    assert (await run_task(task, "jev", must_not_call, clarify)).success


@pytest.mark.asyncio
async def test_approval_and_unavailable_have_distinct_safe_outcomes():
    approval = AgentTask(
        id="approval",
        request="Delete /tmp/a",
        expected_tools=[],
        required_facts=[],
        mock_results={},
        agent_expectation="approval",
    )
    unavailable = AgentTask(
        id="unavailable",
        request="Send an email",
        expected_tools=[],
        required_facts=[],
        mock_results={},
        agent_expectation="unavailable",
    )

    async def model(_messages, _offered):
        return SimpleNamespace(
            content="I need your approval first.", tool_calls=[], input_tokens=1, output_tokens=4
        )

    assert (await run_task(approval, "flat", model)).success
    assert not (await run_task(unavailable, "flat", model)).success


@pytest.mark.asyncio
async def test_agent_receives_same_recent_context_as_router():
    task = AgentTask(
        id="context",
        request="Am I free Friday afternoon?",
        recent_context="Today is September 21, 2026. Afternoon means noon to 5pm.",
        expected_tools=["calendar_check_availability"],
        required_facts=["free"],
        mock_results={"calendar_check_availability": "free"},
    )
    seen = []

    async def model(messages, _offered):
        seen.append(messages)
        return SimpleNamespace(content="free", tool_calls=[], input_tokens=1, output_tokens=1)

    await run_task(task, "flat", model)
    assert task.recent_context in str(seen[0])


def test_summary_uses_total_agent_and_router_usage():
    records = [
        AgentTaskRecord(
            case_id="a",
            arm="jev",
            success=True,
            latency_ms=100,
            input_tokens=30,
            output_tokens=10,
            routing_input_tokens=20,
            routing_output_tokens=5,
            routing_cost_usd=0.001,
        ),
        AgentTaskRecord(
            case_id="b",
            arm="jev",
            success=False,
            latency_ms=300,
            input_tokens=40,
            output_tokens=15,
            routing_input_tokens=10,
            routing_output_tokens=2,
            routing_cost_usd=0.002,
        ),
    ]
    summary = summarize_records(records, input_price=1.0, output_price=2.0)
    assert summary.success_rate == 0.5
    assert summary.mean_latency_ms == 200
    assert summary.mean_success_latency_ms == 100
    assert summary.total_input_tokens == 100
    assert summary.total_output_tokens == 32
    assert summary.estimated_cost_usd == pytest.approx(0.003 + 70 / 1_000_000 + 50 / 1_000_000)
    assert summary.cost_per_success_usd == pytest.approx(summary.estimated_cost_usd)


def test_summary_keeps_exact_cost_unknown_but_reports_known_minimum():
    complete = RoutingDecision(
        router="jev",
        model="test",
        outcome="route",
        selected_tool="files_search",
        usage=TokenUsage(input_tokens=100, output_tokens=10, attempted_calls=1, reported_calls=1),
        estimated_cost_usd=0.0001,
    )
    timed_out = RoutingDecision(
        router="jev",
        model="test",
        outcome="fallback",
        fallback_reason="timeout",
        usage=TokenUsage(
            input_tokens=50, output_tokens=5, complete=False, attempted_calls=2, reported_calls=1
        ),
        estimated_cost_usd=None,
    )
    record = AgentTaskRecord(
        case_id="partial",
        arm="jev",
        success=False,
        input_tokens=20,
        output_tokens=4,
        routing_input_tokens=150,
        routing_output_tokens=15,
        routing_cost_usd=None,
        routing_decisions=[complete, timed_out],
    )
    summary = summarize_records(
        [record],
        input_price=0.2,
        output_price=1.2,
        routing_input_price=0.042,
        routing_output_price=0,
    )
    assert summary.estimated_cost_usd is None
    assert summary.missing_routing_usage_calls == 1
    assert summary.known_minimum_cost_usd == pytest.approx(
        (20 * 0.2 + 4 * 1.2 + 150 * 0.042) / 1_000_000
    )


def test_report_omits_model_answer_but_records_reproducible_settings():
    record = AgentTaskRecord(case_id="a", arm="flat", answer="Private request text echoed")
    report = AgentBenchmarkReport(
        model="example/model",
        tool_count=16,
        dataset_sha256="abc",
        settings={"jev_tool_confidence_threshold": 0.7},
        summaries={},
        cases=[record],
    )
    data = report.model_dump_json()
    assert "Private request text echoed" not in data
    assert '"dataset_sha256":"abc"' in data
    assert '"jev_tool_confidence_threshold":0.7' in data


@pytest.mark.asyncio
async def test_openrouter_agent_reads_tool_call_and_usage():
    class FakeCompletions:
        async def create(self, **kwargs):
            assert kwargs["tools"][0]["function"]["name"] == "files_read"
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_123",
                                    type="function",
                                    function=SimpleNamespace(
                                        name="files_read", arguments='{"path":"/tmp/report"}'
                                    ),
                                )
                            ],
                        ),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=50, completion_tokens=7),
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    agent = OpenRouterAgent(fake_client, "openai/gpt-5.6-luna")
    turn = await agent([{"role": "user", "content": "Read report"}], [CATALOG["files_read"]])
    assert turn.tool_calls[0].name == "files_read"
    assert turn.tool_calls[0].arguments == {"path": "/tmp/report"}
    assert turn.tool_calls[0].id == "call_123"
    assert turn.input_tokens == 50
    assert turn.output_tokens == 7
