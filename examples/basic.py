"""Smallest live route. Set TYPESAFE_API_KEY before running this file."""

import asyncio

from jev_router import JevToolRouter, Tool


async def main() -> None:
    tools = [
        Tool(
            name="search_docs",
            domain="knowledge",
            description="Search the company's documentation by topic.",
            read_only=True,
        ),
        Tool(
            name="create_ticket",
            domain="support",
            description="Create a support ticket for a customer issue.",
        ),
    ]
    async with JevToolRouter(tools) as router:
        decision = await router.route("Find the SSO setup guide")
    if decision.outcome == "route":
        print(decision.selected_tool, decision.requires_approval)
    else:
        print(decision.outcome, decision.fallback_reason or decision.clarification_reason)


if __name__ == "__main__":
    asyncio.run(main())
