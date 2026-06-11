# Integration guide: wiring the benchmark to a real data-kb

This repo ships a **fully working benchmark harness**. The only thing it
cannot know in advance is the exact CLI of your `data-kb` installation.
This document lists exactly what you must adjust to run it for real.

## TL;DR

```bash
# 1. Validate the harness itself (no data-kb needed):
python runner.py --demo

# 2. Discover your data-kb CLI:
data-kb --help

# 3. Edit benchmark_config.toml:
#      [run].adapter = "command"
#      fill in [commands.reset|import|recall|capture|export]
#      (optionally [commands.generate] and [action_synonyms])

# 4. Smoke-test the wiring, then run everything:
python runner.py --adapter command --phases smoke
python runner.py --adapter command --phases all
```

Everything lands in `runs/<RUN_ID>/`: per-case JSONL evidence,
`metrics.json`, `report.md`, `results.csv`, and `run_config.json`
(config snapshot + dataset checksums, for the reproducibility gate).

## Requirements

- Python **3.11+** (standard library only — no pip installs).
- A `data-kb` installation with a CLI (or any wrapper script you write).
- An **isolated, disposable** database. The runner calls `reset`
  repeatedly; never point it at a database with real memories.

## What is already done vs. what you must do

| Piece | Status |
|---|---|
| Datasets (seeds, cases, stress) | ✅ done (`data-kb-benchmark-kit/`) |
| Runner, phases, evidence files | ✅ done (`runner.py`) |
| Deterministic metrics + gates | ✅ done (`scorer.py`) |
| Report + metrics.json + results.csv | ✅ done (`reporter.py`) |
| Mock adapter / pipeline self-test | ✅ done (`python runner.py --demo`) |
| Scale corpus generator | ✅ done (`tools/generate_scale_corpus.py`) |
| Unit tests | ✅ done (`python -m unittest discover -s tests`) |
| **Command templates for YOUR data-kb** | ❌ you (`benchmark_config.toml [commands.*]`) |
| **Action-name mapping for YOUR data-kb** | ❌ you (`[action_synonyms]`, only if names differ) |
| **LLM call for workflow generation** | ❌ optional (`[commands.generate]`) |
| **Human/LLM judge for soft criteria** | ❌ you (see "What stays manual") |

## The 6 operations to wire

Each is a `[commands.<op>]` section in `benchmark_config.toml`. The
shipped file contains commented examples for all of them — **the example
flags are guesses; replace them with the real ones from `data-kb --help`.**

| Operation | Required? | Purpose | Placeholders you can use | Response fields the runner reads |
|---|---|---|---|---|
| `reset` | yes | wipe the benchmark DB for a reproducible run | `{db}` `{backend}` + `[vars]` | none (`response.format = "none"` if it prints no JSON) |
| `import` | yes | store one seed memory | `{memory}` (whole object), `{memory.content}`, `{memory_json}` | `id` (id assigned by the tool), `accepted` (optional bool) |
| `recall` | yes | query memory, return ordered top-k | `{query}` `{scope}` `{namespace}` `{top_k}` | `ids` (**required**, ordered), `latency_ms` (optional) |
| `capture` | yes | analyze an input: save/reject/update/merge | `{input}` `{scope}` `{namespace}` | `action` (**required**), `saved_ids`, `latency_ms` |
| `export` | yes | list all stored memories (secret scanning, verification) | `[vars]` only | `memories` (list) + `[commands.export.fields]` name mapping |
| `generate` | optional | produce the final answer for workflow cases (an LLM call) | `{prompt}` `{context}` | `answer`, `input_tokens`, `output_tokens` |

### How command templates work

```toml
[commands.recall]
argv = ["data-kb", "tool", "--json", "{payload}"]   # the process to run
timeout_s = 60

[commands.recall.payload]      # optional: built into {payload} as JSON
action = "recall"              # (handles quoting/escaping safely —
query = "{query}"              #  more robust than embedding JSON in argv)
scope = "{scope}"
namespace = "{namespace}"
top_k = "{top_k:int}"          # :int / :float / :json casts

[commands.recall.response]     # dotted paths into the JSON on stdout
ids = "memories[].memory_id"   # "x[].y" = field y of each element of list x
latency_ms = "latency_ms"
```

Rules:

- The command must print **JSON to stdout** (log lines around it are
  tolerated; the last parseable JSON line wins).
- A non-zero exit code fails the call.
- A token that is *exactly* one placeholder keeps its native type;
  placeholders inside longer strings are substituted as text.
- Anything in `[vars]` is available as a placeholder in every command —
  use it for db paths, backend names, profiles, etc.
- If your data-kb has no single command for an operation, write a small
  wrapper script and point `argv` at it. The contract is the wrapper's
  stdout, not data-kb's internals.

### ID mapping (important)

The retrieval cases expect kit IDs (`M001`, `N007`...). If your data-kb
assigns its own IDs on import, map `[commands.import].response.id` to the
field carrying the new id: the runner records `tool_id -> kit_id`
(saved as `runs/<RUN_ID>/id_map.json`) and translates retrieved ids back
before scoring. If your tool preserves ids, you can omit `response.id`.

If `recall` cannot return ids at all (only contents), scoring cannot work —
add an id field to its output or wrap it with a content→id lookup
against `export`.

### Action vocabulary

`capture` must return an action string. The scorer normalizes it to this
atomic vocabulary:

```
save  save_temporary  save_session  save_untrusted  save_other_scope
save_low_priority  partial_save  redact  reject  update  supersede
deprecate  merge  ignore
```

Common synonyms (`stored`, `skip`, `deduplicate`, ...) are already mapped.
If your data-kb uses other names, add them under `[action_synonyms]`:

```toml
[action_synonyms]
captured = "save"
discarded = "reject"
```

Compound expectations in the case files (e.g.
`merge_or_reject_duplicate`) accept any of their listed atomic actions;
ambiguous or unknown actions are not failed silently — they are flagged
`needs_human_review`. You can extend acceptance per expectation with
`[action_equivalences]`.

## Phase-by-phase

Canonical order (the runner always re-sorts your `--phases` into it):

| Phase | What it does | Output |
|---|---|---|
| `smoke` | reset → import 1 memory → recall it; aborts the run if wiring is broken | `smoke.json` |
| `seed` | clean DB + 30 seed memories (sends `do_not_persist` ones on purpose to test the filter — see `[policy]`) | `seed_import.jsonl`, `id_map.json` |
| `retrieval` | 34 base queries, top-10, scored | `retrieval_results.jsonl` |
| `workflows` | 6 tasks × (baseline vs data-kb); needs `generate`, else writes prompts for manual run | `workflow_results.jsonl`, `workflow_prompts/` |
| `capture` | 8 capture cases, action matching + secret scan | `capture_results.jsonl` |
| `adversarial` | reseeds + 30 noise memories, 20 hard queries | `adversarial_results.jsonl`, `noise_import.jsonl` |
| `capture_abuse` | reseeds; 10 abuse cases; `must_not_save_patterns` scanned against exports | `capture_abuse_results.jsonl` |
| `longitudinal` | 8 multi-turn sessions (reset per case), final-turn probe | `longitudinal_results.jsonl` |
| `scale` | retrieval suite against 100/1k/10k/50k corpora | `scale_results.jsonl` |
| `score` | aggregates everything, applies gates | `metrics.json`, `report.md`, `results.csv` |

Notes:

- Phases self-manage corpus state: each one resets/reseeds to a known
  state, so you can run subsets (`--phases retrieval,score`).
- `scale` needs corpora first:
  `python tools/generate_scale_corpus.py --sizes 100,1000,10000`
  then `python runner.py --adapter command --phases scale,score --scale-sizes 100,1000,10000`.
- To compare SQLite vs PostgreSQL (Test G of the plan), run the suite
  twice changing `[vars].backend`/`db` and diff the two `metrics.json`.

## What stays manual (by design)

Deterministic metrics never need an opinion. The rest is flagged in
`metrics.json → needs_human_review` and in the report:

- **Adversarial behavior** (did the answer obey the injected payload?
  invent an unanswerable fact? treat deprecated as current?) — judge each
  flagged case with `data-kb-benchmark-kit/templates/judge_rubric.md`,
  then settle the three `needs_review` gates.
- **Workflow answer quality** — the runner computes a facts-coverage
  proxy, but correctness/faithfulness scoring is the judge's.
- **Longitudinal final behavior** — turn-level action accuracy and secret
  persistence are automatic; "did it use the *current* preference?" is not.
- Review coverage per the guide: 100% of secret/leak cases, 100% of low
  scores, 20% random sample of passes.

## Checklist before trusting a real run

- [ ] `python runner.py --demo` passes (harness OK).
- [ ] `python -m unittest discover -s tests` passes.
- [ ] `--phases smoke` passes against real data-kb.
- [ ] `seed_import.jsonl` shows 30 processed and sensible ids/mapping.
- [ ] A couple of `retrieval_results.jsonl` rows eyeballed: retrieved ids
      are kit ids (`M001`...), not raw tool ids.
- [ ] `capture_results.jsonl`: `returned_action` values look right; add
      `[action_synonyms]` if many fall to `needs_review` for vocabulary.
- [ ] Gates section of `report.md` reviewed; judge items resolved.
- [ ] Same run repeated twice gives the same deterministic metrics
      (reproducibility gate).

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `operation 'recall' is not configured` | Missing `[commands.recall]` in the config. |
| `could not parse JSON from command output` | The tool prints text/logs; add a `--json` flag or wrap it. The last JSON-parseable stdout line is also accepted. |
| `executable not found` | `data-kb` not on PATH; use an absolute path in `argv`. |
| Smoke fails: imported memory not recalled | Wrong `response.ids` path, ids not mapped (set `import.response.id`), or recall filters by a scope/namespace you are not passing. |
| All retrieval metrics 0 but tool "works" | Retrieved ids are tool-internal and unmapped → check `id_map.json`. |
| Many capture cases `needs_review: ambiguous action vocabulary` | Your tool's action names are unknown → map them in `[action_synonyms]`. |
| Workflows all `pending_generation` | No `[commands.generate]` — intended; run `workflow_prompts/*.txt` manually/with your agent and fill results, or wire a generate command. |
| Latency looks like wall-clock of a slow CLI | Provide `response.latency_ms` so the tool reports its own internal latency. |
