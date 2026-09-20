"""Public Python API for describing tools supplied by an application."""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel
from typesafe_sdk import AsyncTypeSafeClient

from jev_router.config import Settings
from jev_router.jev_router import JevRouter
from jev_router.models import RoutingDecision, RoutingRequest, ToolDomain
from jev_router.tools import ToolDefinition


class JevToolRouter(JevRouter):
    """Route against application-supplied tools; this class never executes them."""

    def __init__(
        self,
        tools: Sequence[ToolDefinition],
        settings: Settings | None = None,
        client: AsyncTypeSafeClient | None = None,
    ):
        if any(tool.domain in {"none", "other"} for tool in tools):
            raise ValueError("none and other are reserved domains")
        if any(tool.name == "none_of_the_above" for tool in tools):
            raise ValueError("none_of_the_above is a reserved tool name")
        super().__init__(settings or Settings(), client=client, tools=tools)

    async def route(self, request: str | RoutingRequest, *, context: str = "") -> RoutingDecision:
        state = (
            RoutingRequest(user_request=request, recent_context=context)
            if isinstance(request, str)
            else request
        )
        return await super().route(state)

    async def __aenter__(self) -> "JevToolRouter":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


class Tool(ToolDefinition):
    """A trusted application tool description. Routing never executes this tool."""

    @classmethod
    def from_mcp_schema(
        cls,
        schema: Mapping[str, Any] | BaseModel,
        *,
        domain: ToolDomain,
        read_only: bool = False,
        risk: Literal["low", "medium", "high"] = "medium",
    ) -> "Tool":
        data: Mapping[str, Any] = (
            schema.model_dump(mode="json", by_alias=True, exclude_none=True)
            if isinstance(schema, BaseModel)
            else schema
        )
        name = data.get("name")
        description = data.get("description")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("MCP tool name must be a nonempty string")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("MCP tool description must be a nonempty string")
        input_schema = data.get("inputSchema", data.get("input_schema", {}))
        if not isinstance(input_schema, dict):
            raise ValueError("MCP tool inputSchema must be an object")
        required = input_schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
            raise ValueError("MCP tool inputSchema.required must be a list of strings")
        return cls(
            name=name,
            domain=domain,
            description=description,
            read_only=read_only,
            risk=risk,
            required_arguments=tuple(required),
            input_schema=input_schema,
            output_schema={},
        )
