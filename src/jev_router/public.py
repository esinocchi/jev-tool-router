"""Public Python API for describing tools supplied by an application."""

from collections.abc import Mapping
from typing import Any, Literal

from typesafe_sdk import AsyncTypeSafeClient

from jev_router.config import Settings
from jev_router.jev_router import JevRouter
from jev_router.models import ToolDomain
from jev_router.tool_catalog import ToolDefinition


class JevToolRouter(JevRouter):
    """Route against application-supplied tools; this class never executes them."""

    def __init__(
        self,
        tools: list[ToolDefinition],
        settings: Settings,
        client: AsyncTypeSafeClient | None = None,
    ):
        super().__init__(settings, client=client, tools=tools)


class Tool(ToolDefinition):
    """A trusted application tool description. Routing never executes this tool."""

    @classmethod
    def from_mcp_schema(
        cls,
        schema: Mapping[str, Any],
        *,
        domain: ToolDomain,
        read_only: bool = True,
        risk: Literal["low", "medium", "high"] = "low",
    ) -> "Tool":
        input_schema = schema.get("inputSchema", schema.get("input_schema", {}))
        if not isinstance(input_schema, dict):
            raise ValueError("MCP tool inputSchema must be an object")
        required = input_schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
            raise ValueError("MCP tool inputSchema.required must be a list of strings")
        return cls(
            name=str(schema["name"]),
            domain=domain,
            description=str(schema["description"]),
            read_only=read_only,
            risk=risk,
            required_arguments=tuple(required),
            input_schema=input_schema,
            output_schema={},
        )
