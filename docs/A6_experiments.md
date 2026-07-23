# A6 · Experiments

Five studies on agent reliability. Run with
[`experiments/run_experiments.py`](../experiments/run_experiments.py); results save to
`experiments/results.json`.

```bash
python -m experiments.run_experiments                 # all five
python -m experiments.run_experiments --only 1 5      # selected
python -m experiments.run_experiments --provider openai --model gpt-4o-mini
```

## Experiment 1 — Tool description quality
**Question:** do detailed tool descriptions improve tool selection vs terse ones?
**Method:** run the 8 single-tool requests with (a) the full detailed descriptions and (b) terse
name-only descriptions; measure tool-selection accuracy for each.
**Metric:** selection accuracy (detailed vs short).
**Hypothesis:** detailed descriptions select the correct tool more often — vague descriptions cause
misrouting (the reason tool descriptions in this project are deliberately verbose).

## Experiment 2 — Structured vs unstructured output
**Question:** does Pydantic structured output reduce parsing failures vs free-text JSON?
**Method:** extract meeting actions from 3 note samples via `structured()` (function-calling +
schema) vs asking for free-text JSON and parsing it; count parse/validation failures.
**Metric:** parse-failure count per approach.
**Hypothesis:** structured output fails less; free-text JSON occasionally emits prose/fences that
break parsing.

## Experiment 3 — Temperature
**Question:** how does sampling temperature affect tool selection?
**Method:** run the single-tool requests at temperature 0.0 / 0.5 / 1.0.
**Metric:** selection accuracy per temperature.
**Hypothesis:** temperature 0 gives the most consistent, accurate selection; higher temperature adds
variance and occasional wrong-tool or hallucinated calls.

## Experiment 4 — Approval prompt design
**Question:** is the write-pause robust to prompt wording?
**Method:** run the approval cases and check each pauses before the write.
**Metric:** approval-compliance %.
**Key point:** approval is enforced **structurally** in the graph (the `requires_approval` flag on
each tool routes to the interrupt), *not* by prompt text — so compliance should be **100% regardless
of prompt wording**. This experiment demonstrates that a structural gate is more dependable than a
prompt instruction the model could ignore.

## Experiment 5 — Max agent steps
**Question:** how does the step limit affect completion, looping, and latency?
**Method:** run a 3-part request (`list → plan → flag overdue`) with `max_steps` = 2 / 4 / 8.
**Metric:** steps taken, final outcome, tools used, latency.
**Hypothesis:** too-low a limit (2) truncates multi-step work (`max_steps_exceeded`); 8 completes
with headroom. Confirms why the limit is set to 8.

## Optional Experiment 6 — Model comparison
Re-run the A5 eval on a free OpenRouter model vs OpenAI `gpt-4o-mini` and compare tool-selection
accuracy, argument accuracy, and latency. (Run `eval.run_eval` twice with different `--provider`.)
