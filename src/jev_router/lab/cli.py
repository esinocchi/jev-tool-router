"""Typer CLI. Route calls models; execution is always an inert local simulation."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import typer
from openai import AsyncOpenAI
from pydantic import ValidationError

from jev_router.config import Settings
from jev_router.interfaces import Router
from jev_router.jev_router import JevRouter
from jev_router.lab.agent_benchmark import (
    AgentBenchmarkReport,
    OpenRouterAgent,
    load_agent_tasks,
    run_task,
    summarize_by_expectation,
    summarize_records,
)
from jev_router.lab.baseline_router import BaselineRouter
from jev_router.lab.evaluator import dataset_hash, evaluate, load_cases, write_report
from jev_router.lab.logging import configure_logging, log_decision
from jev_router.lab.tool_catalog import CATALOG, execute_mock
from jev_router.lab.tool_preparation import prepare_tool_call
from jev_router.models import MockResult, Model, RoutingDecision, RoutingRequest
from jev_router.public import JevToolRouter

app = typer.Typer(
    no_args_is_help=True, help="Compare hierarchical tool routers. All tool execution is mocked."
)


class RouterSelection(StrEnum):
    auto = "auto"
    jev = "jev"
    baseline = "baseline"
    both = "both"


class RouteResult(Model):
    decision: RoutingDecision
    execution: MockResult | None = None
    execution_status: str = "not_requested"


class Comparison(Model):
    jev: RoutingDecision
    baseline: RoutingDecision
    agreement: bool | None
    outcome_agreement: bool


def settings_from_environment() -> Settings:
    configure_logging()
    try:
        return Settings()
    except ValidationError as error:
        fields = ", ".join(str(item["loc"][0]) for item in error.errors())
        raise typer.BadParameter(
            f"Invalid configuration fields: {fields}; check .env.example"
        ) from None


def make_request(request: str, context: str) -> RoutingRequest:
    try:
        return RoutingRequest(user_request=request, recent_context=context)
    except ValidationError:
        raise typer.BadParameter(
            "Request must contain 1–20000 characters; context at most 20000"
        ) from None


def readable_decision(d: RoutingDecision) -> str:
    cost = (
        f"${d.estimated_cost_usd:.8f}"
        if d.estimated_cost_usd is not None
        else "unknown/unconfigured"
    )
    domain_confidence = (
        f"{d.domain_confidence:.3f}" if d.domain_confidence is not None else "unknown"
    )
    tool_confidence = f"{d.tool_confidence:.3f}" if d.tool_confidence is not None else "unknown"
    return (
        f"{d.router} ({d.model}): {d.outcome}\n"
        f"  Domain: {d.selected_domain or '—'}; tool: {d.selected_tool or '—'}\n"
        f"  Confidence: domain={domain_confidence}, tool={tool_confidence} "
        f"({d.confidence_source})\n"
        f"  Approval required: {d.requires_approval}; fallback: {d.fallback_reason or '—'}\n"
        f"  Latency: {d.latency_ms:.1f} ms; tokens: {d.usage.input_tokens} in / "
        f"{d.usage.output_tokens} out (complete={d.usage.complete}); estimated cost: {cost}"
    )


@app.command()
def route(
    request: Annotated[str, typer.Argument(help="Request to classify")],
    approve: Annotated[
        bool, typer.Option("--approve", help="Approve and run the mock simulation only")
    ] = False,
    execute: Annotated[
        bool, typer.Option("--execute", help="Attempt mock simulation; does not grant approval")
    ] = False,
    context: Annotated[str, typer.Option(help="Only context needed for routing")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    settings = settings_from_environment()
    state = make_request(request, context)

    async def run() -> RouteResult:
        router = JevRouter(settings, tools=list(CATALOG.values()), prepare_call=prepare_tool_call)
        try:
            decision = await router.route(state)
        finally:
            await router.aclose()
        result = RouteResult(decision=decision)
        attempted = (approve or execute) and decision.outcome == "route"
        if attempted:
            try:
                prepared = decision.tool_call or prepare_tool_call(decision, state)
                if prepared.status == "needs_clarification":
                    result.execution_status = "input_required"
                else:
                    result.execution = execute_mock(decision, prepared=prepared, approved=approve)
                    result.execution_status = "simulated"
            except PermissionError:
                result.execution_status = "approval_required"
            except ValueError:
                result.execution_status = "invalid_route"
        elif approve or execute:
            result.execution_status = "not_routable"
        log_decision(state, decision, settings, mock_execution_attempted=attempted)
        return result

    result = asyncio.run(run())
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(readable_decision(result.decision))
        typer.echo(f"Mock execution: {result.execution_status}")
        if result.execution:
            typer.echo(result.execution.model_dump_json(indent=2))


@app.command()
def compare(
    request: Annotated[str, typer.Argument()],
    context: Annotated[str, typer.Option()] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    settings = settings_from_environment()
    state = make_request(request, context)

    async def run() -> Comparison:
        jev, baseline = (
            JevRouter(settings, tools=list(CATALOG.values()), prepare_call=prepare_tool_call),
            BaselineRouter(settings),
        )
        try:
            first = await jev.route(state)
            second = await baseline.route(state)
        finally:
            await jev.aclose()
            await baseline.aclose()
        for decision in (first, second):
            log_decision(state, decision, settings)
        agreement = (
            None
            if "fallback" in (first.outcome, second.outcome)
            else (
                first.outcome == second.outcome
                and first.selected_domain == second.selected_domain
                and first.selected_tool == second.selected_tool
            )
        )
        return Comparison(
            jev=first,
            baseline=second,
            agreement=agreement,
            outcome_agreement=first.outcome == second.outcome,
        )

    result = asyncio.run(run())
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(readable_decision(result.jev))
        typer.echo(readable_decision(result.baseline))
        typer.echo(
            f"Routing agreement: {result.agreement}; outcome agreement: {result.outcome_agreement}"
        )


@app.command(name="eval")
def evaluate_command(
    dataset: Annotated[Path, typer.Option(exists=True, dir_okay=False)] = Path(
        "experiments/shared_cases.json"
    ),
    output_dir: Annotated[Path, typer.Option()] = Path("experiments/results"),
    routers: Annotated[
        RouterSelection, typer.Option(help="auto includes baseline when configured")
    ] = RouterSelection.auto,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    diagnostic_stage_two: Annotated[
        bool,
        typer.Option("--diagnostic-stage-two", help="Run Stage 2 after a model clarification"),
    ] = False,
) -> None:
    settings = settings_from_environment()
    settings = settings.model_copy(update={"diagnostic_stage_two": diagnostic_stage_two})
    try:
        cases = load_cases(dataset)
    except (OSError, ValueError):
        raise typer.BadParameter(
            "Unable to read a valid evaluation dataset; check schema and IDs"
        ) from None

    async def run() -> str:
        jev, baseline = (
            JevRouter(settings, tools=list(CATALOG.values()), prepare_call=prepare_tool_call),
            BaselineRouter(settings),
        )
        selected: dict[str, Router] = {}
        if routers != RouterSelection.baseline:
            selected["jev"] = jev
        if routers in (RouterSelection.baseline, RouterSelection.both) or (
            routers == RouterSelection.auto and not baseline.provider.configuration_error
        ):
            selected["baseline"] = baseline
        try:
            report = await evaluate(cases, selected, settings, dataset_hash(dataset))
            path = write_report(report, output_dir)
        finally:
            await jev.aclose()
            await baseline.aclose()
        if json_output:
            return json.dumps(
                {"report_path": str(path.resolve()), "report": report.model_dump(mode="json")},
                indent=2,
            )
        lines = [f"Report: {path.resolve()}"]
        for name, result in report.routers.items():
            lines.append(f"{name}: " + result.metrics.model_dump_json(indent=2))
        return "\n".join(lines)

    try:
        typer.echo(asyncio.run(run()))
    except OSError:
        raise typer.BadParameter(
            "Could not write the evaluation report; check output-directory permissions"
        ) from None


@app.command(name="agent-bench")
def agent_benchmark_command(
    live: Annotated[
        bool, typer.Option(help="Explicitly enable paid Jev and OpenRouter calls")
    ] = False,
    dataset: Annotated[Path, typer.Option()] = Path("experiments/shared_cases.json"),
    limit: Annotated[int, typer.Option(min=1, help="Number of paired tasks to run")] = 100,
    output_dir: Annotated[Path, typer.Option()] = Path("experiments/results"),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Compare mock-agent task completion with all tools versus Jev-filtered tools."""
    if not live:
        raise typer.BadParameter("Pass --live to allow paid model calls")
    settings = settings_from_environment()
    if settings.typesafe_api_key is None or not settings.typesafe_api_key.get_secret_value():
        raise typer.BadParameter("Set TYPESAFE_API_KEY for the Jev benchmark arm")
    if settings.openrouter_api_key is None or not settings.openrouter_api_key.get_secret_value():
        raise typer.BadParameter("Set OPENROUTER_API_KEY for the agent model")
    if not settings.baseline_model:
        raise typer.BadParameter("Set BASELINE_MODEL to a tool-capable OpenRouter model")
    assert settings.openrouter_api_key is not None
    openrouter_key = settings.openrouter_api_key.get_secret_value()
    try:
        tasks = load_agent_tasks(dataset)[:limit]
    except (OSError, ValueError):
        raise typer.BadParameter("Unable to read the agent benchmark dataset") from None

    async def run() -> AgentBenchmarkReport:
        client = AsyncOpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            max_retries=0,
            timeout=settings.baseline_routing_timeout_ms / 1000,
        )
        agent = OpenRouterAgent(client, settings.baseline_model)
        records = []
        try:
            async with JevToolRouter(list(CATALOG.values()), settings) as router:

                async def route_request(request: str, context: str) -> RoutingDecision:
                    return await router.route(request, context=context)

                for index, task in enumerate(tasks):
                    arms: tuple[Literal["flat", "jev"], Literal["flat", "jev"]] = (
                        ("jev", "flat") if index % 2 == 0 else ("flat", "jev")
                    )
                    for arm in arms:
                        record = await run_task(
                            task, arm, agent, route_request if arm == "jev" else None
                        )
                        records.append(record)
                        status = "pass" if record.success else record.failure_reason
                        typer.echo(
                            f"{task.id} {arm}: {status}",
                            err=True,
                        )
        finally:
            await client.close()
        summaries = {
            arm: summarize_records(
                [record for record in records if record.arm == arm],
                input_price=settings.baseline_input_price_per_million,
                output_price=settings.baseline_output_price_per_million,
                routing_input_price=settings.jev_input_price_per_million,
                routing_output_price=settings.jev_output_price_per_million,
            )
            for arm in ("flat", "jev")
        }
        return AgentBenchmarkReport(
            model=settings.baseline_model,
            tool_count=len(CATALOG),
            dataset_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest(),
            settings=settings.report_config(),
            summaries=summaries,
            by_expectation={
                arm: summarize_by_expectation(
                    [record for record in records if record.arm == arm],
                    input_price=settings.baseline_input_price_per_million,
                    output_price=settings.baseline_output_price_per_million,
                    routing_input_price=settings.jev_input_price_per_million,
                    routing_output_price=settings.jev_output_price_per_million,
                )
                for arm in ("flat", "jev")
            },
            cases=records,
        )

    report = asyncio.run(run())
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"agent-bench-{timestamp}.json"
    path.write_text(report.model_dump_json(indent=2) + "\n")
    if json_output:
        typer.echo(
            json.dumps(
                {"report_path": str(path.resolve()), "report": report.model_dump(mode="json")},
                indent=2,
            )
        )
    else:
        typer.echo(f"Report: {path.resolve()}")
        for arm, summary in report.summaries.items():
            completed_latency = (
                f"{summary.mean_success_latency_ms:.0f}"
                if summary.mean_success_latency_ms is not None
                else "n/a"
            )
            typer.echo(
                f"{arm}: {summary.success_count}/{summary.task_count} tasks; "
                f"mean completed-task latency {completed_latency} ms; "
                f"{summary.total_input_tokens} input / "
                f"{summary.total_output_tokens} output tokens; "
                f"estimated cost {summary.estimated_cost_usd} USD; "
                f"cost per completion {summary.cost_per_success_usd} USD"
            )
            if summary.missing_routing_usage_calls:
                typer.echo(
                    f"  known minimum cost {summary.known_minimum_cost_usd} USD; "
                    f"{summary.missing_routing_usage_calls} routing calls lack usage"
                )
            for expectation, group in report.by_expectation[arm].items():
                latency = (
                    f"{group.mean_latency_ms:.0f}" if group.mean_latency_ms is not None else "n/a"
                )
                typer.echo(
                    f"  {expectation}: {group.success_count}/{group.task_count}; "
                    f"mean latency {latency} ms; estimated cost {group.estimated_cost_usd} USD"
                )


if __name__ == "__main__":
    app()
