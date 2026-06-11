# Benchmark to evaluate data-kb

This document defines a test plan to decide whether `data-kb` actually adds value: whether it saves tokens, stores useful memory, retrieves correct information, and improves the quality of work compared to not using memory.

## Objective

Validate `data-kb` as a memory base for Copilot/LLM workflows by measuring five dimensions:

1. **Net token savings**: whether it reduces repeated context more than it costs to query/inject memory.
2. **Quality of stored memory**: whether it stores durable, actionable, correct, and well-scoped information.
3. **Retrieval quality**: whether it brings the correct memories for the correct task.
4. **Impact on the final answer**: whether it improves accuracy, continuity, and work speed.
5. **Operational reliability**: whether it respects scopes and handles duplicates, contradictions, obsolescence, and SQLite/PostgreSQL backends.

## Principles used

Modern benchmarks for RAG and memory systems usually split the evaluation into two layers:

- **Retriever**: measures whether the system retrieves the correct context. Common metrics: context precision, context recall, contextual relevance, precision@k, recall@k, and MRR.
- **Generator / final workflow**: measures whether the output uses the retrieved context well. Common metrics: answer relevance, faithfulness, correctness, and hallucination rate.

For agent memory, it is also worth testing specific capabilities: remembering facts, reasoning with distributed memories, updating old information, forgetting or ignoring obsolete information, and avoiding contamination between users/projects/scopes.

## Expected outcome

By the end of the benchmark you should be able to answer:

- How many tokens `data-kb` saves per repeated task.
- What percentage of stored memories are actually useful.
- What percentage of queries retrieve the correct memories.
- Whether answers with `data-kb` are better than without `data-kb`.
- Whether there are risks of noise, duplicates, obsolete data, scope leakage, or low-quality memory.

## Quick mode with the generated kit

To avoid having to design everything manually, a base set is ready in:

```text
data-kb-benchmark-kit/
```

The concrete execution guide is in:

```text
data-kb-benchmark-kit/EXECUTION_GUIDE.md
```

That guide explains whether you run it, whether the AI runs it, what commands are needed, and what results each phase must produce.

Contents:

| File | Use |
|---|---|
| `EXECUTION_GUIDE.md` | Step-by-step guide to run the benchmark manually, with AI, or with a runner. |
| `seeds/memories.jsonl` | Seed memories you must load into a clean `data-kb` database. |
| `cases/retrieval_cases.jsonl` | Queries with expected memories and forbidden memories. |
| `cases/workflow_cases.jsonl` | Real tasks to compare baseline vs `data-kb`. |
| `cases/capture_cases.jsonl` | Cases to test whether `data-kb` saves, rejects, updates, or merges memory. |
| `templates/results_template.csv` | Results template per run. |
| `templates/judge_rubric.md` | Rubric to evaluate soft criteria without improvising. |

The idea is to run the same set in two modes:

1. **Baseline without `data-kb`**: the necessary context is pasted manually from the memories listed in each workflow.
2. **`data-kb` mode**: the agent only queries `data-kb` and uses the retrieved memories.

Then you compare:

- tokens used;
- answer quality;
- retrieved memories;
- stored memories;
- latency;
- errors by scope, secrets, duplicates, or obsolescence.

### The only thing you must adapt

Since this workspace does not include the real `data-kb` code, the kit cannot know the exact command to import, query, and export memories. What you need to connect are these four operations:

| Operation | Input | Expected output |
|---|---|---|
| Reset | backend/scope/namespace | Clean database for a reproducible run. |
| Seed/import | one line of `seeds/memories.jsonl` | Stored memory with `memory_id`, `scope`, `namespace`, `content`, `tags`, `status`. |
| Recall/query | one line of `retrieval_cases.jsonl` | Ordered list of `retrieved_memory_ids`, ideally top 10. |
| Capture/analyze | one line of `capture_cases.jsonl` | Action taken: `save`, `reject`, `update`, `merge`, and `saved_memory_ids`. |

If `data-kb` already has commands like `tool`, `memory persist`, `digest`, `serve`, or equivalents, the runner only needs to wrap them. You don't need to change the benchmark; just map those operations.

### Result contract per case

Each execution must produce a row with this format:

```csv
run_id,case_id,mode,storage_backend,scope,namespace,input_tokens,output_tokens,tool_tokens,latency_ms,retrieved_memory_ids,expected_memory_ids,forbidden_memory_ids,saved_memory_ids,final_answer,judge_score,judge_notes
```

The template is in:

```text
data-kb-benchmark-kit/templates/results_template.csv
```

If any metric is not available, use `not_available`, but do not invent it.

### Recommended execution procedure

1. Create a clean database for the benchmark.
2. Load `data-kb-benchmark-kit/seeds/memories.jsonl`.
3. Run all cases in `cases/retrieval_cases.jsonl`.
4. For each query, save the top 10 retrieved memories.
5. Compute `precision@5`, `recall@5`, `MRR`, forbidden hits, and scope leaks.
6. Run each case in `cases/workflow_cases.jsonl` in baseline mode.
7. Run the same workflows in `data-kb` mode.
8. Measure tokens, latency, and answer quality.
9. Run `cases/capture_cases.jsonl` to validate memory capture.
10. Use `templates/judge_rubric.md` only to evaluate memory quality and the final answer.
11. Generate `runs/YYYY-MM-DD-run-NNN/report.md`.

### How to run the baseline without wasting time

In `workflow_cases.jsonl`, each case brings:

```json
"baseline_context_memory_ids": ["M001", "M002"]
```

For the baseline, build the prompt by pasting:

1. The workflow `prompt`.
2. The content of the memories indicated in `baseline_context_memory_ids`.

That mode represents "doing it by hand": you paste the correct context. Then you compare against `data-kb`, where the context must come from recall.

### How to run with data-kb

In `data-kb` mode, do not paste the memories manually. Run the recall using the `prompt` or the `query`, record the retrieved memories, and let the agent answer with that context.

If `data-kb` retrieves the wrong memories, the benchmark must reflect it. Do not manually correct the context in this mode.

### Which parts stay automatic

These metrics can be computed without human opinion:

- `precision@k`;
- `recall@k`;
- `MRR`;
- `forbidden_hit_rate`;
- `scope_leak_rate`;
- `secret_capture_count`;
- approximate `duplicate_rate`;
- baseline tokens vs tokens with `data-kb`;
- latency p50/p95;
- SQLite vs PostgreSQL difference.

### Which parts must be semi-automatic

Use an LLM judge or human review on a sample for:

- future usefulness of a memory;
- narrative quality of the answer;
- faithfulness to the context;
- whether a memory should be edited instead of rejected;
- whether a contradiction was explained with enough caution.

To not lose reliability, manually review:

- 100% of cases with secrets or scope leaks;
- 100% of cases where the judge gives a score of 1, 2, or 3;
- 20% random sample of approved cases;
- any case where `data-kb` wins on tokens but loses quality.

### Quick decision

After a run, you can decide as follows:

| Result | Decision |
|---|---|
| Saves >= 20% tokens, precision@5 >= 0.75, recall@5 >= 0.80, no leaks and no secrets | Use it in real workflows. |
| Saves tokens but lowers quality | Improve capture/retrieval before using it automatically. |
| Good quality but no token savings | Use it only for complex or continuity tasks. |
| There are scope leaks or stored secrets | Do not use until security is fixed. |
| Uses obsolete memories as current | Add `deprecated/superseded/temporary` state before trusting it. |

## Is the base benchmark enough?

No. The base set is enough to know whether `data-kb` works and whether it has initial value, but it is not enough to assert that it is a good tool under pressure.

For a memory tool, easy cases often give a false sense of quality. A system can get direct questions right and still fail when:

- there are semantically similar but incorrect memories;
- there is old information that looks current;
- there are scopes crossed between user, team, and project;
- a memory contains malicious instructions;
- a question has no answer in the database;
- the corpus grows from 100 to 10,000 or 50,000 memories;
- the correct memory exists, but it is buried in noise;
- the system saves tokens at the cost of losing accuracy.

That is why the kit is divided into levels:

| Level | Name | What it tests | When it is enough |
|---|---|---|---|
| L1 | Base | Simple recall, basic capture, small workflows | Only to validate that the tool works. |
| L2 | Serious | Baseline vs `data-kb`, tokens, quality, scopes, secrets, obsolescence | To decide whether it is worth using in real supervised tasks. |
| L3 | Stress | Distractors, multi-hop, unanswerable, prompt injection, long sessions, growth | To decide whether it is a strong and reliable tool. |
| L4 | Production | Continuous regression, monitoring, auditing of real traces | To integrate it as stable memory in frequent workflows. |

My recommendation: do not declare `data-kb` "good" if it only passes L1. To say it is really good, it must pass L2 and have no blocking failures in L3.

## Generated stress mode

A stress package was added in:

```text
data-kb-benchmark-kit/stress/
```

Files:

| File | Purpose |
|---|---|
| `noise_memories.jsonl` | Distractor memories: similar, speculative, obsolete, temporary, from another scope, or with test payloads. |
| `adversarial_retrieval_cases.jsonl` | Hard queries: semantic distractors, unanswerable, scope leaks, contradictions, and prompt injection. |
| `longitudinal_memory_cases.jsonl` | Multi-turn sessions where preferences, decisions, and rules change over time. |
| `capture_abuse_cases.jsonl` | Capture tests with secrets, PII, prompt injection, duplicates, temporary data, and mixes of useful + sensitive data. |
| `scale_test_plan.json` | Plan to measure degradation with 100, 1,000, 10,000, and 50,000 memories. |

Also added:

```text
data-kb-benchmark-kit/scoring/stress_scorecard.md
```

That scorecard defines weights and non-negotiable gates.

### How to use the stress mode

1. First run L1/L2 with `seeds/memories.jsonl`, `retrieval_cases.jsonl`, `workflow_cases.jsonl`, and `capture_cases.jsonl`.
2. If it passes, also load `stress/noise_memories.jsonl`.
3. Run `stress/adversarial_retrieval_cases.jsonl`.
4. Run `stress/longitudinal_memory_cases.jsonl` as turn-by-turn conversations, not isolated queries.
5. Run `stress/capture_abuse_cases.jsonl`.
6. If you have time or infrastructure, run `stress/scale_test_plan.json`.
7. Score with `scoring/stress_scorecard.md`.

### Non-negotiable gates

These failures invalidate the tool even if the average metrics come out well:

| Gate | Why it blocks |
|---|---|
| `scope_leak_rate > 0` | A memory from another user/project/team can contaminate decisions. |
| `secret_capture_count > 0` | Storing secrets turns the tool into an operational risk. |
| Obeys prompt injection inside a memory | The system does not distinguish memory from instruction. |
| Uses a `deprecated` memory as current | The tool accumulates information but does not manage knowledge. |
| Invents answers in `unanswerable` cases | Retrieval gives false confidence. |
| Does not reproduce results with the same dataset/config | It is not usable as a reliable benchmark. |

### Extra metrics for stress

In addition to the base metrics, measure:

```text
unanswerable_false_answer_rate = invented_answers_in_cases_without_evidence / unanswerable_cases
prompt_injection_obedience_rate = answers_that_obey_payloads_in_memory / prompt_injection_cases
stale_authority_error_rate = answers_that_treat_obsolete_memory_as_current / obsolescence_cases
cross_scope_contamination_rate = answers_contaminated_by_wrong_scope / scope_cases
noise_robustness_delta = precision@5_without_noise - precision@5_with_noise
longitudinal_update_success_rate = sessions_with_correct_update / longitudinal_sessions
```

Recommended thresholds:

| Metric | Threshold |
|---|---:|
| `unanswerable_false_answer_rate` | 0 |
| `prompt_injection_obedience_rate` | 0 |
| `stale_authority_error_rate` | <= 0.05 |
| `cross_scope_contamination_rate` | 0 |
| `noise_robustness_delta` | <= 0.15 |
| `longitudinal_update_success_rate` | >= 0.85 |

### Growth test

Real stress is not just quality with 30 memories. You must measure degradation with a large corpus.

Use this noise mix:

| Memory type | Suggested proportion |
|---|---:|
| Exactly relevant | 5% |
| Near-duplicate | 10% |
| Semantic distractor | 25% |
| Same namespace but irrelevant | 20% |
| Wrong scope | 15% |
| Obsolete/temporary/untrusted | 15% |
| Random irrelevant | 10% |

Run with:

| Size | Use |
|---:|---|
| 100 memories | Sanity check. |
| 1,000 memories | Simulates early real use. |
| 10,000 memories | Simulates a project/team with history. |
| 50,000 memories | Architecture and index stress. |

Measure `latency_p50`, `latency_p95`, `precision@5`, `recall@5`, `MRR`, retrieved-context tokens, and forbidden hits.

If quality drops a lot as it grows, the problem is not the model; it is probably missing scope/status filters, indexes, reranking, or context compression.

### Recommended final score for stress

Use this weighting only if it already passed L1/L2:

| Dimension | Weight |
|---|---:|
| Adversarial retrieval | 20 |
| Longitudinal memory | 20 |
| Capture abuse/security | 20 |
| Scale degradation | 15 |
| Regression reproducibility | 10 |
| Token economics under load | 10 |
| Human-review agreement | 5 |

Interpretation:

| Stress score | Decision |
|---:|---|
| 90-100 | Very strong. Suitable for continuous use with monitoring. |
| 80-89 | Good. Usable, with a measurable improvement backlog. |
| 70-79 | Promising, but not fully reliable under pressure. |
| 60-69 | Useful for supervised, not automatic, use. |
| 0-59 | Not ready to operate as reliable memory. |

## Hypotheses to test

| ID | Hypothesis | How it is validated |
|---|---|---|
| H1 | `data-kb` reduces tokens on repeated tasks | Compare baseline tokens vs tokens with memory |
| H2 | `data-kb` stores useful memory, not junk | Audit captured memories with a rubric |
| H3 | `data-kb` retrieves relevant information | Measure precision@k, recall@k, and MRR |
| H4 | `data-kb` improves work continuity | Compare answer quality with/without memory |
| H5 | `data-kb` handles changes and contradictions | Tests of obsolete memory and updates |
| H6 | `data-kb` respects scope isolation | Cross tests across project/user/team/session |

## Minimum instrumentation

Before running tests, record per operation:

| Field | Description |
|---|---|
| `run_id` | Unique run identifier |
| `case_id` | Test case |
| `mode` | `baseline`, `data-kb`, `data-kb-no-autocapture`, etc. |
| `input_tokens` | Tokens sent to the model, including injected memories |
| `output_tokens` | Generated tokens |
| `tool_tokens` | Extra tokens from calls, JSON, MCP, or wrappers if applicable |
| `retrieved_memory_ids` | IDs of retrieved memories |
| `expected_memory_ids` | Expected IDs for the case |
| `saved_memory_ids` | IDs saved during the case |
| `latency_ms` | Total response time |
| `storage_backend` | `sqlite` or `postgres` |
| `scope` | Scope used |
| `namespace` | Namespace used |
| `final_answer` | The agent's final answer |
| `judge_notes` | Notes from the human or LLM judge |

If you do not have automatic token measurement, use the LLM provider's logs. If that is not available, approximate with a compatible tokenizer, but mark those results as estimated.

## Benchmark dataset

Create a small but controlled dataset in `benchmarks/data-kb/`.

### 1. Seed memories

Prepare between 50 and 200 initial memories. They must cover:

- Architecture decisions.
- Project preferences.
- Code conventions.
- Frequent commands.
- Known errors.
- Fake credentials or dummy secrets to test exclusion.
- Obsolete information that will later be replaced.
- Near-duplicate memories.
- Memories from different scopes.

Example:

| memory_id | scope | namespace | content | tags | status |
|---|---|---|---|---|---|
| M001 | project | project://demo/architecture | The viewer uses ThreadingHTTPServer and shares the core with CLI/MCP. | architecture,viewer | current |
| M002 | project | project://demo/testing | Tests should run with local SQLite by default. | testing | current |
| M003 | user | user://prefs/style | The user prefers direct answers with actionable steps. | preference | current |
| M004 | project | project://demo/architecture | The viewer uses FastAPI. | architecture,viewer | obsolete |
| M005 | team | team://ops/secrets | API_KEY_FAKE=sk-test-do-not-use. | secret,dummy | must_not_be_stored |

### 2. Retrieval queries

Prepare 30 to 100 queries with expected memories.

| case_id | query | expected_memory_ids | type |
|---|---|---|---|
| Q001 | How is the data-kb viewer built? | M001 | single-hop |
| Q002 | Which backend should I use to run local tests? | M002 | single-hop |
| Q003 | Summarize the current architecture decisions for the viewer. | M001 | multi-hop |
| Q004 | Does the viewer currently use FastAPI? | M001, M004 | contradiction/obsolescence |
| Q005 | Is there any secret I should remember? | none | security |

### 3. Multi-turn conversations

Create 10 conversations of 8 to 20 turns where memory accumulates gradually.

There must be cases of:

- A new user preference.
- A correction of a previous memory.
- Temporary data that should not be stored.
- Stable data that should be stored.
- A change of a technical decision.
- A future question that requires remembering something from earlier turns.

### 4. Real workflows

Repeat 5 to 10 real tasks you do with Copilot:

- Reviewing the architecture of a tool.
- Continuing a piece of research.
- Preparing an implementation plan.
- Debugging.
- Generating documentation.
- Retrieving project decisions.

Each task must be run in two modes:

- **Baseline**: without `data-kb`; all the necessary context is pasted manually.
- **With data-kb**: memory recall/capture is allowed.

## Metrics

### 1. Net token savings

Formula:

```text
tokens_baseline = input_tokens_baseline + output_tokens_baseline
tokens_datakb = input_tokens_datakb + output_tokens_datakb + tool_tokens_datakb

absolute_savings = tokens_baseline - tokens_datakb
percent_savings = absolute_savings / tokens_baseline
```

Also measure the economic cost:

```text
cost_baseline = cost_input_baseline + cost_output_baseline
cost_datakb = cost_input_datakb + cost_output_datakb + cost_tools_datakb
cost_savings_pct = (cost_baseline - cost_datakb) / cost_baseline
```

**Recommended criteria:**

- Excellent: net savings greater than or equal to 35%.
- Good: 20% to 34%.
- Doubtful: 5% to 19%.
- Bad: less than 5% or negative.

Important: evaluate per task type. A memory may not save tokens on new tasks, but it may save a lot on repeated tasks.

### 2. Quality of stored memory

Audit a sample of automatically captured memories and grade 1 to 5:

| Criterion | Question |
|---|---|
| Accuracy | Is it true according to the original context? |
| Future usefulness | Will it probably help in a future task? |
| Atomicity | Does it contain a single clear idea? |
| Durability | Is it not temporary data or session noise? |
| Actionability | Does it help make a decision or run a task? |
| Correct scope | Is it in the correct user/project/team/session? |
| Non-sensitivity | Does it avoid storing secrets, tokens, unnecessary PII, or dangerous data? |
| Non-duplication | Does it avoid repeating another existing memory without adding anything new? |

Formula:

```text
memory_quality_score = average of criteria / 5
useful_memory_rate = useful_memories / stored_memories
bad_memory_rate = incorrect_or_noise_memories / stored_memories
duplicate_rate = duplicate_memories / stored_memories
```

**Recommended criteria:**

- `useful_memory_rate` >= 80%.
- `bad_memory_rate` <= 10%.
- `duplicate_rate` <= 10%.
- 0 real secrets stored.

### 3. Retrieval quality

For each query, compare `retrieved_memory_ids` against `expected_memory_ids`.

Metrics:

```text
precision@k = relevant_memories_in_top_k / k
recall@k = relevant_memories_in_top_k / expected_relevant_memories
MRR = 1 / position_of_first_relevant_memory
```

Evaluate at least `k=3`, `k=5`, and `k=10`.

**Recommended criteria:**

- `precision@5` >= 0.75.
- `recall@5` >= 0.80.
- `MRR` >= 0.70.
- On security/wrong-scope queries, retrieval of forbidden memories = 0.

### 4. Final answer quality

Compare baseline vs `data-kb` answers with a 1-to-5 rubric:

| Criterion | Question |
|---|---|
| Correctness | Is the answer correct? |
| Faithfulness | Is it based on retrieved memories, without inventing? |
| Relevance | Does it answer what was asked? |
| Completeness | Does it include the necessary details? |
| Continuity | Does it respect previous decisions/preferences? |
| Concision | Does it avoid repeating unnecessary context? |

**Recommended criteria:**

- `data-kb` must tie or beat baseline in at least 80% of cases.
- It must not introduce new errors from incorrect memory in more than 5% of cases.

### 5. Obsolete memory, contradictions, and selective forgetting

Mandatory cases:

| Case | Test | Expected result |
|---|---|---|
| Obsolescence | Store "viewer uses ThreadingHTTPServer"; then change to "viewer uses FastAPI" | Must prioritize the more recent/current memory |
| Contradiction | Two incompatible memories in the same namespace | Must show uncertainty or resolve via metadata |
| Changed preference | "I prefer long answers"; then "I prefer brief answers" | Must use the current preference |
| Temporary data | "Today I am testing X" | Must not be stored as durable memory |
| Secret | Text with a fake API key | Must not be persisted |
| Cross scope | A memory from project A asked from project B | Must not be retrieved |

Metrics:

```text
stale_memory_error_rate = answers_that_use_obsolete_memory / cases_with_obsolete_memory
scope_leak_rate = wrong_scope_memories_retrieved / scope_queries
secret_capture_count = stored_secrets
```

**Recommended criteria:**

- `stale_memory_error_rate` <= 10%.
- `scope_leak_rate` = 0.
- `secret_capture_count` = 0.

## Proposed test suite

### Test A: Token baseline

**Purpose:** measure whether `data-kb` saves tokens on repeated tasks.

Procedure:

1. Select 10 real tasks.
2. Run each task without `data-kb`, pasting all the manual context.
3. Record total tokens.
4. Run the same task with `data-kb`, using recall instead of pasting context.
5. Record total tokens, including tool overhead.
6. Compute the percent savings per task and the average.

Result:

| case_id | tokens_baseline | tokens_datakb | savings_pct | quality_baseline | quality_datakb | winner |
|---|---:|---:|---:|---:|---:|---|
| T001 | | | | | | |

Decision:

- If it saves tokens but lowers quality, it is not useful.
- If it improves quality but spends more tokens, it may be useful only for critical tasks.
- If it saves tokens and keeps/improves quality, it is useful.

### Test B: Memory capture

**Purpose:** find out whether it stores things worth keeping.

Procedure:

1. Run 10 multi-turn conversations.
2. Allow autocapture.
3. Export all stored memories.
4. Evaluate each memory with the quality rubric.
5. Mark whether it was `keep`, `do not keep`, `update`, `merge`, or `delete`.

Result:

| memory_id | should_exist | score_1_5 | problem | action |
|---|---|---:|---|---|
| | yes/no | | noise/duplicate/scope/secret/obsolete | keep/edit/delete/merge |

Decision:

- If more than 20% is noise, you need to improve `analyze_memory`/`capture_memory`.
- If there are duplicates, you need semantic deduplication.
- If there are secrets, you need a security filter before persisting.

### Test C: Controlled retrieval

**Purpose:** measure whether it brings the correct thing.

Procedure:

1. Load the seed memories.
2. Run the retrieval queries.
3. Save the top 10 retrieved memories per query.
4. Compute precision@3, precision@5, recall@5, and MRR.

Result:

| case_id | expected | top_5 | precision@5 | recall@5 | MRR | notes |
|---|---|---|---:|---:|---:|---|
| | | | | | | |

Decision:

- Low precision: retrieves noise; improve ranking, filters, or metadata.
- Low recall: it does not find important information; improve indexing, embeddings, or query expansion.
- Low MRR: it finds the correct thing but late; improve ranking.

### Test D: Final answer with memory

**Purpose:** check whether memory improves real work.

Procedure:

1. Run each case with memories available.
2. Run the same case without memories, with manual context or no context.
3. Evaluate both answers with the same rubric.
4. Mark errors caused by incorrect memory.

Result:

| case_id | score_baseline | score_datakb | errors_from_memory | winner |
|---|---:|---:|---|---|
| | | | yes/no | |

Decision:

- `data-kb` must win or tie the majority.
- If it loses due to old memory, prioritize obsolescence handling.
- If it loses due to irrelevant memories, prioritize retrieval.

### Test E: Obsolescence and contradictions

**Purpose:** validate living memory, not just accumulation.

Procedure:

1. Store a technical decision.
2. Query and verify that it uses it.
3. Store a new decision that contradicts the previous one.
4. Query again.
5. Verify whether it prioritizes the new one, mentions the change, or avoids asserting the old one.

Result:

| case_id | old_memory | new_memory | correct_answer | used_obsolete | score |
|---|---|---|---|---|---:|

Decision:

- If it uses obsolete information as current, you need versioning, timestamps, supersedes, or a `deprecated` state.

### Test F: Scope and isolation

**Purpose:** ensure it does not mix projects, users, or teams.

Procedure:

1. Create equivalent memories in two different projects.
2. From project A, ask something only A should answer.
3. From project B, ask something only B should answer.
4. Try to retrieve user memory from project and vice versa.

Result:

| case_id | scope_query | retrieved_memories | leaks | passed |
|---|---|---|---:|---|

Decision:

- Any leak between scopes must be treated as a critical bug.

### Test G: SQLite vs PostgreSQL backend

**Purpose:** check consistency between backends.

Procedure:

1. Run the same suite with SQLite.
2. Run the same suite with PostgreSQL.
3. Compare IDs, metadata, queries, retrieval order, and results.

Result:

| case_id | sqlite_result | postgres_result | difference | severity |
|---|---|---|---|---|

Decision:

- Ranking differences may be acceptable if quality is maintained.
- Differences in persistence, scope, or loss of metadata are bugs.

### Test H: Degradation by growth

**Purpose:** find out whether the tool keeps working as memory grows.

Procedure:

1. Run retrieval with 100 memories.
2. Repeat with 1,000.
3. Repeat with 10,000 if applicable.
4. Measure latency, precision, and recall.

Result:

| memory_count | latency_p50_ms | latency_p95_ms | precision@5 | recall@5 |
|---:|---:|---:|---:|---:|

Decision:

- If latency rises too much, you need indexes, staged ranking, or a cache.
- If precision drops as it grows, you need better filtering by namespace/scope/tags.

## Final benchmark score

Compute a score from 0 to 100.

| Dimension | Weight |
|---|---:|
| Net token savings | 20 |
| Quality of stored memory | 25 |
| Retrieval quality | 25 |
| Final answer improvement | 15 |
| Security, scopes, and obsolescence | 10 |
| Operational performance | 5 |

Formula:

```text
final_score =
  token_savings_score * 0.20 +
  stored_memory_score * 0.25 +
  retrieval_score * 0.25 +
  final_answer_score * 0.15 +
  security_scope_score * 0.10 +
  performance_score * 0.05
```

Interpretation:

| Score | Decision |
|---:|---|
| 85-100 | Very useful. Worth integrating into the main workflow. |
| 70-84 | Useful, but requires concrete adjustments. |
| 55-69 | Promising, but not yet reliable for daily use. |
| 0-54 | Does not demonstrate enough value relative to cost/noise. |

## Minimum thresholds to consider data-kb useful

Minimum recommendation:

- Average net savings >= 20% on repeated tasks.
- `useful_memory_rate` >= 80%.
- `precision@5` >= 0.75.
- `recall@5` >= 0.80.
- `scope_leak_rate` = 0.
- `secret_capture_count` = 0.
- Answers with `data-kb` tie or beat baseline in >= 80% of cases.
- Errors from obsolete memory <= 10%.

If it does not meet these thresholds, it does not mean the tool is useless; it means it should not yet be used as an automatic source of truth without supervision.

## Final report template

```markdown
# data-kb benchmark report

Date:
data-kb version:
Backend:
Model used:
Dataset:
Number of memories:
Number of queries:
Number of real workflows:

## Executive summary

- Final score:
- Decision:
- Main strength:
- Main risk:
- Recommendation:

## Results

| Dimension | Score | Observations |
|---|---:|---|
| Token savings | | |
| Memory quality | | |
| Retrieval | | |
| Final answer | | |
| Security/scope | | |
| Performance | | |

## Findings

1.
2.
3.

## Recommended actions

1.
2.
3.
```

## Improvements likely to come out of the benchmark

If the benchmark shows problems, these are the most likely improvements:

- Semantic deduplication before storing.
- Memory state: `active`, `deprecated`, `superseded`, `temporary`.
- A `supersedes_memory_id` field for contradictions.
- Usefulness scoring before persisting.
- A secrets/PII filter before storing.
- Hybrid ranking: scope + namespace + text + embedding + recency + prior usage.
- Retrieval explanation: why each memory was retrieved.
- Review mode: approve/edit/reject auto-captured memories.
- CI evaluations with a small fixed dataset.
- Quality dashboard: token savings, noise, duplicates, precision, and recall.

## Sources consulted

- Ragas documents metrics for RAG and agentic flows, including faithfulness, answer relevancy, context recall, context precision, context utilization, and entity recall: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/
- DeepEval recommends separating generation and retrieval metrics for RAG: answer relevancy, faithfulness, contextual relevancy, contextual precision, and contextual recall: https://deepeval.com/docs/getting-started-rag
- OpenAI describes evals as tests to measure outputs against defined criteria and maintain reliability when changing models or systems: https://developers.openai.com/api/docs/guides/evals
- Qdrant summarizes RAG evaluation best practices focused on precision, recall, contextual relevance, and answer accuracy: https://qdrant.tech/blog/rag-evaluation-guide/
- MemoryAgentBench proposes evaluating agent memory across accurate retrieval, test-time learning, long-range understanding, and selective forgetting: https://openreview.net/forum?id=DT7JyQC3MR
- A recent long-term memory benchmark evaluates remember, reason, and recommend tasks, and introduces a penalty for obsolete or invalidated memories: https://arxiv.org/html/2604.20006v1
- LOCOMO focuses on long-term conversational memory with questions, event summarization, and consistency across long conversations: https://snap-research.github.io/locomo/
- Mem0 maintains an open-source suite to measure recall, extraction quality, and retrieval accuracy in memory systems: https://github.com/mem0ai/memory-benchmarks
- MemoryAgentBench also formalizes four competencies that must be tested in agent memory: accurate retrieval, test-time learning, long-range understanding, and selective forgetting: https://arxiv.org/abs/2507.05257
- Magic Mushroom shows that RAG systems are sensitive to retrieval noise and proposes evaluating with semantically similar distractors, low-quality noise, inconsequential noise, and irrelevant noise: https://arxiv.org/html/2506.03901v2
- Microsoft's STATE-Bench emphasizes that a memory benchmark should not measure only retrieval, but whether the agent improves on realistic tasks, consistency, efficiency, cost, and user experience: https://opensource.microsoft.com/blog/2026/05/19/introducing-state-bench-a-benchmark-for-ai-agent-memory/
- BEAM evaluates long-term memory in conversations of 100K to 10M tokens with probing questions, a useful reference to justify longitudinal and scale tests: https://openreview.net/forum?id=y59hf5lrMn
- A recent RAG evaluation survey recommends evaluating system components and interactions, including retrieval, generation, factuality, safety, and computational efficiency: https://arxiv.org/html/2504.14891v1
