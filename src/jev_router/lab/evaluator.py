"""Offline metric computation and optional paid routing runs. Never executes tools."""

import hashlib
import math
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

from pydantic import Field, TypeAdapter, model_validator

from jev_router.config import Settings
from jev_router.interfaces import Router
from jev_router.lab.logging import log_decision, request_hash
from jev_router.lab.tool_catalog import CATALOG
from jev_router.models import Domain, Model, Outcome, RoutingDecision, RoutingRequest
from jev_router.tools import tool_requires_approval


class EvaluationCase(Model):
    id: str
    request: str = Field(min_length=1, max_length=20000)
    recent_context: str = Field(default="", max_length=20000)
    expected_domain: Domain
    expected_tools: list[str]
    expected_outcome: Outcome
    requires_approval: bool
    expected_mutation: bool
    expected_high_consequence: bool
    expected_tool_fit: bool | None = None
    expected_execution_ready: bool | None = None
    notes: str = ""

    @model_validator(mode="after")
    def validate_tools(self) -> "EvaluationCase":
        if self.expected_outcome == "route" and not self.expected_tools:
            raise ValueError("Route cases require acceptable tools")
        for name in self.expected_tools:
            if name not in CATALOG or CATALOG[name].domain != self.expected_domain:
                raise ValueError("Expected tool is not in expected domain")
            if (
                self.expected_outcome == "route"
                and tool_requires_approval(name, CATALOG)
                and not self.requires_approval
            ):
                raise ValueError("Case contradicts catalog approval policy")
        return self

    @property
    def tool_fit_expected(self) -> bool:
        return (
            self.expected_tool_fit
            if self.expected_tool_fit is not None
            else bool(self.expected_tools)
        )

    @property
    def execution_ready_expected(self) -> bool:
        return (
            self.expected_execution_ready
            if self.expected_execution_ready is not None
            else self.expected_outcome == "route"
        )


class EvaluationRecord(Model):
    case: EvaluationCase = Field(exclude=True)
    decision: RoutingDecision


class BinaryMetrics(Model):
    precision: float | None
    recall: float | None
    true_positives: int
    false_positives: int
    false_negatives: int
    unknown_count: int = 0


class ConfidenceBucket(Model):
    label: str
    count: int
    accuracy: float | None


class Metrics(Model):
    case_count: int
    tool_case_count: int
    domain_accuracy: float | None
    exact_tool_accuracy: float | None
    tool_fit_case_count: int
    tool_fit_accuracy: float | None
    execution_readiness_accuracy: float | None
    top_two_tool_accuracy: float | None
    top_two_available_case_count: int
    outcome_accuracy: float | None
    overall_accuracy: float | None
    correct_route_count: int
    clarification: BinaryMetrics
    mutation: BinaryMetrics
    high_consequence: BinaryMetrics
    approval_policy_violations: int
    fallback_rate: float | None
    latency_mean_ms: float | None
    latency_median_ms: float | None
    latency_p95_ms: float | None
    input_tokens: int
    output_tokens: int
    usage_incomplete_count: int
    estimated_cost_usd: float | None
    cost_per_correct_route_usd: float | None
    confidence_buckets: list[ConfidenceBucket]


def ratio(numerator: int | float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def binary_metrics(truth: list[bool], predicted: list[bool | None]) -> BinaryMetrics:
    tp = sum(t and p is True for t, p in zip(truth, predicted, strict=True))
    fp = sum(not t and p is True for t, p in zip(truth, predicted, strict=True))
    fn = sum(t and p is not True for t, p in zip(truth, predicted, strict=True))
    return BinaryMetrics(
        precision=ratio(tp, tp + fp),
        recall=ratio(tp, tp + fn),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        unknown_count=predicted.count(None),
    )


def correct_route(record: EvaluationRecord) -> bool:
    c, d = record.case, record.decision
    return (
        c.expected_outcome == d.outcome == "route"
        and d.selected_domain == c.expected_domain
        and d.selected_tool in c.expected_tools
    )


def correct_tool_fit(record: EvaluationRecord) -> bool:
    c, d = record.case, record.decision
    return d.selected_domain == c.expected_domain and d.selected_tool in c.expected_tools


def correct_outcome(record: EvaluationRecord) -> bool:
    c, d = record.case, record.decision
    return (
        c.expected_outcome == d.outcome
        and c.expected_domain == d.selected_domain
        and (d.outcome != "route" or correct_route(record))
    )


def confidence_buckets(records: list[EvaluationRecord]) -> list[ConfidenceBucket]:
    groups: dict[str, list[bool]] = {
        "[0,0.5)": [],
        "[0.5,0.7)": [],
        "[0.7,0.9)": [],
        "[0.9,1]": [],
        "unknown": [],
    }
    labels = list(groups)
    for record in records:
        d = record.decision
        values = [x for x in (d.domain_confidence, d.tool_confidence) if x is not None]
        confidence = min(values) if values else None
        index = (
            4
            if confidence is None
            else 0
            if confidence < 0.5
            else 1
            if confidence < 0.7
            else 2
            if confidence < 0.9
            else 3
        )
        groups[labels[index]].append(correct_outcome(record))
    return [
        ConfidenceBucket(label=label, count=len(values), accuracy=ratio(sum(values), len(values)))
        for label, values in groups.items()
    ]


def calculate_metrics(records: list[EvaluationRecord], settings: Settings) -> Metrics:
    n = len(records)
    tool_rows = [r for r in records if r.case.expected_outcome == "route"]
    tool_fit_rows = [r for r in records if r.case.tool_fit_expected]
    top_two_rows = [r for r in tool_rows if r.decision.tool_probabilities]
    top_two_correct = sum(
        any(
            tool in r.case.expected_tools
            for tool in sorted(
                r.decision.tool_probabilities,
                key=lambda k: r.decision.tool_probabilities[k],
                reverse=True,
            )[:2]
        )
        and r.case.expected_domain == r.decision.selected_domain
        for r in top_two_rows
    )
    latencies = sorted(r.decision.latency_ms for r in records)
    costs = [r.decision.estimated_cost_usd for r in records]
    cost = (
        sum(c for c in costs if c is not None) if n and all(c is not None for c in costs) else None
    )
    correct = sum(correct_route(r) for r in records)
    violations = sum(
        r.decision.outcome == "route"
        and not r.decision.requires_approval
        and (
            r.case.requires_approval
            or (
                r.decision.selected_tool in CATALOG
                and tool_requires_approval(r.decision.selected_tool or "", CATALOG)
            )
        )
        for r in records
    )
    return Metrics(
        case_count=n,
        tool_case_count=len(tool_rows),
        domain_accuracy=ratio(
            sum(r.case.expected_domain == r.decision.selected_domain for r in records), n
        ),
        exact_tool_accuracy=ratio(correct, len(tool_rows)),
        tool_fit_case_count=len(tool_fit_rows),
        tool_fit_accuracy=ratio(
            sum(correct_tool_fit(r) for r in tool_fit_rows), len(tool_fit_rows)
        ),
        execution_readiness_accuracy=ratio(
            sum(
                r.case.execution_ready_expected == (r.decision.outcome == "route") for r in records
            ),
            n,
        ),
        top_two_tool_accuracy=ratio(top_two_correct, len(top_two_rows)),
        top_two_available_case_count=len(top_two_rows),
        outcome_accuracy=ratio(
            sum(r.case.expected_outcome == r.decision.outcome for r in records), n
        ),
        overall_accuracy=ratio(sum(correct_outcome(r) for r in records), n),
        correct_route_count=correct,
        clarification=binary_metrics(
            [r.case.expected_outcome == "clarify" for r in records],
            [r.decision.outcome == "clarify" for r in records],
        ),
        mutation=binary_metrics(
            [r.case.expected_mutation for r in records],
            [
                None
                if r.decision.mutation_probability is None
                else r.decision.mutation_probability >= settings.jev_mutation_threshold
                for r in records
            ],
        ),
        high_consequence=binary_metrics(
            [r.case.expected_high_consequence for r in records],
            [
                None
                if r.decision.high_consequence_probability is None
                else r.decision.high_consequence_probability
                >= settings.jev_high_consequence_threshold
                for r in records
            ],
        ),
        approval_policy_violations=violations,
        fallback_rate=ratio(sum(r.decision.outcome == "fallback" for r in records), n),
        latency_mean_ms=mean(latencies) if n else None,
        latency_median_ms=median(latencies) if n else None,
        latency_p95_ms=latencies[math.ceil(0.95 * n) - 1] if n else None,
        input_tokens=sum(r.decision.usage.input_tokens for r in records),
        output_tokens=sum(r.decision.usage.output_tokens for r in records),
        usage_incomplete_count=sum(not r.decision.usage.complete for r in records),
        estimated_cost_usd=cost,
        cost_per_correct_route_usd=ratio(cost, correct) if cost is not None else None,
        confidence_buckets=confidence_buckets(records),
    )


class CaseResult(Model):
    case_id: str
    request_sha256: str
    expected_domain: Domain
    expected_tools: list[str]
    expected_outcome: Outcome
    expected_tool_fit: bool
    expected_execution_ready: bool
    requires_approval: bool
    expected_mutation: bool
    expected_high_consequence: bool
    decision: RoutingDecision
    correct: bool


class RouterReport(Model):
    metrics: Metrics
    cases: list[CaseResult]


class EvaluationReport(Model):
    schema_version: int = 3
    baseline_output_schema: str = "closed_probability_object_v2"
    domain_option_schema: str = "catalog_derived_domains_v1"
    created_at: str
    dataset_sha256: str
    settings: dict[str, str | float | int | None]
    routers: dict[str, RouterReport]
    notes: str = (
        "Sequential routing; router order alternates each case; no warmup. No tools executed. "
        "Token totals are reported lower bounds if usage_incomplete_count > 0. "
        "Costs are assumptions, not invoices. Baseline probabilities are self-reported."
    )


def load_cases(path: Path) -> list[EvaluationCase]:
    cases = TypeAdapter(list[EvaluationCase]).validate_json(path.read_text())
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("Dataset must be nonempty and have unique IDs")
    return cases


async def evaluate(
    cases: list[EvaluationCase], routers: dict[str, Router], settings: Settings, dataset_sha256: str
) -> EvaluationReport:
    records: dict[str, list[EvaluationRecord]] = {name: [] for name in routers}
    for index, case in enumerate(cases):
        request = RoutingRequest(user_request=case.request, recent_context=case.recent_context)
        names = list(routers) if index % 2 == 0 else list(reversed(routers))
        for name in names:
            decision = await routers[name].route(request)
            log_decision(request, decision, settings)
            records[name].append(EvaluationRecord(case=case, decision=decision))
    reports = {}
    for name, rows in records.items():
        results = [
            CaseResult(
                case_id=r.case.id,
                request_sha256=request_hash(r.case.request),
                expected_domain=r.case.expected_domain,
                expected_tools=r.case.expected_tools,
                expected_outcome=r.case.expected_outcome,
                expected_tool_fit=r.case.tool_fit_expected,
                expected_execution_ready=r.case.execution_ready_expected,
                requires_approval=r.case.requires_approval,
                expected_mutation=r.case.expected_mutation,
                expected_high_consequence=r.case.expected_high_consequence,
                # Prepared fields are request-derived and must not leave the process in reports.
                decision=r.decision.model_copy(update={"tool_call": None}),
                correct=correct_outcome(r),
            )
            for r in rows
        ]
        reports[name] = RouterReport(metrics=calculate_metrics(rows, settings), cases=results)
    return EvaluationReport(
        created_at=datetime.now(UTC).isoformat(),
        dataset_sha256=dataset_sha256,
        settings=settings.report_config(),
        routers=reports,
    )


def write_report(report: EvaluationReport, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    path = directory / f"routing-{timestamp}.json"
    with path.open("x") as file:
        file.write(report.model_dump_json(indent=2) + "\n")
    return path


def dataset_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
