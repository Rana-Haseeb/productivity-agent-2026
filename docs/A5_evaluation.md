# A5 · Agent Evaluation Dataset & Metrics

## Purpose
Measure whether the agent is **dependable** — does it select the right tool, with the right
arguments, pause for approval on writes, complete requests, and recover from failures.

## Dataset ([eval/dataset.py](../eval/dataset.py)) — 32 cases

| Category | Count | Minimum | What it tests |
|---|:--:|:--:|---|
| Direct response (no tool) | 6 | ≥5 | Decision logic — answer directly, don't call tools |
| Single-tool | 8 | ≥8 | Correct tool + arguments for one action |
| Multi-tool | 8 | ≥8 | Chaining 2+ tools for one request |
| Approval (writes) | 6 | ≥5 | Pausing for approval before every write |
| Failure / edge | 4 | ≥4 | Ambiguous, unknown-id, unsupported, nonsense |
| **Total** | **32** | ≥30 | |

Each case records: `id`, `category`, `request`, `expected_tools`, `expected_args` (subset checked on
the primary tool), `approval_required`, and `notes`. The runner also records the **actual** tools,
arguments, approval behaviour, outcome, and duration.

## Metrics ([eval/metrics.py](../eval/metrics.py)) & targets

| Metric | Definition | Target |
|---|---|---|
| Tool-selection accuracy | correct tool(s) selected (direct = no tool) | ≥ 85% |
| Argument accuracy | expected args present on the chosen tool | ≥ 80% |
| Task-completion rate | ran without error and did the expected thing | ≥ 80% |
| **Approval compliance** | writes that correctly paused for approval | **100%** |
| Invalid-action rate | unexpected write, or a tool on a direct question | < 10% |
| Avg response time | mean run duration | measure |
| Recovery rate | failure/edge cases handled gracefully (no crash) | measure |

Approval cases are **auto-rejected** after the pause, so the eval never mutates the database while
still measuring that the pause happened and the correct tool was chosen.

## How to run
```bash
# Full run (32 cases). Budget quota — free tier is 50 req/day.
python -m eval.run_eval

# Graded run (recommended — consistent + fast):
python -m eval.run_eval --provider openai --model gpt-4o-mini

# Quick smoke:
python -m eval.run_eval --limit 6
```
Outputs (saved incrementally): `eval/results.json` (per-case), `eval/metrics.json` (aggregate),
`eval/A5_results.md` (the results table).

## Results
Run the command above to populate `eval/A5_results.md`. A 2-case pipeline smoke has been executed
(both direct cases → 0 tools, tool-selection 100%); the full graded run should be executed on a fresh
quota or on OpenAI `gpt-4o-mini`.
