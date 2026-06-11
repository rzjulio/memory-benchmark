# data-kb memory benchmark

A complete, runnable benchmark to decide whether `data-kb` (an agent
memory tool) actually adds value: token savings, memory quality,
retrieval quality, answer impact, and operational reliability — including
adversarial, longitudinal, security, and scale stress testing.

## Quick start

```bash
# Validate the whole pipeline (no data-kb required):
python runner.py --demo

# Unit tests:
python -m unittest discover -s tests

# Real run (after wiring your data-kb CLI in benchmark_config.toml):
python runner.py --adapter command --phases all
```

Requires Python 3.11+, standard library only.

## Repository map

| Path | What it is |
|---|---|
| `data-kb-benchmark-plan.md` | The full methodology: metrics, thresholds, test suite, scoring. |
| `data-kb-benchmark-kit/` | Datasets: seeds, retrieval/workflow/capture cases, stress packs, rubric, scorecard. |
| `data-kb-benchmark-kit/EXECUTION_GUIDE.md` | Phase-by-phase execution guide. |
| `runner.py` | Orchestrates all phases, writes per-case evidence to `runs/<RUN_ID>/`. |
| `scorer.py` | Deterministic metrics: P@k, R@k, MRR, leaks, secret scanning, gates. |
| `reporter.py` | Generates `report.md`, `metrics.json` summary tables, `results.csv`. |
| `adapters.py` | `CommandAdapter` (wraps your real data-kb CLI) + `MockAdapter` (demo). |
| `benchmark_config.toml` | All configuration; the `[commands.*]` sections are what you wire. |
| `tools/generate_scale_corpus.py` | Builds 100/1k/10k/50k synthetic corpora for the scale phase. |
| `INTEGRATION.md` | **Start here for a real run** — exactly what to modify and how. |

## Status

- The harness, datasets, metrics, gates, and reporting are complete and
  self-tested (`--demo` runs all phases with a built-in mock).
- The only thing not included is your `data-kb` CLI wiring
  (`benchmark_config.toml → [commands.*]`) and the human/LLM judge pass
  for soft criteria. Both are documented in `INTEGRATION.md`.
