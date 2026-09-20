"""Provider-neutral boundaries. Provider JSON is validated before policy uses it."""

from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from jev_router.errors import RoutingFailure

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Domain = Literal["github", "browser", "files", "calendar", "none", "other"]
ToolDomain = str
Outcome = Literal["route", "no_tool", "clarify", "fallback"]
ClarificationReason = Literal["model_uncertainty", "missing_required_argument"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RoutingRequest(Model):
    user_request: str = Field(min_length=1, max_length=20000)
    recent_context: str = Field(default="", max_length=20000)
    request_id: str = Field(default_factory=lambda: str(uuid4()))

    def state(self) -> dict[str, str]:
        return {"user_request": self.user_request, "recent_context": self.recent_context}


class ChoiceJudgment(Model):
    selected: str
    probabilities: dict[str, Probability]
    confidence: Probability

    @model_validator(mode="after")
    def valid_distribution(self) -> "ChoiceJudgment":
        if self.selected not in self.probabilities:
            raise PydanticCustomError(
                "selected_label_missing", "Selected label is absent from distribution"
            )
        if abs(sum(self.probabilities.values()) - 1) > 0.02:
            raise PydanticCustomError(
                "invalid_probability_sum", "Probabilities must sum to one within rounding tolerance"
            )
        if self.probabilities[self.selected] + 1e-6 < max(self.probabilities.values()):
            raise PydanticCustomError(
                "selected_label_not_maximum", "Selected label must have maximum probability"
            )
        return self

    def check_options(self, options: dict[str, str]) -> None:
        if set(self.probabilities) - set(options):
            raise RoutingFailure("unknown_probability_labels")
        if set(options) - set(self.probabilities):
            raise RoutingFailure("missing_probability_labels")


class DomainJudgment(Model):
    choice: ChoiceJudgment
    needs_clarification: Probability
    likely_mutation: Probability
    high_consequence: Probability


class TokenUsage(Model):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    complete: bool = True
    attempted_calls: int = 0
    reported_calls: int = 0
    response_models: list[str] = Field(default_factory=list)

    def start_call(self) -> None:
        self.attempted_calls += 1
        self.complete = False

    def record(self, input_tokens: int | None, output_tokens: int | None, model: str) -> None:
        self.input_tokens += input_tokens or 0
        self.output_tokens += output_tokens or 0
        if input_tokens is not None and output_tokens is not None:
            self.reported_calls += 1
        self.response_models.append(model)
        self.complete = self.reported_calls == self.attempted_calls


class ToolCallPreparation(Model):
    """A locally derived, schema-shaped mock call. This is not model-generated input."""

    tool: str
    status: Literal["ready", "needs_clarification"]
    arguments: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    clarification: str | None = None


class RoutingDecision(Model):
    request_id: str = ""
    router: str
    model: str
    confidence_source: str = "unknown"
    selected_domain: str | None = None
    domain_probabilities: dict[str, Probability] = Field(default_factory=dict)
    domain_confidence: Probability | None = None
    selected_tool: str | None = None
    tool_probabilities: dict[str, Probability] = Field(default_factory=dict)
    tool_confidence: Probability | None = None
    needs_clarification_probability: Probability | None = None
    mutation_probability: Probability | None = None
    high_consequence_probability: Probability | None = None
    outcome: Outcome = "fallback"
    fallback_reason: str | None = None
    failure_stage: Literal["domain", "tool"] | None = None
    requires_approval: bool = False
    latency_ms: float = Field(default=0, ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    estimated_cost_usd: float | None = None
    tool_call: ToolCallPreparation | None = None
    clarification_reason: ClarificationReason | None = None


class MockArguments(Model):
    target: str = "mock://placeholder"
    fields: dict[str, str] = Field(default_factory=dict)
    payload: str = "placeholder; no user content or credentials"


class MockResult(Model):
    tool: str
    arguments: MockArguments
    simulated: Literal[True] = True
    message: str = "Would invoke this tool with these placeholder arguments; no action performed."
