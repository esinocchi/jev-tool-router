"""Optional OpenAI Responses baseline using the same questions and policy."""

import json
from typing import TypeVar

from openai import AsyncOpenAI

from jev_router.config import Settings
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


class LabelProbability(Model):
    label: str
    probability: Probability


class BaselineToolOutput(Model):
    selected: str
    probabilities: list[LabelProbability]
    confidence: Probability

    def judgment(self) -> ChoiceJudgment:
        probabilities = {item.label: item.probability for item in self.probabilities}
        if len(probabilities) != len(self.probabilities):
            raise ValueError("Duplicate probability labels")
        return ChoiceJudgment(
            selected=self.selected, probabilities=probabilities, confidence=self.confidence
        )


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
                    not settings.openai_api_key
                    or not settings.openai_api_key.get_secret_value().strip()
                )
            )
            else None
        )

    def get_client(self) -> AsyncOpenAI:
        if self.client is None:
            assert self.settings.openai_api_key is not None
            self.client = AsyncOpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                base_url="https://api.openai.com/v1",
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
        response = await client.responses.parse(
            model=self.model,
            store=False,
            text_format=schema,
            input=[
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
        if response.usage is not None:
            usage.record(response.usage.input_tokens, response.usage.output_tokens, response.model)
        else:
            usage.response_models.append(response.model)
        if response.status != "completed" or response.output_parsed is None:
            raise ValueError("Refused, incomplete, or missing structured output")
        return response.output_parsed

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
