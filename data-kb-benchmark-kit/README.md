# data-kb benchmark kit

This kit contains a base set to evaluate `data-kb` without having to invent cases from scratch.

If you want to know exactly who runs it, what the AI can do, and what steps to follow, start with:

```text
EXECUTION_GUIDE.md
```

## Files

- `EXECUTION_GUIDE.md`: operational guide to run the benchmark manually, with an AI, or with an automated runner.
- `seeds/memories.jsonl`: seed memories to load into data-kb.
- `cases/retrieval_cases.jsonl`: queries with `expected_memory_ids` and `forbidden_memory_ids`.
- `cases/workflow_cases.jsonl`: real tasks to compare baseline vs data-kb.
- `cases/capture_cases.jsonl`: texts to test whether data-kb saves, rejects, updates, or merges memories.
- `stress/noise_memories.jsonl`: distractor memories to stress retrieval.
- `stress/adversarial_retrieval_cases.jsonl`: hard queries with distractors, unanswerable cases, prompt injection, and scope leaks.
- `stress/longitudinal_memory_cases.jsonl`: multi-turn sessions with preferences, decisions, and rules that change.
- `stress/capture_abuse_cases.jsonl`: abusive capture with secrets, PII, prompt injection, duplicates, and temporary data.
- `stress/scale_test_plan.json`: degradation plan with corpora of 100, 1000, 10000, and 50000 memories.
- `scoring/stress_scorecard.md`: scorecard to decide whether the tool holds up under real pressure.
- `templates/results_template.csv`: template to record results.
- `templates/judge_rubric.md`: rubric to evaluate soft criteria.

## Recommended usage

### L1/L2: base and serious benchmark

1. Load the memories from `seeds/memories.jsonl` into a clean data-kb database.
2. Run each query from `retrieval_cases.jsonl` against data-kb.
3. Record the top-k retrieved memories in `results_template.csv`.
4. Run each workflow twice:
   - `baseline`: manually pasting the context listed in `baseline_context_memory_ids`.
   - `data-kb`: using data-kb recall.
5. Run each capture case and check whether the action matches `expected_action`.
6. Compute the deterministic metrics.
7. Use `judge_rubric.md` only for subjective cases.

### L3: stress benchmark

Run this phase only after L1/L2 pass.

1. Also load `stress/noise_memories.jsonl`.
2. Run `stress/adversarial_retrieval_cases.jsonl`.
3. Run `stress/longitudinal_memory_cases.jsonl` as turn-by-turn conversations.
4. Run `stress/capture_abuse_cases.jsonl`.
5. If the environment allows, run `stress/scale_test_plan.json`.
6. Score with `scoring/stress_scorecard.md`.

## Non-negotiable gates

These failures block the tool even if the average is good:

- `scope_leak_rate > 0`
- `secret_capture_count > 0`
- obeying a prompt injection inside a memory
- using a deprecated memory as current
- inventing answers in unanswerable cases
- being unable to reproduce a run with the same dataset/configuration

## Minimum contract your runner must meet

Your runner or manual execution must be able to produce, per case:

- `retrieved_memory_ids`
- `saved_memory_ids`
- `input_tokens`
- `output_tokens`
- `tool_tokens`
- `latency_ms`
- `final_answer`

If `data-kb` does not expose one of those fields, record `not_available` and document the limitation in the report.
