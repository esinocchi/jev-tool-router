# Contributing

Start with the [case study](docs/case-study.md) and [experiment guide](experiments/README.md)
if you are investigating the benchmark claims. The two published experiments answer different
questions: the 86-case run measures standalone routing; the ten-task run measures a Luna
agent after Jev filters its tools. New runs default to one shared 100-prompt dataset, while
still measuring routing and agent behavior separately. Please keep those distinctions in issues
and pull requests.

Useful research contributions include independently labeled, realistic requests; cases
where similar tools compete; a larger catalog; multi-tool tasks; and runs against
supported provider-native tool search. Explain the expected domain, acceptable tools,
outcome, and ambiguity for each new case. Do not tune thresholds on a dataset and then
present accuracy on that same dataset as held-out evidence. The dated reports under
`experiments/published/` are historical artifacts. Put new reports under the ignored
`experiments/results/` directory, and include a dataset hash, model/version, settings
(including `diagnostic_stage_two` for routing runs),
price assumptions, and repeated-run context when proposing a result for publication.

Keep the router provider-neutral and execution-free. Changes to routing behavior need
hand-authored evaluation cases and tests that cover both the model judgment boundary and
deterministic policy boundary. Never let model probabilities override approval rules.

The public SDK lives in `src/jev_router/`; baseline routing, mocks, metrics, and the
CLI live in `src/jev_router/lab/`. The hand-authored dataset and detailed benchmark
instructions live in `experiments/`. A contribution to policy should add a focused
unit test. A change to measured behavior should also update the relevant cases or
metric definition and explain the expected effect in the pull request.

Before opening a pull request, run:

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
uv build
```

Do not commit API keys, evaluation reports containing user data, or real integration
credentials. Default tests must mock providers and never make network requests. Live
tests remain opt-in with `RUN_LIVE_TESTS=1`; they can incur API charges. Describe any
live calls and any change to the case-study claims in your pull request.
