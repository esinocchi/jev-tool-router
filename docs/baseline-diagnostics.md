# OpenRouter baseline output investigation

The original 81-case run reported 40 baseline `api_or_invalid_response` fallbacks. That category did not distinguish provider failures from validation failures, so it could not support a clean semantic model comparison.

## Reproduction

Five previously failed cases were sampled again using the unchanged list schema: case_001, case_007, case_010, case_031, and case_059. The first three passed on this later call. Case_031 returned only five of the six domain probability labels; case_059 returned only two. Both returned complete API responses with probabilities summing to one. Local option-coverage validation correctly rejected them.

This confirms an output-contract weakness for at least some failures; it does not establish the cause of every earlier fallback. The old schema allowed an arbitrary-length array of label/probability pairs, while complete coverage existed only in the text instruction.

## Change

The baseline now requests a fixed object with every offered probability label required and additional properties forbidden. Its selected label is restricted to the offered options by an enum. Stage two still sees only the chosen domain's tools. Internal probability, sum, and selected-maximum checks remain; no missing values are invented and no distributions are normalized. Duplicate JSON keys are rejected before Pydantic validation.

Safe diagnostic categories distinguish malformed JSON, invalid output shape, missing/unknown labels, invalid probability sums, nonmaximal selections, refusals, incomplete/empty completions, and API error categories. `failure_stage` identifies the domain or tool stage. Error messages, raw responses, user inputs, and credentials are not included. Report schema version 2 marks the new baseline output schema for reproducibility.

The dataset, prompts, routing thresholds, timeouts, price assumptions, and deterministic approval policy were not changed. All evaluation calls remain routing-only; neither mock nor real tools are executed.

## Verification

97 offline tests pass, including 19 diagnostic/schema cases, real-SDK mocked-transport tests, existing safety checks, and token accounting. Ruff formatting/lint, strict mypy, and wheel/source packaging pass. An independent review found no actionable issues.

## Full verification rerun

Report: `routing-20260920T023209.455605Z.json`. Original report and dataset preserved. Reported settings and dataset hash match the original run.

- jev: 47/54 correct tool routes; overall accuracy 88.9%; mean latency 369.8 ms; estimated cost $0.00314958; errors {}.
- baseline: 48/54 correct tool routes; overall accuracy 66.7%; mean latency 2098.8 ms; estimated cost $0.01088640; errors {'invalid_probability_sum': 5, 'selected_label_not_maximum': 2}.

This is one paired rerun, not statistical proof. Remaining probability validation failures are model outputs rejected under the unchanged contract; they are not silently repaired. No GPT-5.6 Luna evaluation was launched; the user will test that model separately.
