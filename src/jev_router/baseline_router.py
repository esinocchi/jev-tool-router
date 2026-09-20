"""Optional OpenRouter Chat Completions baseline using the same questions and policy."""

import json
from typing import Any, TypeVar

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI

from jev_router.config import Settings
from jev_router.errors import RoutingFailure
from jev_router.models import (
    ChoiceJudgment,
    DomainJudgment,
    Model,
    Probability,
    RoutingRequest,
    TokenUsage,
)
from jev_router.questions import (
    DOMAIN_INSTRUCTIONS,
    DOMAIN_OPTIONS,
    SIGNAL_INSTRUCTIONS,
    TOOL_INSTRUCTIONS,
    tool_options,
)
from jev_router.routing_service import HierarchicalRouter


class BaselineToolOutput(Model):
    selected: str
    probabilities: dict[str, Probability]
    confidence: Probability

    def judgment(self) -> ChoiceJudgment:
        return ChoiceJudgment(
            selected=self.selected, probabilities=self.probabilities, confidence=self.confidence
        )


def output_schema(schema: type[Model], options: dict[str, str]) -> dict[str, Any]:
    """Require every offered label in the wire schema, not just in prose."""
    result = schema.model_json_schema()
    result["properties"]["selected"]["enum"] = list(options)
    result["properties"]["probabilities"] = {
        "type": "object",
        "properties": {label: {"type": "number", "minimum": 0, "maximum": 1} for label in options},
        "required": list(options),
        "additionalProperties": False,
    }
    return result


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RoutingFailure("duplicate_json_keys")
        result[key] = value
    return result


def api_failure(error: APIError) -> RoutingFailure:
    if isinstance(error, APITimeoutError):
        return RoutingFailure("timeout")
    if isinstance(error, APIConnectionError):
        return RoutingFailure("api_connection")
    if isinstance(error, APIStatusError):
        reasons = {
            400: "api_bad_request",
            401: "api_authentication",
            403: "api_permission",
            404: "api_not_found",
            422: "api_bad_request",
            429: "api_rate_limit",
        }
        return RoutingFailure(
            reasons.get(
                error.status_code, "api_server_error" if error.status_code >= 500 else "api_error"
            )
        )
    return RoutingFailure("api_error")


class BaselineDomainOutput(BaselineToolOutput):
    needs_clarification: Probability
    likely_mutation: Probability
    high_consequence: Probability


OutputT = TypeVar("OutputT", bound=BaselineToolOutput)


class BaselineProvider:
    name = "baseline"
    confidence_source = "self_reported"

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        self.settings = settings
        self.model = settings.baseline_model.strip()
        self.client = client
        self.owns_client = client is None
        self.configuration_error = (
            "missing_baseline_configuration"
            if not self.model
            or (
                client is None
                and (
                    not settings.openrouter_api_key
                    or not settings.openrouter_api_key.get_secret_value().strip()
                )
            )
            else None
        )

    def get_client(self) -> AsyncOpenAI:
        if self.client is None:
            assert self.settings.openrouter_api_key is not None
            self.client = AsyncOpenAI(
                api_key=self.settings.openrouter_api_key.get_secret_value(),
                base_url="https://openrouter.ai/api/v1",
                max_retries=0,
                timeout=self.settings.baseline_routing_timeout_ms / 1000,
            )
        return self.client

    async def _call(
        self,
        request: RoutingRequest,
        instructions: str,
        options: dict[str, str],
        signals: dict[str, str],
        schema: type[OutputT],
        usage: TokenUsage,
    ) -> OutputT:
        client = self.get_client()
        usage.start_call()
        try:
            response = await client.chat.completions.create(
                model=self.model,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": True,
                        "schema": output_schema(schema, options),
                    },
                },
                extra_body={"provider": {"require_parameters": True, "allow_fallbacks": False}},
                messages=[
                    {
                        "role": "system",
                        "content": json.dumps(
                            {
                                "instructions": instructions,
                                "options": options,
                                "binary_questions": signals,
                                "output_instructions": (
                                    "Return exactly the supplied option labels, one probability "
                                    "for each, summing "
                                    "to one, and select a maximum-probability label. Return "
                                    "confidence in the "
                                    "selection and yes-probabilities for binary questions "
                                    "when supplied. "
                                    "These are your self-reported estimates, not measured "
                                    "token probabilities."
                                ),
                            }
                        ),
                    },
                    {"role": "user", "content": json.dumps(request.state())},
                ],
            )
        except APIError as error:
            raise api_failure(error) from None
        if response.usage is not None:
            usage.record(
                response.usage.prompt_tokens, response.usage.completion_tokens, response.model
            )
        else:
            usage.response_models.append(response.model)
        if not response.choices:
            raise RoutingFailure("empty_response")
        choice = response.choices[0]
        if choice.message.refusal:
            raise RoutingFailure("provider_refusal")
        if choice.finish_reason != "stop":
            raise RoutingFailure("incomplete_response")
        if not choice.message.content:
            raise RoutingFailure("empty_response")
        try:
            payload = json.loads(choice.message.content, object_pairs_hook=unique_json_object)
        except json.JSONDecodeError:
            raise RoutingFailure("invalid_json") from None
        output = schema.model_validate(payload)
        if set(output.probabilities) - set(options):
            raise RoutingFailure("unknown_probability_labels")
        if set(options) - set(output.probabilities):
            raise RoutingFailure("missing_probability_labels")
        return output

    async def judge_domain(self, request: RoutingRequest, usage: TokenUsage) -> DomainJudgment:
        output = await self._call(
            request,
            DOMAIN_INSTRUCTIONS,
            DOMAIN_OPTIONS,
            SIGNAL_INSTRUCTIONS,
            BaselineDomainOutput,
            usage,
        )
        return DomainJudgment(
            choice=output.judgment(),
            needs_clarification=output.needs_clarification,
            likely_mutation=output.likely_mutation,
            high_consequence=output.high_consequence,
        )

    async def judge_tool(
        self, request: RoutingRequest, domain: str, usage: TokenUsage
    ) -> ChoiceJudgment:
        output = await self._call(
            request, TOOL_INSTRUCTIONS, tool_options(domain), {}, BaselineToolOutput, usage
        )
        return output.judgment()

    async def aclose(self) -> None:
        if self.owns_client and self.client is not None:
            await self.client.close()


class BaselineRouter(HierarchicalRouter):
    provider: BaselineProvider

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        super().__init__(BaselineProvider(settings, client), settings)

    async def aclose(self) -> None:
        await self.provider.aclose()
