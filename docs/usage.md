# Python SDK usage

Install from this Git repository as shown in the [quickstart](../README.md). The public import surface is `from jev_router import JevToolRouter, Tool, Settings, RoutingRequest, RoutingDecision`.

## Describe your tools

`Tool(name, domain, description, read_only=False, risk="medium")` is enough to route. Domain names are caller-defined. Each tool needs a unique name; descriptions should say what the tool does and when it differs from another tool in the same domain. The router derives the domain choices from the tools you provide on construction. Keep safety metadata in trusted application code.

MCP metadata can be adapted with `Tool.from_mcp_schema(schema, domain="...", read_only=...)`. Pass either a mapping or the Pydantic tool object returned by the MCP Python SDK; the adapter serializes that object using aliases, which handles current `input_schema`/`inputSchema` field naming. This copies the tool's name, description, and input schema, including required argument names. It does not connect to the server. If the metadata does not say whether the tool is read-only, the adapter assumes it can mutate. A remote server's annotation should be reviewed before your application marks a tool read-only.

## Route a request

```python
from jev_router import JevToolRouter, Tool

tools = [
    Tool(
        name="search_docs", domain="knowledge", description="Search documentation.", read_only=True
    )
]
async with JevToolRouter(tools) as router:
    decision = await router.route(
        "Find the onboarding guide", context="The user means internal docs."
    )
```

Use `RoutingRequest(user_request=..., recent_context=..., request_id=...)` when you already have a request ID or want a typed input. `JevToolRouter.route()` accepts either that model or a plain string. The context is sent to TypeSafe along with the request; pass only context needed for the decision.

You can provide `Settings(...)` as the second constructor argument to override environment thresholds, model alias, or timeout. `Settings()` reads `TYPESAFE_API_KEY` from the environment or `.env`. If no key is present, `route()` returns a `fallback` with `fallback_reason="missing_typesafe_api_key"`; it does not crash. `jev_routing_timeout_ms` covers both Jev stages.

## Use the result in your agent

The decision's `outcome` is one of `route`, `clarify`, `no_tool`, and `fallback`. On `route`, `selected_domain` and `selected_tool` identify an offered tool. `requires_approval` is raised by the model's mutation or consequence signals or by trusted tool metadata. Your application still needs its own permission check, argument generation, schema validation, and execution. The public router returns no executable arguments (`tool_call` is `None`).

On `clarify`, ask the user for information before retrying. `clarification_reason` distinguishes model uncertainty from missing lab placeholder arguments, though the latter only appears in experiments. On `no_tool`, the agent can answer without an external tool. On `fallback`, use your normal LLM routing path or ask the user; `fallback_reason` explains the failure or confidence gate.

## Filter tools before the model call

The useful integration point is where your agent framework builds the tool list for its next LLM request:

```text
Application's tool registry
  → JevToolRouter.route(request)
  → selected tool or shortlist policy
  → framework binds those tool schemas for the next model turn
  → agent model chooses calls and arguments
  → application validates and authorizes execution
```

Map `decision.selected_tool` back to your application's trusted tool registry. A `route` can expose that one tool; a `fallback` can expose your normal catalog or use another search mechanism. `clarify` and `no_tool` should follow their outcome handling above. This package does not currently include a framework-specific binding adapter, and the public API selects one tool rather than a multi-tool shortlist. Your framework must let you vary the tools before each model request for this pattern to work.

Keep **tool relevance** separate from **readiness to call it**. In the standalone 86-case routing test, Jev selected an acceptable candidate in all 55 cases labeled ready to route, but returned `clarify` on 24 of them. That test did not have an agent making a subsequent tool call. `selected_tool` on a `clarify` decision is useful diagnostic or shortlist information; it is not a `route` outcome, an executable call, or permission to skip clarification. A future adapter could use that candidate to focus a clarification-only turn if its execution layer can reliably block calls until the missing details and authorization are resolved. This SDK does not implement that policy.

The lab's [agent benchmark](../experiments/README.md#agent-task-benchmark) exercises this idea by passing the filtered tool list directly to [OpenRouter tool calling](https://openrouter.ai/docs/guides/features/tool-calling) in a custom mock loop. The Luna agent still selects the tool and proposes its arguments; the application returns a mock result. An application could instead constrain or force a tool through supported provider APIs, but that is a different, untested orchestration design and still does not replace the provider model's internal `auto` selection. This benchmark does not prove that a particular framework adapter accepts the hook, nor does it compare with [OpenAI's native tool search](https://developers.openai.com/api/docs/guides/tools-tool-search). The current ten-task result did not show a speed benefit with 16 tools; a larger catalog and a real adapter remain untested.

The domain and tool probabilities are Jev's response distributions. The two confidence values come from TypeSafe's choice confidence and are not calibrated probabilities of being correct. A low-confidence result is a reason to defer under the configured policy, not proof that a different tool is correct. Token usage and latency describe the routing calls and may be incomplete when a provider request fails.

## Add an MCP client later

Obtain tool metadata from your MCP client, assign trusted domain/read-only/risk labels, then route using `Tool.from_mcp_schema`. If a tool is selected, let your primary agent propose arguments, validate them against the tool's input schema, and check user authorization before calling the MCP client. Keep this router out of the execution path so a model probability cannot bypass permissions. The [experiment lab](../experiments/README.md) demonstrates selection and inert mock execution without connecting real accounts.
