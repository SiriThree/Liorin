# Evaluators

Evaluation helpers for the TechHub customer support agent.

- `correctness_evaluator`: LLM-as-judge comparison against reference answers.
- `count_total_tool_calls_evaluator`: Trace-based count of tool calls.

The CI runner uses these evaluators in `evals/run_ci_eval.py`.
