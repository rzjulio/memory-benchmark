"""Generates runs/<RUN_ID>/report.md and results.csv from metrics.json."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def _fmt(value, pct: bool = False) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value * 100:.1f}%" if pct else f"{value:.3f}"
    return str(value)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


GATE_LABELS = {
    "pass": "PASS", "fail": "**FAIL**", "needs_review": "needs review",
    "not_run": "not run", "manual_check": "manual check",
}


def write_report(metrics: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    lines: list[str] = []
    add = lines.append

    add(f"# data-kb benchmark report — `{metrics.get('run_id', '?')}`")
    add("")
    add(f"- Generated: {metrics.get('generated_at', '?')}")
    add(f"- Adapter: `{metrics.get('adapter', '?')}`"
        + (" *(mock — results are illustrative, NOT a verdict on data-kb)*"
           if metrics.get("adapter") == "mock" else ""))
    add(f"- Kit: `{metrics.get('kit_dir', '?')}` "
        f"(dataset sha256 in `run_config.json` for reproducibility)")
    add(f"- Verdict: **{metrics.get('verdict', '?')}**")
    add("")

    # ---- gates ----
    add("## Non-negotiable gates")
    add("")
    gates = metrics.get("gates", {})
    add(_table(["Gate", "Status"],
               [[g.replace("_", " "), GATE_LABELS.get(s, s)] for g, s in gates.items()]))
    add("")
    if any(s == "fail" for s in gates.values()):
        add("> One or more gates FAILED. Per the scorecard, the tool must not "
            "pass this run regardless of average scores.")
        add("")

    # ---- scores ----
    scores = metrics.get("scores", {})
    add("## Deterministic scores (vs plan thresholds, 100 = meets threshold)")
    add("")
    add(_table(["Dimension", "Score"], [
        ["Retrieval (P@5 / R@5 / MRR)", _fmt(scores.get("retrieval"))],
        ["Token savings", _fmt(scores.get("token_savings"))],
        ["Capture quality (action accuracy)", _fmt(scores.get("capture_quality"))],
        ["Security / scope", _fmt(scores.get("security_scope"))],
        ["Final answer (judge required)", _fmt(scores.get("final_answer"))],
        ["Weighted partial", _fmt(scores.get("weighted_partial"))],
    ]))
    add("")
    if scores.get("note"):
        add(f"> {scores['note']}")
        add("")

    # ---- retrieval ----
    for key, title in (("retrieval", "Retrieval (base)"),
                       ("adversarial", "Adversarial retrieval (stress)")):
        section = metrics.get(key)
        add(f"## {title}")
        add("")
        if not section:
            add("_Phase not run._")
            add("")
            continue
        add(_table(["Metric", "Value"], [
            ["cases", section["cases"]],
            ["precision@5 (lenient)", _fmt(section.get("precision_at_5"))],
            ["precision@5 (strict /k)", _fmt(section.get("precision_at_5_strict"))],
            ["recall@5", _fmt(section.get("recall_at_5"))],
            ["MRR", _fmt(section.get("mrr"))],
            ["forbidden_hit_rate", _fmt(section.get("forbidden_hit_rate"), pct=True)],
            ["scope_leak_rate", _fmt(section.get("scope_leak_rate"), pct=True)],
            ["cases below min_recall_at_5", section.get("recall_min_failures", 0)],
            ["latency p50 (ms)", _fmt(section.get("latency_p50_ms"))],
            ["latency p95 (ms)", _fmt(section.get("latency_p95_ms"))],
        ]))
        add("")

    # ---- capture ----
    add("## Capture")
    add("")
    cap = metrics.get("capture")
    if cap:
        add(_table(["Metric", "Value"], [
            ["cases", cap["cases"]],
            ["action_accuracy", _fmt(cap.get("action_accuracy"), pct=True)],
            ["mismatched cases", ", ".join(cap.get("mismatches", [])) or "none"],
            ["no action returned", ", ".join(cap.get("no_action_returned", [])) or "none"],
            ["secret pattern hits", cap.get("secret_pattern_hits", 0)],
        ]))
    else:
        add("_Phase not run._")
    add("")

    # ---- workflows ----
    add("## Workflows (baseline vs data-kb)")
    add("")
    wf = metrics.get("workflows")
    if wf:
        add(_table(["Metric", "Value"], [
            ["cases", wf["cases"]],
            ["pending generation", wf.get("pending_generation", 0)],
            ["avg token savings", _fmt(wf.get("avg_token_savings_pct")) + (" %" if wf.get("avg_token_savings_pct") is not None else "")],
            ["avg facts-coverage delta (data-kb − baseline)", _fmt(wf.get("avg_facts_coverage_delta"))],
            ["token counts estimated", _fmt(wf.get("tokens_estimated"))],
        ]))
        if wf.get("pending_generation"):
            add("")
            add("> Some workflows are pending: no `[commands.generate]` was "
                "configured, so prompts were written to `workflow_prompts/` "
                "for manual or AI-assisted execution.")
    else:
        add("_Phase not run._")
    add("")

    # ---- longitudinal / abuse ----
    add("## Longitudinal memory (stress)")
    add("")
    lon = metrics.get("longitudinal")
    if lon:
        add(_table(["Metric", "Value"], [
            ["cases", lon["cases"]],
            ["turn action accuracy", _fmt(lon.get("turn_action_accuracy"), pct=True)],
            ["secret/temporary pattern violations", lon.get("pattern_violations", 0)],
        ]))
    else:
        add("_Phase not run._")
    add("")

    add("## Capture abuse / security (stress)")
    add("")
    ab = metrics.get("capture_abuse")
    if ab:
        add(_table(["Metric", "Value"], [
            ["cases", ab["cases"]],
            ["action accuracy", _fmt(ab.get("action_accuracy"), pct=True)],
            ["pattern violations", ab.get("pattern_violations", 0)],
            ["critical violations", ab.get("critical_violations", 0)],
        ]))
    else:
        add("_Phase not run._")
    add("")

    # ---- scale ----
    add("## Scale / degradation")
    add("")
    scale = metrics.get("scale")
    if scale:
        add(_table(
            ["corpus size", "P@5", "R@5", "MRR", "p50 ms", "p95 ms", "forbidden rate"],
            [[s.get("corpus_size"), _fmt(s.get("precision_at_5")),
              _fmt(s.get("recall_at_5")), _fmt(s.get("mrr")),
              _fmt(s.get("latency_p50_ms")), _fmt(s.get("latency_p95_ms")),
              _fmt(s.get("forbidden_hit_rate"), pct=True)] for s in scale]))
    else:
        add("_Phase not run. Generate corpora with "
            "`python tools/generate_scale_corpus.py` first._")
    add("")

    # ---- review queue ----
    review = metrics.get("needs_human_review", [])
    add("## Needs human review")
    add("")
    add(f"{len(review)} item(s) flagged. Review per `templates/judge_rubric.md`: "
        "100% of secret/leak cases, 100% of low scores, 20% random sample of passes.")
    add("")
    if review:
        add(_table(["Phase", "Case", "Reasons"],
                   [[r["phase"], r.get("case_id", "?"), "; ".join(map(str, r.get("reasons", [])))]
                    for r in review[:60]]))
        if len(review) > 60:
            add(f"\n_...and {len(review) - 60} more (see metrics.json)._")
    add("")

    add("## Notes")
    add("")
    add("- precision@5 (lenient) divides by `min(5, returned)`; the strict "
        "variant divides by 5 and is structurally capped low because most "
        "cases expect only 1-2 memories. Thresholds apply to the lenient one.")
    add("- Token counts flagged as estimated use a ~4 chars/token heuristic; "
        "prefer real usage from your LLM provider when wiring `generate`.")
    add("- Judge-dependent gates (prompt injection obedience, deprecated-as-current, "
        "unanswerable invention) stay `needs_review` until a human/LLM judge "
        "fills them in; deterministic evidence is in the per-case JSONL files.")
    add("")

    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# results.csv — matches templates/results_template.csv
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "run_id", "case_id", "mode", "storage_backend", "scope", "namespace",
    "input_tokens", "output_tokens", "tool_tokens", "latency_ms",
    "retrieved_memory_ids", "expected_memory_ids", "forbidden_memory_ids",
    "saved_memory_ids", "final_answer", "judge_score", "judge_notes",
]


def write_results_csv(out_dir: Path, run_id: str, backend: str) -> Path:
    out_dir = Path(out_dir)

    def rows_from(path: Path, mode: str):
        if not path.exists():
            return
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            yield {
                "run_id": run_id,
                "case_id": r.get("case_id", ""),
                "mode": r.get("mode", mode),
                "storage_backend": backend,
                "scope": r.get("scope", ""),
                "namespace": r.get("namespace", ""),
                "input_tokens": r.get("input_tokens", "not_available"),
                "output_tokens": r.get("output_tokens", "not_available"),
                "tool_tokens": r.get("tool_tokens", "not_available"),
                "latency_ms": r.get("latency_ms", "not_available"),
                "retrieved_memory_ids": ";".join(r.get("retrieved_memory_ids", [])),
                "expected_memory_ids": ";".join(r.get("expected_memory_ids", [])),
                "forbidden_memory_ids": ";".join(r.get("forbidden_memory_ids", [])),
                "saved_memory_ids": ";".join(r.get("saved_memory_ids", [])),
                "final_answer": (r.get("final_answer") or "")[:500],
                "judge_score": "",  # filled by the judge
                "judge_notes": "needs_human_review" if r.get("needs_human_review") else "",
            }

    csv_path = out_dir / "results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for path, mode in [
            (out_dir / "retrieval_results.jsonl", "data-kb"),
            (out_dir / "workflow_results.jsonl", ""),
            (out_dir / "capture_results.jsonl", "data-kb"),
            (out_dir / "adversarial_results.jsonl", "data-kb"),
            (out_dir / "capture_abuse_results.jsonl", "data-kb"),
        ]:
            for row in rows_from(path, mode) or []:
                writer.writerow(row)
    return csv_path
