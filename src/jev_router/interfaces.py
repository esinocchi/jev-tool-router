"""Routing and model-judgment interfaces."""

from typing import Protocol

from jev_router.models import (
    ChoiceJudgment,
    DomainJudgment,
    RoutingDecision,
    RoutingRequest,
    TokenUsage,
)


class Router(Protocol):
    async def route(self, request: RoutingRequest) -> RoutingDecision: ...


class JudgmentProvider(Protocol):
    name: str
    model: str
    confidence_source: str
    configuration_error: str | None

    async def judge_domain(self, request: RoutingRequest, usage: TokenUsage) -> DomainJudgment: ...
    async def judge_tool(
        self, request: RoutingRequest, domain: str, usage: TokenUsage
    ) -> ChoiceJudgment: ...
