"""Typer CLI. Route calls models; execution is always an inert local simulation."""

import asyncio
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from jev_router.baseline_router import BaselineRouter
from jev_router.config import Settings
from jev_router.evaluator import dataset_hash, evaluate, load_cases, write_report
from jev_router.interfaces import Router
from jev_router.jev_router import JevRouter
from jev_router.logging import configure_logging, log_decision
from jev_router.models import MockResult, Model, RoutingDecision, RoutingRequest
from jev_router.tool_catalog import execute_mock
from jev_router.tool_preparation import prepare_tool_call

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
        router = JevRouter(settings)
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
        jev, baseline = JevRouter(settings), BaselineRouter(settings)
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
        "evals/routing_cases.json"
    ),
    output_dir: Annotated[Path, typer.Option()] = Path("evals/results"),
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
        jev, baseline = JevRouter(settings), BaselineRouter(settings)
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


if __name__ == "__main__":
    app()
