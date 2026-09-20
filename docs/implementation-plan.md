# Jev tool router implementation plan

Goal: a local, mock-only experiment comparing hierarchical routing, accuracy, latency, and assumed API costs.

Design: typed provider-neutral stage judgments feed one deterministic policy. Jev and OpenRouter see identical state, questions, and domain-specific tool options. The executor checks trusted catalog metadata independently. No tool integrates with a real service.

1. Define configuration, typed boundaries, the 16-tool catalog, and safe placeholder execution. Test catalog integrity and approval enforcement.
2. Define shared question specifications and asynchronous stage-provider/router protocols. Implement Jev Choice/Noul translation and OpenRouter Chat Completions JSON Schema outputs. Test actual SDK response parsing with mocked calls, timeouts, malformed distributions, and partial usage.
3. Implement shared hierarchical policy: clarification takes precedence, then domain confidence, none/other, then exact-tool confidence. A total configurable deadline covers both calls. Disable retries. Preserve diagnostics but execute only route outcomes.
4. Add CLI commands and structured logging with hashes by default; opt-in previews/full request logging. Test JSON output, missing config, errors, and privacy.
5. Author >=60 cases with separate mutation/high-consequence labels. Evaluate both routers without execution, track denominators and missing usage explicitly, report per-case outcomes and reproducible configuration without secrets.
6. Document sources, limitations, setup, live-test gating, metric semantics, and future MCP boundary. Run formatter, linter, strict type checker, offline tests, and packaging smoke tests.

Thresholds follow the requested defaults. Confidence is not correctness. Baseline probabilities are self-reported and not calibrated Jev probabilities. Score is documented but unnecessary for this experiment's categorical and binary judgments.
