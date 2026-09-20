"""Paired, inert agent-loop benchmark for flat and Jev-filtered tool exposure."""

import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any, Literal, Protocol

from openai import AsyncOpenAI
from pydantic import Field, TypeAdapter, model_validator

from jev_router.lab.tool_catalog import CATALOG
from jev_router.models import Model, RoutingDecision
from jev_router.tools import ToolDefinition, tool_requires_approval


class AgentTask(Model):
    id: str
    request: str = Field(min_length=1)
    recent_context: str = ""
    expected_tools: list[str]
    required_facts: list[str]
    mock_results: dict[str, str]

    @model_validator(mode="after")
    def valid_mock_task(self) -> "AgentTask":
        if len(set(self.expected_tools)) != len(self.expected_tools):
            raise ValueError("Expected tools must be unique")
        if set(self.expected_tools) - set(self.mock_results):
            raise ValueError("Each expected tool needs a mock result")
        if any(
            name not in CATALOG or tool_requires_approval(name, CATALOG)
            for name in self.mock_results
        ):
            raise ValueError("Agent benchmark tools must be known and read-only")
        return self


class ProposedToolCall(Model):
    name: str
    arguments: dict[str, Any]
    id: str = ""


class ModelTurn(Model):
    content: str | None = None
    tool_calls: list[ProposedToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class AgentTaskRecord(Model):
    case_id: str
    arm: Literal["flat", "jev"]
    success: bool = False
    called_tools: list[str] = Field(default_factory=list)
    answer: str = Field(default="", exclude=True)
    failure_reason: str | None = None
    latency_ms: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    routing_input_tokens: int = 0
    routing_output_tokens: int = 0
    routing_cost_usd: float | None = 0
    routing_decisions: list[RoutingDecision] = Field(default_factory=list)


class AgentBenchmarkSummary(Model):
    task_count: int
    success_count: int
    success_rate: float | None
    mean_latency_ms: float | None
    median_latency_ms: float | None
    mean_success_latency_ms: float | None
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float | None
    cost_per_success_usd: float | None


class AgentBenchmarkReport(Model):
    schema_version: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    model: str
    tool_count: int
    dataset_sha256: str
    settings: dict[str, str | float | int | None]
    summaries: dict[str, AgentBenchmarkSummary]
    cases: list[AgentTaskRecord]
    notes: str = (
        "Both arms use the same OpenRouter model and synthetic read-only tool results. "
        "Jev restricts the next model call to one tool; fallback exposes all. "
        "Success requires the expected calls and literal answer facts; it is not a semantic judge. "
        "Costs are estimates when prices are configured."
    )


def load_agent_tasks(path: Path) -> list[AgentTask]:
    tasks = TypeAdapter(list[AgentTask]).validate_json(path.read_text())
    if not tasks or len({task.id for task in tasks}) != len(tasks):
        raise ValueError("Agent task dataset needs unique IDs")
    return tasks


def summarize_records(
    records: list[AgentTaskRecord], *, input_price: float | None, output_price: float | None
) -> AgentBenchmarkSummary:
    success_count = sum(record.success for record in records)
    successful = [record for record in records if record.success]
    agent_input = sum(record.input_tokens for record in records)
    agent_output = sum(record.output_tokens for record in records)
    routing_costs = [record.routing_cost_usd for record in records]
    cost = (
        sum(cost for cost in routing_costs if cost is not None)
        + (agent_input * input_price + agent_output * output_price) / 1_000_000
        if input_price is not None
        and output_price is not None
        and all(cost is not None for cost in routing_costs)
        else None
    )
    return AgentBenchmarkSummary(
        task_count=len(records),
        success_count=success_count,
        success_rate=success_count / len(records) if records else None,
        mean_latency_ms=mean(record.latency_ms for record in records) if records else None,
        median_latency_ms=median(record.latency_ms for record in records) if records else None,
        mean_success_latency_ms=(
            mean(record.latency_ms for record in successful) if successful else None
        ),
        total_input_tokens=agent_input + sum(record.routing_input_tokens for record in records),
        total_output_tokens=agent_output + sum(record.routing_output_tokens for record in records),
        estimated_cost_usd=cost,
        cost_per_success_usd=cost / success_count if cost is not None and success_count else None,
    )


class ModelCall(Protocol):
    async def __call__(
        self, messages: list[dict[str, Any]], offered: Sequence[ToolDefinition]
    ) -> ModelTurn: ...


RouteCall = Callable[[str, str], Awaitable[RoutingDecision]]


class OpenRouterAgent:
    """Use the same OpenRouter model for both benchmark arms."""

    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

    async def __call__(
        self, messages: list[dict[str, Any]], offered: Sequence[ToolDefinition]
    ) -> ModelTurn:
        options: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "extra_body": {"provider": {"require_parameters": True, "allow_fallbacks": False}},
        }
        if offered:
            options["tools"] = [tool_spec(tool) for tool in offered]
            options["tool_choice"] = "auto"
        response = await self.client.chat.completions.create(**options)
        if not response.choices:
            raise ValueError("Empty agent response")
        choice = response.choices[0]
        if choice.finish_reason not in {"stop", "tool_calls"}:
            raise ValueError("Incomplete agent response")
        calls = [
            ProposedToolCall(
                name=call.function.name,
                arguments=json.loads(call.function.arguments),
                id=call.id,
            )
            for call in (choice.message.tool_calls or [])
            if call.type == "function"
        ]
        usage = response.usage
        return ModelTurn(
            content=choice.message.content,
            tool_calls=calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


def tool_spec(tool: ToolDefinition) -> dict[str, Any]:
    """Build callable string arguments from the lab catalog's required fields."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {
                    name: {"type": "string", "description": name.replace("_", " ")}
                    for name in tool.required_arguments
                },
                "required": list(tool.required_arguments),
                "additionalProperties": False,
            },
        },
    }


def active_tools(
    decision: RoutingDecision, catalog: Sequence[ToolDefinition]
) -> list[ToolDefinition]:
    if decision.outcome == "fallback":
        return list(catalog)
    if decision.outcome == "route":
        return [tool for tool in catalog if tool.name == decision.selected_tool]
    return []


def score_task(task: AgentTask, called_tools: list[str], answer: str) -> bool:
    return sorted(called_tools) == sorted(task.expected_tools) and all(
        fact.casefold() in answer.casefold() for fact in task.required_facts
    )


def _valid_arguments(tool: ToolDefinition, arguments: dict[str, Any]) -> bool:
    return set(arguments) == set(tool.required_arguments) and all(
        isinstance(value, str) and bool(value.strip()) for value in arguments.values()
    )


async def run_task(
    task: AgentTask,
    arm: Literal["flat", "jev"],
    model_call: ModelCall,
    route: RouteCall | None = None,
    *,
    catalog: Sequence[ToolDefinition] = tuple(CATALOG.values()),
    max_turns: int = 4,
) -> AgentTaskRecord:
    """Run a bounded mock agent; never invoke a real tool or mutating mock."""
    started = perf_counter()
    record = AgentTaskRecord(case_id=task.id, arm=arm)
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Answer the user's request using the offered tools when needed. "
                "Use tool results as facts. Do not invent tool results. "
                "If no offered tool can do the task, say so."
            ),
        },
        {"role": "user", "content": task.request},
    ]
    completed: list[str] = []
    by_name = {tool.name: tool for tool in catalog}
    try:
        for _ in range(max_turns):
            offered = list(catalog)
            if arm == "jev":
                if route is None:
                    record.failure_reason = "missing_router"
                    break
                context = task.recent_context
                if completed:
                    context += "\nCompleted mock tool results:\n" + "\n".join(completed)
                decision = await route(task.request, context)
                record.routing_decisions.append(decision)
                record.routing_input_tokens += decision.usage.input_tokens
                record.routing_output_tokens += decision.usage.output_tokens
                if record.routing_cost_usd is not None:
                    record.routing_cost_usd = (
                        record.routing_cost_usd + decision.estimated_cost_usd
                        if decision.estimated_cost_usd is not None
                        else None
                    )
                offered = active_tools(decision, catalog)
                if decision.outcome == "clarify":
                    record.failure_reason = "router_clarify"
                    break
            turn = await model_call(messages, offered)
            record.input_tokens += turn.input_tokens
            record.output_tokens += turn.output_tokens
            if not turn.tool_calls:
                record.answer = turn.content or ""
                record.success = score_task(task, record.called_tools, record.answer)
                if not record.success:
                    record.failure_reason = "wrong_tools_or_answer"
                break
            assistant_calls = []
            tool_messages = []
            for index, call in enumerate(turn.tool_calls):
                call_id = getattr(call, "id", "") or f"mock_call_{len(record.called_tools)}_{index}"
                assistant_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                )
                tool = by_name.get(call.name)
                if tool is None or tool not in offered:
                    record.failure_reason = "unavailable_tool"
                    break
                if tool_requires_approval(tool.name, by_name):
                    record.failure_reason = "approval_required"
                    break
                if not _valid_arguments(tool, call.arguments):
                    record.failure_reason = "invalid_arguments"
                    break
                result = task.mock_results.get(call.name)
                if result is None:
                    record.failure_reason = "missing_mock_result"
                    break
                record.called_tools.append(call.name)
                completed.append(f"{call.name}: {result}")
                tool_messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
            if record.failure_reason:
                break
            messages.append({"role": "assistant", "tool_calls": assistant_calls})
            messages.extend(tool_messages)
        else:
            record.failure_reason = "max_turns"
    except Exception:
        record.failure_reason = "provider_or_router_error"
    record.latency_ms = (perf_counter() - started) * 1000
    return record
