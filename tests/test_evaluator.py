import json
from pathlib import Path

import pytest

from jev_router.config import Settings
from jev_router.lab.evaluator import (
    EvaluationCase,
    EvaluationRecord,
    calculate_metrics,
    evaluate,
    load_cases,
)
from jev_router.models import RoutingDecision, TokenUsage


def record(
    case_id,
    expected_tool,
    selected_tool,
    *,
    truth=False,
    prediction=0.0,
    approval=False,
    outcome="route",
    expected_outcome="route",
    latency=10,
):
    case = EvaluationCase(
        id=case_id,
        request="Example request",
        expected_domain="files",
        expected_tools=[expected_tool] if expected_tool else [],
        expected_outcome=expected_outcome,
        requires_approval=truth,
        expected_mutation=truth,
        expected_high_consequence=truth,
    )
    decision = RoutingDecision(
        router="jev",
        model="test",
        selected_domain="files",
        selected_tool=selected_tool,
        outcome=outcome,
        requires_approval=approval,
        mutation_probability=prediction,
        high_consequence_probability=prediction,
        domain_confidence=0.9,
        tool_confidence=0.9,
        tool_probabilities={"files_read": 0.7, "files_delete": 0.3},
        latency_ms=latency,
        usage=TokenUsage(input_tokens=100, output_tokens=10),
        estimated_cost_usd=0.01,
    )
    return EvaluationRecord(case=case, decision=decision)


def test_metrics_have_explicit_denominators():
    rows = [
        record("a", "files_read", "files_read"),
        record("b", "files_delete", "files_read", truth=True, prediction=0.8),
        record("c", None, None, outcome="clarify", expected_outcome="clarify", latency=100),
    ]
    metrics = calculate_metrics(rows, Settings(_env_file=None))
    assert metrics.domain_accuracy == 1
    assert metrics.exact_tool_accuracy == 0.5
    assert metrics.tool_fit_accuracy == 0.5
    assert metrics.execution_readiness_accuracy == 1
    assert metrics.tool_case_count == 2
    assert metrics.top_two_tool_accuracy == 1
    assert metrics.clarification.precision == metrics.clarification.recall == 1
    assert metrics.mutation.precision == metrics.mutation.recall == 1
    assert metrics.high_consequence.recall == 1
    assert metrics.approval_policy_violations == 1
    assert metrics.input_tokens == 300
    assert metrics.cost_per_correct_route_usd == pytest.approx(0.03)
    assert metrics.latency_median_ms == 10
    assert metrics.latency_p95_ms == 100
    assert sum(bucket.count for bucket in metrics.confidence_buckets) == 3


def test_empty_metrics_and_unknown_cost():
    assert calculate_metrics([], Settings(_env_file=None)).domain_accuracy is None
    row = record("a", "files_read", "files_read")
    row.decision.usage.complete = False
    row.decision.estimated_cost_usd = None
    metrics = calculate_metrics([row], Settings(_env_file=None))
    assert metrics.estimated_cost_usd is None
    assert metrics.cost_per_correct_route_usd is None
    assert metrics.usage_incomplete_count == 1


def test_dataset_has_unique_cases_and_truth_labels():
    cases = load_cases(Path("experiments/routing_cases.json"))
    assert len(cases) >= 60
    assert len({case.id for case in cases}) == len(cases)
    assert len({case.request for case in cases}) == len(cases)
    assert {case.expected_outcome for case in cases} == {"route", "no_tool", "clarify", "fallback"}
    assert all(
        "expected_mutation" in row and "expected_high_consequence" in row
        for row in json.loads(Path("experiments/routing_cases.json").read_text())
    )


async def test_evaluation_never_executes_tools(monkeypatch):
    from unittest.mock import Mock

    execute = Mock(side_effect=AssertionError("must not execute"))
    monkeypatch.setattr("jev_router.lab.tool_catalog.execute_mock", execute)
    row = record("a", "files_delete", "files_delete", truth=True, approval=True)

    class Router:
        async def route(self, request):
            return row.decision

    report = await evaluate([row.case], {"jev": Router()}, Settings(_env_file=None), "hash")
    assert report.routers["jev"].metrics.exact_tool_accuracy == 1
    assert not execute.called
    assert "Example request" not in report.model_dump_json()


async def test_evaluation_report_records_diagnostic_stage_two_mode():
    row = record("a", "files_read", "files_read")

    class Router:
        async def route(self, request):
            return row.decision

    settings = Settings(_env_file=None, diagnostic_stage_two=True)
    report = await evaluate([row.case], {"jev": Router()}, settings, "hash")
    assert json.loads(report.model_dump_json())["settings"]["diagnostic_stage_two"] is True
