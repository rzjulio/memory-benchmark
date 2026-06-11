# data-kb benchmark execution guide

This guide explains how to run the benchmark, what the AI can do, what you must configure, and what steps to follow to get reliable conclusions.

> **An automated runner now exists at the repo root** (`runner.py` +
> `scorer.py` + `reporter.py` + `benchmark_config.toml`). It implements
> every phase in this guide, writes all the result files listed below, and
> ships a mock adapter so you can validate the pipeline with
> `python runner.py --demo` before wiring real commands.
> See `../INTEGRATION.md` for exactly what to configure.

## Short answer

The benchmark does not run on its own just by having the JSONL files.

There are three ways to run it:

| Mode | Who runs it | When to use it |
|---|---|---|
| Supervised manual | You run the commands and fill in the results | If you don't have a runner yet or want to validate the process once. |
| AI-assisted | The AI runs the commands, captures results, and generates the report | If the AI has access to the repo, the `data-kb` command, and the test database. |
| Automated runner | A script runs everything and generates metrics/report | Ideal for regression, CI, and repeatable comparisons. |

The best final option is **automated runner + selective human review**.

## What the AI can run

The AI can run the benchmark if it has access to:

- the source code or binary of `data-kb`;
- a clean SQLite or PostgreSQL test database;
- real commands for reset, import, recall, capture/export;
- logs or JSON output with the IDs of retrieved/saved memories;
- the model's token usage, or at least an estimating tokenizer;
- permission to create result files under `runs/`.

The AI can do the following well:

- load seed memories;
- run queries;
- capture the top-k of retrieval;
- compute precision@k, recall@k, MRR, leaks, and forbidden hits;
- run baseline vs `data-kb` workflows;
- generate `metrics.json` and `report.md`;
- flag cases that require human review.

The AI must not decide the whole benchmark on its own. It must leave evidence and flag for review:

- cases with secrets or PII;
- scope leaks;
- invented answers in cases without evidence;
- low or doubtful scores;
- cases where `data-kb` saves tokens but lowers quality;
- threshold changes.

## What is left to connect

The kit already brings data and criteria, but it does not know the exact commands of your `data-kb` installation.

You must map these operations:

| Operation | Real command to connect |
|---|---|
| Reset DB | Command to create a clean run. |
| Import memory | Command to save a memory from JSON. |
| Recall/query | Command to query memory and return top-k IDs. |
| Capture/analyze | Command to test whether an input is saved, rejected, updated, or merged. |
| Export/list | Command to list stored memories and metadata. |
| Metrics/logs | Way to obtain tokens, latency, and errors. |

Conceptual example:

```bash
# Not a guaranteed command. Adjust it to data-kb's real CLI.
data-kb memory persist --json '<memory-json>'
data-kb tool --json '<query-json>'
data-kb memory list --json
```

## Preparation

1. Install or activate `data-kb`.
2. Choose a backend:
   - SQLite for the first local run.
   - PostgreSQL to validate robust behavior.
3. Create an isolated database for the benchmark.
4. Define a `RUN_ID`, for example:

```text
2026-06-11-run-001
```

5. Create the output folder:

```text
runs/2026-06-11-run-001/
```

6. Copy or reference these files:

```text
seeds/memories.jsonl
cases/retrieval_cases.jsonl
cases/workflow_cases.jsonl
cases/capture_cases.jsonl
stress/noise_memories.jsonl
stress/adversarial_retrieval_cases.jsonl
stress/longitudinal_memory_cases.jsonl
stress/capture_abuse_cases.jsonl
stress/scale_test_plan.json
```

## Phase 0: Smoke test

Before running everything, validate that `data-kb` responds.

1. Reset the database.
2. Import a test memory.
3. Query something that should retrieve it.
4. Verify that the output includes:
   - the memory ID;
   - the score or ranking if it exists;
   - the scope;
   - the namespace;
   - the latency or timestamp.

If this fails, do not run the full benchmark.

## Phase 1: Load the base memories

Load:

```text
seeds/memories.jsonl
```

Expected result:

- 30 memories loaded or processed.
- IDs preserved or mapped.
- Scope and namespace respected.
- Memories with `status=do_not_persist` must be rejected or marked as non-retrievable, according to `data-kb`'s policy.

Save evidence in:

```text
runs/<RUN_ID>/seed_import.jsonl
```

## Phase 2: Base retrieval

Run each line of:

```text
cases/retrieval_cases.jsonl
```

For each case:

1. Send `query`, `scope`, and `namespace` to `data-kb`.
2. Capture the top 10 retrieved memories.
3. Compare against `expected_memory_ids`.
4. Verify that no `forbidden_memory_ids` appear.

Compute:

```text
precision@5
recall@5
MRR
forbidden_hit_rate
scope_leak_rate
```

Save:

```text
runs/<RUN_ID>/retrieval_results.jsonl
```

## Phase 3: Baseline vs data-kb workflows

Run:

```text
cases/workflow_cases.jsonl
```

Each workflow is run twice.

### Baseline mode

Build a prompt with:

1. `prompt`
2. the content of the memories listed in `baseline_context_memory_ids`

This mode represents "doing it manually by pasting the correct context."

Record:

- input tokens;
- output tokens;
- final answer;
- latency;
- quality score.

### data-kb mode

Do not paste memories manually.

1. Send the `prompt` to `data-kb`/recall.
2. Use only the memories retrieved by the tool.
3. Generate the final answer.
4. Record total tokens including tool overhead.

Compare:

```text
token_savings_pct
quality_delta
errors_caused_by_memory
```

Save:

```text
runs/<RUN_ID>/workflow_results.jsonl
```

## Phase 4: Memory capture

Run:

```text
cases/capture_cases.jsonl
```

For each case:

1. Send `input` to `data-kb`'s analyze/capture function.
2. Capture the action taken:
   - `save`
   - `reject`
   - `update`
   - `merge`
   - `supersede`
3. Compare against `expected_action`.
4. Export new memories and check for sensitive content.

Compute:

```text
capture_accuracy
secret_capture_count
duplicate_rate
bad_memory_rate
```

Save:

```text
runs/<RUN_ID>/capture_results.jsonl
```

## Phase 5: Adversarial stress

Run this phase only if L1/L2 pass.

1. Load:

```text
stress/noise_memories.jsonl
```

2. Run:

```text
stress/adversarial_retrieval_cases.jsonl
```

These cases test:

- semantic distractors;
- unanswerable questions;
- scope leaks;
- obsolete memories;
- prompt injection inside memories;
- conditional tradeoffs;
- answers that must not be invented.

Save:

```text
runs/<RUN_ID>/adversarial_results.jsonl
```

## Phase 6: Longitudinal memory

Run:

```text
stress/longitudinal_memory_cases.jsonl
```

Important: these cases are not isolated queries. They must be run as turn-by-turn conversations.

For each case:

1. Reset or create an isolated session.
2. Run each `turn` in order.
3. Allow `data-kb` to capture/update memory.
4. On the last turn, check whether it uses the correct current memory.

Compute:

```text
longitudinal_update_success_rate
stale_authority_error_rate
duplicate_rate
temporary_memory_error_rate
```

Save:

```text
runs/<RUN_ID>/longitudinal_results.jsonl
```

## Phase 7: Capture abuse/security

Run:

```text
stress/capture_abuse_cases.jsonl
```

These cases are blocking. If `data-kb` stores secrets, sensitive PII, or malicious instructions as trusted memory, the tool must not pass.

Compute:

```text
secret_capture_count
pii_capture_count
prompt_injection_saved_as_trusted_count
mixed_input_handling_success_rate
```

Save:

```text
runs/<RUN_ID>/capture_abuse_results.jsonl
```

## Phase 8: Scale and degradation

Use:

```text
stress/scale_test_plan.json
```

Run with corpora of:

- 100 memories;
- 1,000 memories;
- 10,000 memories;
- 50,000 memories if the environment allows.

Measure:

```text
latency_p50_ms
latency_p95_ms
precision@5
recall@5
MRR
retrieved_context_tokens
forbidden_hit_rate
```

Save:

```text
runs/<RUN_ID>/scale_results.jsonl
```

## Phase 9: Scoring

Generate:

```text
runs/<RUN_ID>/metrics.json
runs/<RUN_ID>/report.md
```

Use:

```text
scoring/stress_scorecard.md
```

Non-negotiable gates:

- `scope_leak_rate > 0`
- `secret_capture_count > 0`
- obeying a prompt injection inside a memory;
- using a deprecated memory as current;
- inventing an answer in cases without evidence;
- being unable to reproduce the run.

If any of those appear, the result is **fail**, even if the average score is high.

## What a human reviews

Do not review everything manually. Review:

- 100% of cases with leaks, secrets, or PII;
- 100% of cases with a low score;
- 100% of cases where `data-kb` saved tokens but lowered quality;
- 20% random sample of approved cases;
- any case flagged as `needs_human_review=true`.

## Expected final result

When finished, you should have:

```text
runs/<RUN_ID>/
  seed_import.jsonl
  retrieval_results.jsonl
  workflow_results.jsonl
  capture_results.jsonl
  adversarial_results.jsonl
  longitudinal_results.jsonl
  capture_abuse_results.jsonl
  scale_results.jsonl
  metrics.json
  report.md
```

## How to know whether an AI can already run it

The AI can run this benchmark end to end once you can give it:

1. the path to the repo or `data-kb` installation;
2. the command to reset the database;
3. the command to import memory;
4. the command to recall/query;
5. the command to analyze/capture;
6. the command to export/list memories;
7. a way to obtain tokens or usage logs.

If those commands are missing, the AI can prepare data and documents, but it cannot measure the real tool.

## Natural next step

This deliverable now exists at the repo root:

```text
benchmark_config.toml   # configuration (TOML: stdlib-parseable, supports comments)
runner.py               # orchestrates all phases
scorer.py               # deterministic metrics and gates
reporter.py             # metrics.json + report.md + results.csv
adapters.py             # CommandAdapter (real data-kb) + MockAdapter (demo)
tools/generate_scale_corpus.py  # corpora for the scale phase
```

The runner contains no benchmark-specific logic hardcoded: it reads the
JSONL, executes the `data-kb` commands configured in
`benchmark_config.toml`, computes the metrics, and generates the report.
Wiring instructions: `../INTEGRATION.md`.
