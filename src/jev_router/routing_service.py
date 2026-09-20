"""Two-stage orchestration and deterministic safety policy."""

import asyncio
from time import perf_counter
from typing import cast

from jev_router.config import Settings
from jev_router.interfaces import JudgmentProvider
from jev_router.models import Domain, RoutingDecision, RoutingRequest
from jev_router.questions import DOMAIN_OPTIONS, tool_options
from jev_router.tool_catalog import tool_requires_approval


class HierarchicalRouter:
    def __init__(self, provider: JudgmentProvider, settings: Settings):
        self.provider = provider
        self.settings = settings

    async def route(self, request: RoutingRequest) -> RoutingDecision:
        started = perf_counter()
        decision = RoutingDecision(
            request_id=request.request_id,
            router=self.provider.name,
            model=self.provider.model,
            confidence_source=self.provider.confidence_source,
        )
        timeout_ms = (
            self.settings.baseline_routing_timeout_ms
            if self.provider.name == "baseline"
            else self.settings.jev_routing_timeout_ms
        )
        try:
            if self.provider.configuration_error:
                decision.fallback_reason = self.provider.configuration_error
            else:
                async with asyncio.timeout(timeout_ms / 1000):
                    await self._stages(request, decision)
        except TimeoutError:
            decision.outcome = "fallback"
            decision.fallback_reason = "timeout"
        except Exception as error:
            # Never expose exception strings: providers may include requests and credentials.
            decision.outcome = "fallback"
            decision.fallback_reason = (
                "timeout"
                if "timeout" in type(error).__name__.lower()
                else "api_or_invalid_response"
            )
        decision.latency_ms = (perf_counter() - started) * 1000
        decision.estimated_cost_usd = self.settings.cost(self.provider.name, decision.usage)
        return decision

    async def _stages(self, request: RoutingRequest, decision: RoutingDecision) -> None:
        s = self.settings
        judgment = await self.provider.judge_domain(request, decision.usage)
        judgment.choice.check_options(DOMAIN_OPTIONS)
        decision.selected_domain = cast(Domain, judgment.choice.selected)
        decision.domain_probabilities = judgment.choice.probabilities
        decision.domain_confidence = judgment.choice.confidence
        decision.needs_clarification_probability = judgment.needs_clarification
        decision.mutation_probability = judgment.likely_mutation
        decision.high_consequence_probability = judgment.high_consequence
        decision.requires_approval = (
            judgment.likely_mutation >= s.jev_mutation_threshold
            or judgment.high_consequence >= s.jev_high_consequence_threshold
        )
        if judgment.needs_clarification > s.jev_clarification_threshold:
            decision.outcome = "clarify"
            return
        if judgment.choice.confidence < s.jev_domain_confidence_threshold:
            decision.fallback_reason = "low_domain_confidence"
            return
        if decision.selected_domain == "none":
            decision.outcome = "no_tool"
            return
        if decision.selected_domain == "other":
            decision.fallback_reason = "unsupported_domain"
            return
        tool = await self.provider.judge_tool(request, decision.selected_domain, decision.usage)
        tool.check_options(tool_options(decision.selected_domain))
        decision.tool_probabilities = tool.probabilities
        decision.tool_confidence = tool.confidence
        if tool.selected != "none_of_the_above":
            decision.selected_tool = tool.selected
            decision.requires_approval |= tool_requires_approval(tool.selected)
        if tool.confidence < s.jev_tool_confidence_threshold:
            decision.fallback_reason = "low_tool_confidence"
        elif tool.selected == "none_of_the_above":
            decision.fallback_reason = "no_matching_tool"
        else:
            decision.outcome = "route"
