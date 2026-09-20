# Routing experiments

This is the evidence and rerun guide for [the case study](../docs/case-study.md). The [public SDK](../README.md#use-the-experimental-python-sdk) is separate from the benchmark harness in `src/jev_router/lab/`. Run all commands from the repository root.

| Test | What it measures | What it does not measure | Source material |
| --- | --- | --- | --- |
| [100-prompt routing evaluation](#evaluation) | Whether Jev or a Luna-based router chooses the labeled domain and tool, plus policy outcomes, latency, and estimated cost. | A later agent tool call or full task completion. | [Shared cases](shared_cases.json) · [Run 1](published/routing-shared-100-3000ms-run1-2026-09-20.json) · [Run 2](published/routing-shared-100-3000ms-run2-2026-09-20.json) · [Run 3](published/routing-shared-100-3000ms-run3-2026-09-20.json) |
| [100-prompt agent benchmark](#agent-task-benchmark) | A Luna mock agent with all 16 tools versus the same agent after Jev filters its offered tools. | Real tool execution or provider-native tool search. | [Shared cases](shared_cases.json) · [Run 1](published/agent-bench-shared-100-3000ms-run1-2026-09-20.json) · [Run 2](published/agent-bench-shared-100-3000ms-run2-2026-09-20.json) · [Run 3](published/agent-bench-shared-100-3000ms-run3-2026-09-20.json) |

The shared-prompt reports are one routing run and two agent runs. Read them without credentials, then use the commands below if you want to create a new run. The older [86-case routing report](published/routing-2026-09-20.json) uses schema version 2; the current harness uses version 3 and catalog-derived domain descriptions. Its ordinary policy also stops before exact-tool selection on high clarification, while the old report contains stage-two selections in those cases. Use `--diagnostic-stage-two` for comparable tool-fit coverage, but do not expect an exact replay of the old prompt/protocol. New results also vary with model version, network conditions, provider behavior, and configuration. Do not overwrite the published reports. Unit tests check the harness, not model accuracy.

## Shared 100-prompt protocol for new runs

Both current commands default to [`shared_cases.json`](shared_cases.json). Its 100 IDs, request strings, and recent context are identical in the routing and agent runs. The first 86 prompts come from the original routing set; ten come from the original agent set; four add read tasks. Routing labels and agent expectations are stored together for each prompt. The published shared-prompt reports all record the same dataset SHA-256. The older 86-case and ten-task reports used different datasets and cannot be compared as if they were paired.

The shared set has 47 read tasks labeled `complete`, 21 approval cases, 13 clarification cases, ten no-tool questions, and nine unavailable-tool requests. The agent report records an overall mean latency and estimated cost for the same 100 prompts in each arm, plus `by_expectation` summaries. Use the `complete` category for mean read-task latency; that mean includes failed attempts. Approval, clarification, and unavailable-tool responses are shorter but are still included in the overall wall-clock and cost totals. The routing report measures tool fit, routing latency, and routing-call cost. The agent report measures end-to-end mock-agent latency and total estimated cost, including Jev calls in its Jev arm. It also reports success by category, rather than treating 100% success as proof of perfect tool routing.

The main published protocol repeats each test three times at a 3,000 ms Jev routing timeout. All six reports have complete usage, so their total estimated costs include both Jev routing and Luna agent calls where applicable. The figure generator [`render_benchmark_figures.py`](render_benchmark_figures.py) reads all six reports and plots medians. A report with missing provider usage still records `known_minimum_cost_usd` and `missing_routing_usage_calls`, while `estimated_cost_usd` remains null. The earlier 1,500 ms [routing report](published/routing-shared-100-2026-09-20.json) and [agent runs](published/agent-bench-shared-100-run1-2026-09-20.json) ([second](published/agent-bench-shared-100-run2-2026-09-20.json)) remain historical; each old agent run had one missing-usage timeout and thus no exact Jev total.

Agent completion requires exactly the expected read-only calls and literal answer facts. No-tool cases require an answer without a call. Clarification, approval, and unavailable-tool outcomes use simple observable checks (a question mark, approval wording, or inability wording); these are coarse checks, not semantic judgments. Mutating tools are never executed. All mock results are synthetic; they are not evidence about real external services. Freeze this dataset and repeat matched runs before drawing speed or cost conclusions.

The 16 mock tools cover GitHub, browser, local files, and calendar. They do not connect to those services, read user files, open websites, or change a calendar. Routing and agent-benchmark commands call model APIs when configured and can incur charges. The mock executor returns only a typed description of a hypothetical invocation. The original [implementation plan](implementation-plan.md) and [baseline diagnostics](baseline-diagnostics.md) remain as historical notes.

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/). From the repository root:

```bash
uv sync --locked --extra lab
cp -n .env.example .env
```

Edit `.env` locally. It is ignored by `.gitignore`; never put credentials in a dataset, command argument, report, or commit. `uv.lock` fixes the resolved environment; `pyproject.toml` bounds dependency versions. The tested SDK versions are `typesafe-sdk==0.6.0` and `openai==2.54.0`.

Get a TypeSafe API key from the [TypeSafe keys dashboard](https://console.typesafe.ai/keys), following the [official quickstart](https://docs.typesafe.ai/introduction/quickstart). Sign in yourself and follow any access requirements shown by TypeSafe. This project does not create accounts or provision credentials. Set:

```dotenv
TYPESAFE_API_KEY=your-key-here
```

The default Jev alias is `jev-latest`; optionally set `JEV_MODEL` to an available fixed version for reproducibility. Record the actual response versions from `usage.response_models` in reports. Available models and access may change: consult [TypeSafe models](https://docs.typesafe.ai/models).

The OpenRouter baseline is optional. Get a key from [OpenRouter API keys](https://openrouter.ai/settings/keys), then set **both** `OPENROUTER_API_KEY` and `BASELINE_MODEL` in `.env`:

```dotenv
OPENROUTER_API_KEY=your-key-here
BASELINE_MODEL=provider/model-id
```

`provider/model-id` is a placeholder: use the exact model ID from the [OpenRouter model catalog](https://openrouter.ai/models), choosing a model and endpoint that support [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs). There is no default model. The official OpenAI Python SDK calls OpenRouter's compatible `https://openrouter.ai/api/v1/chat/completions` endpoint; an OpenAI API key is not used. Provider preferences require support for the request parameters and disable provider fallbacks. Unsupported models or schemas return a routing fallback. Use the same model ID throughout comparisons. Jev-only routing does not create an OpenRouter client.

## Commands

Run these from the project root:

```bash
uv run jev-router route "Find open GitHub issues mentioning authentication"
uv run jev-router route "Read /tmp/report.txt" --execute
uv run jev-router route "Delete /tmp/temporary-report.txt" --approve
uv run jev-router route "Delete the temporary local report" --approve
uv run jev-router route "Explain what GitHub issues are" --json
```

`route` alone only routes. `--execute` attempts a mock invocation without granting approval. `--approve` explicitly approves and attempts the mock invocation. Ambiguous requests, including a deletion without a sufficiently identified target, can still return `clarify`; approval does not fill in missing information or bypass routing thresholds. A route requiring approval returns `approval_required` if executed without it. Nothing executes for `fallback`, `clarify`, or `no_tool` outcomes.

```bash
uv run jev-router compare "Check whether I am free Friday afternoon" \
  --context "Today is September 21, 2026. Timezone America/New_York; afternoon means noon to 5pm."
uv run jev-router compare "Read /tmp/report.txt" --json
```

Comparison displays domain/tool selection, routing and outcome agreement, both confidences and their sources, latency, token usage, and configured estimated cost. Routing agreement is `null` if either router falls back; two API failures are not counted as successful agreement. Compare never executes tools. Missing OpenRouter configuration produces a readable fallback and leaves Jev usable.

`--context` supplies only necessary context, identically to both providers; it does not automatically read conversation history. JSON results go to stdout and structured logs go to stderr. Expected provider failures are represented by a fallback decision with exit status 0; inspect `outcome` in automation. Invalid CLI/configuration/dataset inputs use a nonzero exit status without printing sensitive validation values.

## Agent task benchmark

The routing eval gives the routing decision to Jev or Luna in isolation. To test what happens when a Luna agent still makes its normal tool call after Jev filters the available list, run the separate paired benchmark:

```bash
uv run jev-router agent-bench --live
uv run jev-router agent-bench --live --json
```

`--live` is required because this makes paid Jev and OpenRouter calls. Both arms use the same `BASELINE_MODEL`, system instruction, tasks, and inert tool results from [`shared_cases.json`](shared_cases.json). The flat arm gives the model all 16 tool schemas. The Jev arm calls the public router before each model turn and offers the selected exact tool; a routing fallback restores all tools. Task order alternates between arms. No real GitHub, browser, file, or calendar operation occurs. Mutating mock tools are refused.

The original dataset contains 10 synthetic tasks: eight single-tool reads, one no-tool question, and one two-tool task. The new shared dataset uses the category-specific scoring described above. This remains a synthetic benchmark, not a semantic judge or proof of performance on real tasks. Reports under `experiments/results/` include per-case outcomes, latency, token counts, configured cost estimates, and `mean_success_latency_ms`; failed early exits make the ordinary mean latency misleading. Request text and model answers are omitted from reports. Repeat runs and compare matched tasks before drawing a conclusion.

The archived [September 20, 2026 run](published/agent-bench-2026-09-20.json) used `openai/gpt-5.6-luna` and the current [`agent_tasks.json`](agent_tasks.json); the dataset SHA-256 in the report matches that file. Both arms passed 10/10 tasks. Mean task latency was 2.575 s with all tools versus 3.071 s with Jev filtering. Estimated cost was $0.002979 versus $0.002786 for ten tasks, using the nonsecret price assumptions recorded in the report. This is a single synthetic run, not a demonstration of general accuracy or speed. In the two-tool case Jev fell back to all tools. Provider-native tool search was not measured. The [case study](../docs/case-study.md) explains the result and its limits; future local reports remain ignored by git until deliberately reviewed for publication.

OpenRouter documents ordinary [tool calling](https://openrouter.ai/docs/guides/features/tool-calling), but does not currently document forwarding OpenAI's provider-native `tool_search` feature. This benchmark compares full-tool exposure with Jev prefiltering through OpenRouter; it is **not** a native tool-search benchmark. Testing provider-native search requires a separately supported endpoint and credentials. [OpenAI's tool-search guide](https://developers.openai.com/api/docs/guides/tools-tool-search) describes its own API feature.

## Architecture

```text
Typed RoutingRequest
  → Jev or OpenRouter judgment adapter
  → stage 1: domain Choice + clarification/mutation/consequence judgments
  → shared policy: clarify / fallback / no_tool / continue
  → stage 2: exact tool among only that domain + none_of_the_above
  → shared policy → RoutingDecision
  → optional explicitly requested mock executor with independent approval checks
```

- `models.py` and `config.py`: validated Pydantic boundaries and settings.
- `questions.py`: shared complete instructions and options.
- `interfaces.py`: `Router` and `JudgmentProvider` protocols.
- `jev_router.py`: TypeSafe Choice/Noul construction and SDK response translation.
- `baseline_router.py`: OpenRouter JSON Schema output, Pydantic validation, and response translation.
- `routing_service.py`: provider-neutral two-stage orchestration and policy.
- `lab/tool_catalog.py`: stable mock tool names, descriptions, schemas, and inert execution.
- `evaluator.py`, `logging.py`, and `cli.py`: evaluation, private structured logging, and commands.

The hierarchy narrows each exact-tool decision to four tools and a rejection option. It trades an extra network round trip and possible domain-stage mistakes for smaller tool-choice inputs and a clearer boundary. It is an experimental choice, not a demonstrated optimization; a flat 16-tool router is a useful later ablation. Both current routers use this hierarchy and the exact same request state, domain options, tool descriptions, and binary questions.

**Jev does not generate arbitrary tool arguments in this prototype.** It chooses from predefined options and judges binary signals. `Score` was checked but is not needed for these categorical and binary decisions. After selection, a local deterministic preparer extracts only explicit simple values such as URLs, absolute paths, quoted text, and `field=value` context. Missing required inputs produce a targeted clarification. The mock executor accepts only a prepared Pydantic-validated call and still never invokes a real service. A future primary LLM could generate complex arguments after Jev narrows the tool set, followed by schema validation and independent authorization.

## Deterministic routing and approval policy

All thresholds are configurable. Current defaults:

| Environment variable | Default |
| --- | ---: |
| `JEV_DOMAIN_CONFIDENCE_THRESHOLD` | 0.65 |
| `JEV_TOOL_CONFIDENCE_THRESHOLD` | 0.70 |
| `JEV_CLARIFICATION_THRESHOLD` | 0.75 |
| `JEV_MUTATION_THRESHOLD` | 0.60 |
| `JEV_HIGH_CONSEQUENCE_THRESHOLD` | 0.50 |
| `JEV_ROUTING_TIMEOUT_MS` | 3000 |
| `BASELINE_ROUTING_TIMEOUT_MS` | 30000 |

Precedence is explicit: API error/timeout → fallback; after stage one, clarification **greater than** its threshold → clarify; domain confidence **below** its threshold → fallback; `none` → no_tool; `other` → fallback. Only a confident supported domain reaches stage two. Low tool confidence or `none_of_the_above` → fallback. Equality at a confidence threshold passes. A mutation or consequence probability **at or above** its threshold requires approval. Thresholds apply to both providers.

The asynchronous total deadline covers both stages, including client creation. Each SDK also receives an HTTP timeout. Automatic retries are disabled, avoiding hidden extra calls in latency/cost measurements. The baseline has a separate, disclosed 30-second default so the Jev budget does not censor most conventional LLM responses; set identical deadlines when testing an identical service-level target. Client cleanup is outside measured routing latency. Partial usage survives a failed second stage. The earlier shared-prompt reports used a 1,500 ms Jev deadline; the current 3,000 ms protocol is reported separately. Jev reports per-call stage, duration, and sanitized status in `usage.call_timings`. Agent summaries keep exact cost null when usage is missing and also report `known_minimum_cost_usd` and `missing_routing_usage_calls`.

Every mutating catalog tool always requires `approved=True`, independently of the model's predictions. File deletion, issue creation, form submission, and calendar creation/deletion also have an explicit immutable name-based approval rule. Browser clicks conservatively count as potentially mutating. Even if a model misses a mutation or a caller clears `requires_approval`, the executor rechecks the trusted catalog. High-risk catalog tools also require approval. The model never approves an action. A candidate tool may appear in diagnostics on a low-confidence fallback; it is not executable.

## Evaluation

`experiments/routing_cases.json` contains **86 hand-authored cases**, including closely related tools, clear routes, explanations requiring no tool, missing information, mutations, high-consequence actions, misleading tool names, unsupported domains, and unsupported actions within known domains. Cases include explicit independent `expected_mutation` and `expected_high_consequence` labels; neither is inferred from `requires_approval`. For example, a navigation click requires approval conservatively even when it does not request persistent mutation. A case can allow multiple acceptable tools.

The published [September 20, 2026 routing run](published/routing-2026-09-20.json) matches the current dataset SHA-256 and used `openai/gpt-5.6-luna` as the two-stage LLM-router baseline. Jev selected a suitable domain and tool in 64/68 tool-fit cases versus Luna's 65/68, at 508 ms versus 2,579 ms mean routing latency. Estimated total cost was $0.00365 versus $0.02920 at the configured prices. In all 55 cases labeled ready to route, both standalone routers selected an acceptable tool. Jev then returned `clarify` on 24 and `fallback` on one low-confidence case, leaving 30/55 correct ready-to-use routes; Luna returned `clarify` on 20, leaving 35/55. This supports the idea that specialized routing can be fast and inexpensive **when routing is the job being measured**. It does not show that an agent becomes faster after adding Jev before its own tool-selection step, or that the differences are statistically significant. The baseline's self-reported confidence is not calibrated against Jev's distribution-derived confidence. Both provider calls are included in routing latency.

```bash
# Current policy: high clarification stops before exact-tool selection
uv run jev-router eval
# Collect exact-tool diagnostics after clarification, as in the published report
uv run jev-router eval --routers both --diagnostic-stage-two
# Jev-only current-policy run and machine-readable diagnostic output
uv run jev-router eval --routers jev
uv run jev-router eval --routers both --diagnostic-stage-two --json
# Alternative dataset or report directory
uv run jev-router eval --dataset experiments/routing_cases.json --output-dir experiments/results
```

`--diagnostic-stage-two` still returns `clarify` when the clarification threshold is exceeded; it makes a second model call solely to record the exact-tool candidate and probabilities. This can change latency, token totals, and cost. Without the flag, low tool-fit coverage may reflect unasked stage-two questions rather than poor selection. Compare new runs under the same flag and configuration; neither mode exactly reproduces the published schema-2 prompts.

Reports use UTC timestamps under `experiments/results/`. Schema version 3 records catalog-derived domain descriptions as `catalog_derived_domains_v1` and retains the baseline output format marker `closed_probability_object_v2`, so earlier runs remain distinguishable. Reports written by the current harness include dataset SHA-256, nonsecret threshold/model/price configuration, the diagnostic-stage-two setting, actual response model versions, per-case decisions, and aggregate metrics. Requests are represented by case IDs and hashes, not their full text. Reports are ignored by git. Evaluation **never calls the mock executor**. With absent credentials, it produces fallback records, useful for checking the CLI but not for benchmarking models.

Metric definitions:

| Metric | Definition |
| --- | --- |
| Domain accuracy | Correct selected domain / all cases; missing domains are incorrect. |
| Exact-tool accuracy | Correct domain and acceptable tool **with route outcome** / cases whose expected outcome is route. Abstention counts as a miss. |
| Tool-fit accuracy | Correct domain and acceptable tool regardless of whether the request is ready to execute / cases labeled `expected_tool_fit`. This isolates tool relevance from readiness. |
| Execution-readiness accuracy | Correctly distinguishes requests ready to route from those requiring clarification / all cases. |
| Top-two tool accuracy | Expected tool in the two highest reported tool probabilities with correct domain / route cases with tool probabilities. Report includes the available-case denominator; this is conditional accuracy, not full-dataset coverage. |
| Outcome accuracy | Correct route/no_tool/clarify/fallback outcome / all cases. |
| Overall accuracy | Correct domain and outcome, plus acceptable tool when routing / all cases. |
| Clarification precision/recall | Predicted `clarify` outcomes against expected `clarify`. |
| Mutation/consequence precision/recall | Thresholded raw model judgments against independent truth labels. Missing judgments count as unknown and as false negatives for positive truth. |
| Approval-policy violations | Routed decisions lacking approval when the case or selected tool's deterministic policy requires it. Counts policy failures, not actual executions. |
| Fallback rate | All fallback outcomes / all cases, including unsupported requests. |
| Latency | Mean, median, and nearest-rank p95 of total measured routing latency, including errors. |
| Tokens | Sum of reported input/output tokens across both stages; incomplete usage is explicitly counted, and totals are then lower bounds. |
| Confidence buckets | Overall decision accuracy grouped by the minimum available stage confidence; unknown values get their own bucket. Not a probability-of-correctness calibration score. |
| Cost per correct route | Total estimated API cost for **all evaluated cases** / correctly routed expected-route cases. Undefined if none are correct or costs are incomplete/unconfigured. |

Zero-denominator metrics are `null`, not zero. Token usage comes from SDK responses, not a tokenizer estimate. A request that fails after being sent may still be billed; its unknown usage is never treated as a known free call. Model responses without complete usage also produce unknown total cost. The report retains usable counts from other calls.

`JEV_*_PRICE_PER_MILLION` and `BASELINE_*_PRICE_PER_MILLION` are optional nonnegative reporting assumptions. Both input and output prices must be configured for a provider. `.env.example` includes the requested Jev assumptions of $0.042/million input tokens and zero output cost, not a promise of current pricing. Blank prices remain unconfigured. Estimates use `tokens × configured price / 1,000,000`; they do not account for cached-input discounts, tiers, credits, taxes, or future provider billing rules. Set accurate assumptions from the providers before comparing costs.

Runs are sequential and alternate provider order by case. No hidden warmup calls are made. Client startup, connection reuse, schema processing/caching, network variability, OpenRouter provider selection, differing timeouts, and early exits can affect results. Both stages are included in the latency and cost totals. Repeat runs with pinned models and compare matched cases. Inspect fallback rates and latency by outcome before concluding one router is faster. Use held-out cases to choose thresholds and a larger independently labeled dataset to test non-inferiority; 86 cases and one run do not establish general accuracy parity. This harness does not calculate statistical significance.

## Confidence and typed output

TypeSafe `Choice` returns the winning choice, all probabilities, and a distribution-derived confidence. **Confidence is not the same as the winning probability, nor proof of correctness.** `Noul` is the probability of yes and has no separate confidence. `Score` uses ordered rubric levels and returns a probability-weighted score, level probabilities, and confidence. Question IDs are not provided to the underlying model, so every instruction stands alone.

OpenRouter requests strict JSON Schema output from compatible endpoints; enforcement varies by provider, so local Pydantic validation remains mandatory; the adapter still handles refusals, incomplete responses, and invalid judgments. The baseline's returned probabilities and confidence are **self-reported estimates**, not native class probabilities, token logprobs, or calibrated Jev equivalents. Their numerical thresholds are shared for experimental consistency, not because the scales have demonstrated equivalence. Both adapters reject missing/unoffered/duplicate labels, nonfinite or out-of-range numbers, invalid probability sums, and a selected label that is not maximal. A 0.02 sum tolerance allows provider rounding; probabilities are not silently normalized.

The baseline wire schema requires a fixed probability object with one required numeric property for every offered option, forbids additional properties, and constrains the selected label to those options. This avoids the earlier free-form probability list, which permitted omissions and duplicate labels despite the prompt asking for all options. The adapter still validates sums, ranges, option coverage, maximal selection, and duplicate JSON keys locally. Invalid outputs are rejected, not repaired or silently normalized.

Errors include a `failure_stage` (`domain` or `tool`) and a safe `fallback_reason`: `invalid_json`, `invalid_output_schema`, `missing_probability_labels`, `unknown_probability_labels`, `invalid_probability_sum`, `selected_label_missing`, `selected_label_not_maximum`, `duplicate_json_keys`, `provider_refusal`, `incomplete_response`, or `empty_response`. OpenRouter transport failures distinguish authentication, permission, rate limits, bad requests, missing endpoints, server errors, connections, and timeouts. Raw provider messages, response text, and validation input are never included in these diagnostics. Usage is recorded before validating a received completion, including rejected completions.

Typed, schema-valid output can still select the wrong domain or tool, miss ambiguity, misread a request, or confidently misjudge risk. Only evaluation can measure that behavior. Deterministic rules protect known tool categories; they cannot prove that a read-only result is safe or that the user's intent was understood.

## Logging and security limitations

Structured JSON logs include request ID/hash, router/model, distributions and confidence, signals, outcome and fallback reason, latency, token usage, approval requirement, and whether mock execution was attempted. By default neither requests nor recent context nor environment values/API keys are logged. SDK/HTTP logging is suppressed by the CLI because debug body logging can expose user content. Exception messages are not emitted.

- `LOG_REQUEST_PREVIEW_CHARS=0` defaults to no preview. A positive value includes a truncated preview, potentially sensitive; use only with nonsensitive development data. Even short previews omit the final character.
- `LOG_FULL_REQUESTS=false` is the default. Set true **only in development with nonsensitive data**. Recent context remains omitted.
- Programmatic callers should call `configure_logging()` before model calls and keep their own SDK/HTTP debug handlers disabled.

This is not an authorization system, an injection defense, a sandbox, or an autonomous agent. Requests and context are untrusted model inputs. Passing `approved=True` is an explicit caller assertion, not an authenticated human identity or durable approval record. The catalog is trusted application code, not model-controlled data. It does not cover all sensitive reads or every consequence. Logs with hashes can still reveal repeated requests or be vulnerable to dictionary matching. OpenRouter forwards requests to an upstream model provider; review both OpenRouter and that provider's retention policies. Do not send secrets to either model. No real accounts are connected by this project, but you must obtain model API credentials yourself to run paid routing.

## Tests and checks

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv build
```

Default tests mock all external API calls, block outbound socket connections, remove provider keys from the test environment, and deselect `live` tests. Tests cover provider questions/response translation, routing gates, approval enforcement, timeout/error/missing-key behavior, catalog integrity, evaluation metrics, CLI behavior, and log privacy.

Live tests require **both** explicit selection and an enable variable, plus the corresponding configured credentials (and `BASELINE_MODEL` for OpenRouter):

```bash
RUN_LIVE_TESTS=1 uv run pytest -m live
# Only Jev's live contract check
RUN_LIVE_TESTS=1 uv run pytest -m live -k jev
```

They send a harmless routing request and never execute tools. They can incur API charges. A timeout or invalid provider response fails the live contract check; semantic accuracy is measured through evaluation instead. Live tests were not run during project creation.

## Extending the catalog and connecting MCP later

To add a benchmark tool, add a stable `ToolDefinition` to `src/jev_router/lab/tool_catalog.py`, choose conservative read-only/risk metadata, and add evaluation cases and approval tests. The current mock input/output schemas are deliberately shared placeholder schemas; actual tool-specific argument schemas belong in a future validated integration. Each domain's stage-two options are derived from its catalog entries.

To add a domain, extend `Domain` and `ToolDomain` in `models.py`, add a description to `DOMAIN_OPTIONS`, and add its tools and evaluation cases. Add deterministic authorization requirements before any execution capability. Both adapters automatically consume the shared question definitions.

The smallest next MCP step is a **local fake MCP server exposing one read-only tool**. Map its discovered metadata into this catalog and check selection and schema compatibility while retaining mock execution. Then introduce an `Executor` interface backed by an MCP client, with an allowlist, validated arguments, target-specific authorization, timeouts, audit records, and authenticated approvals outside the router. Never give the model the power to edit safety metadata or approve calls. Keep actual mutating MCP calls disabled until that boundary has been separately designed and tested.

## Official documentation checked

Checked September 19, 2026:

- [TypeSafe introduction](https://docs.typesafe.ai/introduction), [System One HTTP API](https://docs.typesafe.ai/api), [Python SDK](https://docs.typesafe.ai/sdk/python), [async client](https://docs.typesafe.ai/sdk/python/api/clients/async), [answers and usage](https://docs.typesafe.ai/sdk/python/api/types/responses), [retry policy](https://docs.typesafe.ai/sdk/python/api/retries).
- [Choice](https://docs.typesafe.ai/primitives/choice), [Noul](https://docs.typesafe.ai/primitives/noul), [Score](https://docs.typesafe.ai/primitives/score), [confidence](https://docs.typesafe.ai/confidence), [API-key quickstart](https://docs.typesafe.ai/introduction/quickstart).
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), reviewed for the original direct-OpenAI adapter. The current baseline uses OpenRouter Chat Completions instead.
- [OpenRouter quickstart](https://openrouter.ai/docs/quickstart), [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), and [usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting). Baseline usage maps `prompt_tokens`/`completion_tokens` to internal input/output counts before validating completion content.

Details beyond the prompt's sketch: the TypeSafe endpoint is `/v1/systemone`; the async SDK supports cancellation-friendly calls and `RetryPolicy(max_retries=0)`. The installed SDK uses msgspec response objects (not Pydantic) and allows token counts to be `None`. This project validates them at its own typed boundary and tracks incomplete accounting. Jev confidence is derived from the distribution rather than the winning probability. The SDK documentation warns that request/response bodies are not redacted by its debug logger, so the CLI suppresses those logs. No `Score` API call is needed for this design.
