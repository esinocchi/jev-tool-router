"""TypeSafe-specific translation; no security decisions are delegated to the SDK."""

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy, SystemOneResponse

from jev_router.config import Settings
from jev_router.models import ChoiceJudgment, DomainJudgment, RoutingRequest, TokenUsage
from jev_router.questions import (
    DOMAIN_INSTRUCTIONS,
    DOMAIN_OPTIONS,
    SIGNAL_INSTRUCTIONS,
    TOOL_INSTRUCTIONS,
    tool_options,
)
from jev_router.routing_service import HierarchicalRouter


def domain_questions() -> dict[str, Choice | Noul]:
    return {
        "tool_domain": Choice(instructions=DOMAIN_INSTRUCTIONS, criteria=DOMAIN_OPTIONS),
        **{key: Noul(instructions=value) for key, value in SIGNAL_INSTRUCTIONS.items()},
    }


def tool_questions(domain: str) -> dict[str, Choice]:
    return {"tool": Choice(instructions=TOOL_INSTRUCTIONS, criteria=tool_options(domain))}


class JevProvider:
    name = "jev"
    confidence_source = "typesafe_distribution"

    def __init__(self, settings: Settings, client: AsyncTypeSafeClient | None = None):
        self.settings = settings
        self.model = settings.jev_model
        self.client = client
        self.owns_client = client is None
        self.configuration_error = (
            "missing_typesafe_api_key"
            if client is None
            and (
                not settings.typesafe_api_key
                or not settings.typesafe_api_key.get_secret_value().strip()
            )
            else None
        )

    def get_client(self) -> AsyncTypeSafeClient:
        if self.client is None:
            assert self.settings.typesafe_api_key is not None
            self.client = AsyncTypeSafeClient(
                api_key=self.settings.typesafe_api_key.get_secret_value(),
                model=self.model,
                base_url="https://api.typesafe.ai",
                retry=RetryPolicy(max_retries=0),
                timeout=self.settings.jev_routing_timeout_ms / 1000,
            )
        return self.client

    async def _call(
        self, request: RoutingRequest, questions: dict[str, Choice | Noul], usage: TokenUsage
    ) -> SystemOneResponse:
        client = self.get_client()
        usage.start_call()
        response = await client.system_one(
            state=request.state(), questions=questions, model=self.model
        )
        usage.record(response.usage.input_tokens, response.usage.output_tokens, response.model)
        return response

    async def judge_domain(self, request: RoutingRequest, usage: TokenUsage) -> DomainJudgment:
        response = await self._call(request, domain_questions(), usage)
        answer = response.choices["tool_domain"]
        return DomainJudgment(
            choice=ChoiceJudgment(
                selected=answer.choice,
                probabilities=answer.probabilities,
                confidence=answer.confidence,
            ),
            needs_clarification=response.nouls["needs_clarification"].noul,
            likely_mutation=response.nouls["likely_mutation"].noul,
            high_consequence=response.nouls["high_consequence"].noul,
        )

    async def judge_tool(
        self, request: RoutingRequest, domain: str, usage: TokenUsage
    ) -> ChoiceJudgment:
        questions: dict[str, Choice | Noul] = dict(tool_questions(domain))
        response = await self._call(request, questions, usage)
        answer = response.choices["tool"]
        return ChoiceJudgment(
            selected=answer.choice, probabilities=answer.probabilities, confidence=answer.confidence
        )

    async def aclose(self) -> None:
        if self.owns_client and self.client is not None:
            await self.client.aclose()


class JevRouter(HierarchicalRouter):
    provider: JevProvider

    def __init__(self, settings: Settings, client: AsyncTypeSafeClient | None = None):
        super().__init__(JevProvider(settings, client), settings)

    async def aclose(self) -> None:
        await self.provider.aclose()
