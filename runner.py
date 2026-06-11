#!/usr/bin/env python3
"""data-kb benchmark runner.

Orchestrates the phases described in data-kb-benchmark-kit/EXECUTION_GUIDE.md
against any memory tool wired through adapters.py.

Quick demo (no data-kb needed, validates the whole pipeline):

    python runner.py --demo

Real run (after filling [commands.*] in benchmark_config.toml):

    python runner.py --adapter command --phases all

See INTEGRATION.md for everything you must configure for a real run.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
import traceback
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("Python 3.11+ is required (data-kb itself targets 3.11+).")

import tomllib

import adapters
import reporter
import scorer
from adapters import AdapterError, OperationNotConfigured, estimate_tokens

PHASE_ORDER = [
    "smoke", "seed", "retrieval", "workflows", "capture",
    "adversarial", "capture_abuse", "longitudinal", "scale", "score",
]
DEFAULT_PHASES = [p for p in PHASE_ORDER if p != "scale"]  # scale needs corpora


# ---------------------------------------------------------------------------
# Kit loading
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class Kit:
    def __init__(self, kit_dir: Path):
        self.dir = Path(kit_dir)
        self.seeds = _read_jsonl(self.dir / "seeds/memories.jsonl")
        self.retrieval = _read_jsonl(self.dir / "cases/retrieval_cases.jsonl")
        self.workflows = _read_jsonl(self.dir / "cases/workflow_cases.jsonl")
        self.capture = _read_jsonl(self.dir / "cases/capture_cases.jsonl")
        self.noise = _read_jsonl(self.dir / "stress/noise_memories.jsonl")
        self.adversarial = _read_jsonl(self.dir / "stress/adversarial_retrieval_cases.jsonl")
        self.longitudinal = _read_jsonl(self.dir / "stress/longitudinal_memory_cases.jsonl")
        self.capture_abuse = _read_jsonl(self.dir / "stress/capture_abuse_cases.jsonl")
        self.scale_plan = json.loads((self.dir / "stress/scale_test_plan.json").read_text())
        self.index = scorer.build_corpus_index(self.seeds, self.noise)
        self.seeds_by_id = {m["memory_id"]: m for m in self.seeds}

    def checksums(self) -> dict[str, str]:
        out = {}
        for path in sorted(self.dir.rglob("*.jsonl")) + [self.dir / "stress/scale_test_plan.json"]:
            out[str(path.relative_to(self.dir))] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        return out


# ---------------------------------------------------------------------------
# Run context
# ---------------------------------------------------------------------------

class Run:
    def __init__(self, cfg: dict, adapter, kit: Kit, out_dir: Path, run_id: str):
        self.cfg = cfg
        self.adapter = adapter
        self.kit = kit
        self.out = out_dir
        self.run_id = run_id
        self.corpus_state = "unknown"   # unknown | seeds | seeds+noise | dirty
        self.id_map: dict[str, str] = {}  # tool id -> original kit id
        self.summaries: dict[str, dict] = {}
        self.security_patterns = list(
            cfg.get("security", {}).get("secret_patterns", []))

    # -- helpers ------------------------------------------------------------

    def log(self, msg: str):
        print(f"  {msg}")

    def write_jsonl(self, name: str, rows: list[dict]):
        path = self.out / name
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.log(f"wrote {path} ({len(rows)} rows)")

    def map_ids(self, ids: list[str]) -> list[str]:
        """Translate tool-assigned ids back to kit ids when they differ."""
        return [self.id_map.get(i, i) for i in ids]

    def _import_all(self, memories: list[dict], evidence: list[dict]):
        skip_dnp = self.cfg.get("policy", {}).get("import_do_not_persist", "send") == "skip"
        for mem in memories:
            if skip_dnp and mem.get("status") == "do_not_persist":
                evidence.append({"memory_id": mem["memory_id"], "ok": False,
                                 "skipped": True, "note": "skipped by runner policy"})
                continue
            res = self.adapter.import_memory(mem)
            if res.get("id") and res["id"] != mem["memory_id"]:
                self.id_map[res["id"]] = mem["memory_id"]
            evidence.append({"memory_id": mem["memory_id"], **res})

    def ensure_corpus(self, want: str) -> list[dict]:
        """Guarantee a deterministic corpus state ('seeds' or 'seeds+noise')."""
        if self.corpus_state == want:
            return []
        self.adapter.reset()
        self.id_map = {}
        evidence: list[dict] = []
        self._import_all(self.kit.seeds, evidence)
        if want == "seeds+noise":
            self._import_all(self.kit.noise, evidence)
        self.corpus_state = want
        return evidence


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

def phase_smoke(run: Run) -> dict:
    """Reset -> import one memory -> recall it. Fails fast if wiring is broken."""
    run.adapter.reset()
    run.corpus_state = "dirty"
    probe = run.kit.seeds[0]
    imp = run.adapter.import_memory(probe)
    rec = run.adapter.recall(probe["content"], probe["scope"], probe["namespace"], 10)
    ids = run.map_ids(rec["ids"])
    if imp.get("id") and imp["id"] != probe["memory_id"]:
        ids = [probe["memory_id"] if i == imp["id"] else i for i in ids]
    ok = probe["memory_id"] in ids or (imp.get("id") in rec["ids"] if imp.get("id") else False)
    result = {"ok": ok, "imported": imp, "recalled_ids": rec["ids"],
              "latency_ms": rec["latency_ms"]}
    (run.out / "smoke.json").write_text(json.dumps(result, indent=2))
    if not ok:
        raise AdapterError(
            "smoke test failed: imported memory was not recalled. Check the "
            "[commands.import]/[commands.recall] wiring and response paths "
            "before running the full benchmark.")
    run.log("smoke test passed")
    return result


def phase_seed(run: Run) -> dict:
    run.corpus_state = "unknown"
    evidence = run.ensure_corpus("seeds")
    run.write_jsonl("seed_import.jsonl", evidence)
    (run.out / "id_map.json").write_text(json.dumps(run.id_map, indent=2))
    imported = sum(1 for e in evidence if e.get("ok"))
    skipped = sum(1 for e in evidence if e.get("skipped"))
    return {"imported": imported, "skipped": skipped, "total": len(evidence)}


def _run_retrieval_cases(run: Run, cases: list[dict], top_k: int) -> list[dict]:
    rows = []
    for case in cases:
        rec = run.adapter.recall(case["query"], case["scope"], case["namespace"], top_k)
        retrieved = run.map_ids(rec["ids"])
        row = {
            "case_id": case["case_id"], "type": case.get("type"),
            "scope": case["scope"], "namespace": case["namespace"],
            "query": case["query"],
            "expected_memory_ids": case.get("expected_memory_ids", []),
            "forbidden_memory_ids": case.get("forbidden_memory_ids", []),
            "retrieved_memory_ids": retrieved,
            "latency_ms": rec["latency_ms"],
        }
        row.update(scorer.score_retrieval_case(case, retrieved, run.kit.index))
        if "expected_behavior" in case:
            row["expected_behavior"] = case["expected_behavior"]
            row["failure_modes"] = case.get("failure_modes", [])
        rows.append(row)
    return rows


def phase_retrieval(run: Run) -> dict:
    run.ensure_corpus("seeds")
    top_k = run.cfg.get("run", {}).get("top_k", 10)
    rows = _run_retrieval_cases(run, run.kit.retrieval, top_k)
    run.write_jsonl("retrieval_results.jsonl", rows)
    return {"cases": len(rows),
            "recall_at_5": scorer.mean([r["recall_at_5"] for r in rows]),
            "flagged": sum(1 for r in rows if r["needs_human_review"])}


def phase_adversarial(run: Run) -> dict:
    evidence = run.ensure_corpus("seeds+noise")
    if evidence:
        run.write_jsonl("noise_import.jsonl",
                        [e for e in evidence if e["memory_id"].startswith("N")])
    top_k = run.cfg.get("run", {}).get("top_k", 10)
    rows = _run_retrieval_cases(run, run.kit.adversarial, top_k)
    run.write_jsonl("adversarial_results.jsonl", rows)
    return {"cases": len(rows),
            "flagged": sum(1 for r in rows if r["needs_human_review"])}


def phase_workflows(run: Run) -> dict:
    run.ensure_corpus("seeds")
    wf_cfg = run.cfg.get("workflows", {})
    scope = wf_cfg.get("scope", "project")
    namespace = wf_cfg.get("namespace", "project://data-kb")
    top_k = wf_cfg.get("top_k", 5)
    can_generate = run.adapter.available("generate")
    prompts_dir = run.out / "workflow_prompts"
    rows, pending = [], 0

    for case in run.kit.workflows:
        prompt = case["prompt"]
        facts = case.get("expected_facts", [])

        # --- baseline: paste the listed memories manually ---
        baseline_blocks = [run.kit.seeds_by_id[i]["content"]
                           for i in case["baseline_context_memory_ids"]
                           if i in run.kit.seeds_by_id]
        # --- data-kb: context comes from recall only ---
        rec = run.adapter.recall(prompt, scope, namespace, top_k)
        retrieved = run.map_ids(rec["ids"])
        dk_blocks = [run.kit.seeds_by_id[i]["content"] for i in retrieved
                     if i in run.kit.seeds_by_id]
        tool_tokens = estimate_tokens(json.dumps({"query": prompt, "ids": retrieved}))

        for mode, blocks in (("baseline", baseline_blocks), ("data-kb", dk_blocks)):
            row = {
                "case_id": case["case_id"], "mode": mode, "title": case["title"],
                "scope": scope, "namespace": namespace,
                "retrieved_memory_ids": retrieved if mode == "data-kb" else [],
                "expected_memory_ids": case["baseline_context_memory_ids"] if mode == "baseline" else [],
                "context_blocks": len(blocks),
                "tool_tokens": tool_tokens if mode == "data-kb" else 0,
            }
            if can_generate:
                gen = run.adapter.generate(prompt, blocks)
                answer = gen.get("answer", "")
                cov = scorer.facts_coverage(facts, answer)
                estimated = gen.get("input_tokens") is None
                row.update({
                    "status": "completed",
                    "final_answer": answer,
                    "input_tokens": gen.get("input_tokens")
                        or estimate_tokens(prompt + "\n".join(blocks)),
                    "output_tokens": gen.get("output_tokens") or estimate_tokens(answer),
                    "latency_ms": gen.get("latency_ms"),
                    "tokens_estimated": estimated,
                    "facts_coverage": cov["coverage"],
                    "facts_missing": cov["missing"],
                    "needs_human_review": True,
                    "review_reasons": ["judge final answer quality (rubric)"],
                })
            else:
                # no generate command: write the prompt out for manual/AI run
                prompts_dir.mkdir(exist_ok=True)
                text = prompt + "\n\n--- CONTEXT ---\n" + "\n".join(f"- {b}" for b in blocks)
                (prompts_dir / f"{case['case_id']}.{mode}.txt").write_text(text, encoding="utf-8")
                row.update({"status": "pending_generation",
                            "input_tokens": None, "output_tokens": None,
                            "needs_human_review": True,
                            "review_reasons": ["run prompt manually (no [commands.generate])"]})
                pending += 1
            rows.append(row)

    run.write_jsonl("workflow_results.jsonl", rows)
    summary = {"cases": len(run.kit.workflows), "pending_rows": pending}
    if pending:
        run.log(f"NOTE: no [commands.generate] configured -> prompts saved in {prompts_dir}")
    return summary


def _capture_case(run: Run, case_id: str, text: str, expected: str,
                  scope: str, namespace: str, patterns: list[str],
                  severity: str | None = None) -> dict:
    synonyms = run.cfg.get("action_synonyms", {})
    extra_equiv = run.cfg.get("action_equivalences", {})
    res = run.adapter.capture(text, scope, namespace)
    atomic = scorer.normalize_action(res.get("action"), synonyms)
    matched, ambiguous = scorer.action_match(expected, atomic, extra_equiv)

    # scan persisted memories for forbidden patterns (per-case + secret-shaped)
    exported = run.adapter.export_memories()
    new = [m for m in exported if m["id"] in set(res.get("saved_ids", []))] or exported
    violations = scorer.scan_patterns(new, list(dict.fromkeys(
        list(patterns or []) + scorer.extract_secret_tokens(text))))

    reasons = []
    if matched is False:
        reasons.append(f"action mismatch: expected '{expected}', got '{atomic}'")
    if matched is None:
        reasons.append("tool returned no action")
    if ambiguous:
        reasons.append("ambiguous action vocabulary; verify manually")
    if violations:
        reasons.append(f"forbidden pattern persisted: {[v['pattern'] for v in violations]}")
    return {
        "case_id": case_id, "input": text, "scope": scope, "namespace": namespace,
        "expected_action": expected, "returned_action": res.get("action"),
        "returned_action_atomic": atomic, "action_match": matched,
        "saved_memory_ids": res.get("saved_ids", []),
        "latency_ms": res.get("latency_ms"),
        "pattern_violations": violations, "severity": severity,
        "needs_human_review": bool(reasons), "review_reasons": reasons,
    }


def phase_capture(run: Run) -> dict:
    run.ensure_corpus("seeds")
    run.corpus_state = "dirty"  # capture mutates the store
    rows = []
    for case in run.kit.capture:
        rows.append(_capture_case(
            run, case["case_id"], case["input"], case["expected_action"],
            case.get("expected_scope") or "project",
            case.get("expected_namespace") or "project://data-kb/misc",
            patterns=[],
        ))
    run.write_jsonl("capture_results.jsonl", rows)
    matched = sum(1 for r in rows if r["action_match"] is True)
    return {"cases": len(rows), "action_accuracy": matched / len(rows) if rows else None}


def phase_capture_abuse(run: Run) -> dict:
    run.ensure_corpus("seeds")
    run.corpus_state = "dirty"
    rows = []
    for case in run.kit.capture_abuse:
        rows.append(_capture_case(
            run, case["case_id"], case["input"], case["expected_action"],
            "project", "project://data-kb/misc",
            patterns=case.get("must_not_save_patterns", []),
            severity=case.get("severity"),
        ))
    run.write_jsonl("capture_abuse_results.jsonl", rows)
    violations = sum(len(r["pattern_violations"]) for r in rows)
    return {"cases": len(rows), "pattern_violations": violations}


def phase_longitudinal(run: Run) -> dict:
    synonyms = run.cfg.get("action_synonyms", {})
    extra_equiv = run.cfg.get("action_equivalences", {})
    reset_per_case = run.cfg.get("longitudinal", {}).get("reset_per_case", True)
    top_k = run.cfg.get("run", {}).get("top_k", 10)
    rows = []
    for case in run.kit.longitudinal:
        if reset_per_case:
            run.adapter.reset()
            run.corpus_state = "dirty"
        turns_out, matches, patterns = [], [], []
        final_recall = None
        for turn in case["turns"]:
            text = turn["input"]
            patterns.extend(scorer.extract_secret_tokens(text))
            if "expected_capture" in turn:
                res = run.adapter.capture(text, case["scope"], case["namespace"])
                atomic = scorer.normalize_action(res.get("action"), synonyms)
                matched, _ = scorer.action_match(turn["expected_capture"], atomic, extra_equiv)
                matches.append(bool(matched))
                turns_out.append({"turn": turn["turn"], "input": text,
                                  "expected_capture": turn["expected_capture"],
                                  "returned_action": res.get("action"),
                                  "action_match": matched})
            else:  # final probe turn
                rec = run.adapter.recall(text, case["scope"], case["namespace"], top_k)
                exported = {m["id"]: m for m in run.adapter.export_memories()}
                final_recall = {
                    "turn": turn["turn"], "query": text,
                    "expected_retrieval": turn.get("expected_retrieval"),
                    "retrieved_memory_ids": rec["ids"],
                    "retrieved_contents": [exported[i]["content"]
                                           for i in rec["ids"] if i in exported],
                }
                turns_out.append(final_recall)
        violations = scorer.scan_patterns(run.adapter.export_memories(),
                                          list(dict.fromkeys(patterns)))
        rows.append({
            "case_id": case["case_id"], "title": case["title"],
            "scope": case["scope"], "namespace": case["namespace"],
            "turns": turns_out,
            "turn_action_accuracy": (sum(matches) / len(matches)) if matches else None,
            "expected_final_behavior": case.get("expected_final_behavior"),
            "pattern_violations": violations,
            "needs_human_review": True,
            "review_reasons": (["secret persisted across turns"] if violations else [])
                + ["verify final-turn behavior against expected_final_behavior"],
        })
    run.write_jsonl("longitudinal_results.jsonl", rows)
    return {"cases": len(rows),
            "violations": sum(len(r["pattern_violations"]) for r in rows)}


def phase_scale(run: Run, corpus_dir: Path, sizes: list[int]) -> dict:
    plan = run.kit.scale_plan
    reps = plan.get("query_repetitions_per_size", 3)
    top_k = run.cfg.get("run", {}).get("top_k", 10)
    rows = []
    for size in sizes:
        corpus_path = corpus_dir / f"corpus_{size}.jsonl"
        if not corpus_path.exists():
            run.log(f"SKIP size {size}: {corpus_path} not found "
                    f"(generate it with tools/generate_scale_corpus.py)")
            continue
        corpus = _read_jsonl(corpus_path)
        run.adapter.reset()
        run.id_map = {}
        run.corpus_state = "dirty"
        evidence: list[dict] = []
        run._import_all(corpus, evidence)
        index = scorer.build_corpus_index(corpus)
        latencies, per_case = [], []
        for _ in range(reps):
            for case in run.kit.retrieval:
                rec = run.adapter.recall(case["query"], case["scope"],
                                         case["namespace"], top_k)
                latencies.append(rec["latency_ms"])
                per_case.append(scorer.score_retrieval_case(
                    case, run.map_ids(rec["ids"]), index))
        rows.append({
            "corpus_size": size, "imported": sum(1 for e in evidence if e.get("ok")),
            "queries": len(per_case),
            "precision_at_5": scorer.mean([c["precision_at_5"] for c in per_case]),
            "recall_at_5": scorer.mean([c["recall_at_5"] for c in per_case]),
            "mrr": scorer.mean([c["mrr"] for c in per_case]),
            "forbidden_hit_rate": sum(1 for c in per_case if c["forbidden_hits"]) / len(per_case),
            "scope_leak_rate": sum(1 for c in per_case if c["scope_leaks"]) / len(per_case),
            "latency_p50_ms": scorer.percentile(latencies, 50),
            "latency_p95_ms": scorer.percentile(latencies, 95),
        })
        run.log(f"scale {size}: p95={rows[-1]['latency_p95_ms']:.1f}ms "
                f"R@5={rows[-1]['recall_at_5']:.2f}" if rows[-1]['recall_at_5'] is not None else f"scale {size} done")
    run.write_jsonl("scale_results.jsonl", rows)
    return {"sizes_run": [r["corpus_size"] for r in rows]}


def phase_score(run: Run) -> dict:
    thresholds = run.cfg.get("thresholds", {})
    meta = {
        "run_id": run.run_id,
        "adapter": getattr(run.adapter, "name", "command"),
        "kit_dir": str(run.kit.dir),
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    metrics = scorer.aggregate(run.out, thresholds, meta)
    (run.out / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False))
    report_path = reporter.write_report(metrics, run.out)
    backend = run.cfg.get("vars", {}).get("backend", "mock" if meta["adapter"] == "mock" else "unknown")
    reporter.write_results_csv(run.out, run.run_id, backend)
    run.log(f"metrics.json + report.md + results.csv written")
    return {"verdict": metrics["verdict"],
            "weighted_partial": metrics["scores"].get("weighted_partial"),
            "report": str(report_path)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def next_run_id(out_root: Path, prefix: str | None = None) -> str:
    date = _dt.date.today().isoformat()
    base = f"{prefix + '-' if prefix else ''}{date}-run"
    existing = [p.name for p in out_root.glob(f"{base}-*") if p.is_dir()]
    nums = [int(name.rsplit("-", 1)[-1]) for name in existing
            if name.rsplit("-", 1)[-1].isdigit()]
    return f"{base}-{(max(nums) + 1) if nums else 1:03d}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="benchmark_config.toml")
    ap.add_argument("--adapter", choices=["mock", "command"],
                    help="override [run].adapter from the config")
    ap.add_argument("--phases", default=None,
                    help=f"comma list or 'all'. Order: {','.join(PHASE_ORDER)}")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--kit-dir", default=None)
    ap.add_argument("--scale-sizes", default=None,
                    help="comma list of corpus sizes for the scale phase, e.g. 100,1000")
    ap.add_argument("--corpus-dir", default="corpora")
    ap.add_argument("--demo", action="store_true",
                    help="mock adapter + all runnable phases (pipeline validation)")
    ap.add_argument("--list-phases", action="store_true")
    args = ap.parse_args(argv)

    if args.list_phases:
        print("\n".join(PHASE_ORDER))
        return 0

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        sys.exit(f"config not found: {cfg_path} (copy/edit benchmark_config.toml)")
    cfg = tomllib.loads(cfg_path.read_text())

    adapter_name = args.adapter or ("mock" if args.demo else cfg.get("run", {}).get("adapter", "mock"))
    kit_dir = Path(args.kit_dir or cfg.get("run", {}).get("kit_dir", "data-kb-benchmark-kit"))
    out_root = Path(cfg.get("run", {}).get("out_dir", "runs"))
    out_root.mkdir(exist_ok=True)

    if args.phases:
        phases = PHASE_ORDER if args.phases == "all" else [
            p.strip() for p in args.phases.split(",") if p.strip()]
        unknown = [p for p in phases if p not in PHASE_ORDER]
        if unknown:
            sys.exit(f"unknown phase(s): {unknown}; valid: {PHASE_ORDER}")
        phases = [p for p in PHASE_ORDER if p in phases]  # canonical order
    else:
        phases = DEFAULT_PHASES

    run_id = args.run_id or next_run_id(out_root, "demo" if args.demo else None)
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    kit = Kit(kit_dir)
    try:
        adapter = adapters.build_adapter(adapter_name, cfg)
    except AdapterError as e:
        sys.exit(f"error: {e}")
    run = Run(cfg, adapter, kit, out_dir, run_id)

    # reproducibility evidence
    (out_dir / "run_config.json").write_text(json.dumps({
        "run_id": run_id, "adapter": adapter_name, "phases": phases,
        "config_file": str(cfg_path), "config": cfg,
        "kit_dir": str(kit_dir), "dataset_sha256": kit.checksums(),
        "python": sys.version.split()[0],
        "started_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }, indent=2))

    print(f"run: {run_id}  adapter: {adapter_name}  phases: {','.join(phases)}")
    failures = 0
    for phase in phases:
        print(f"[{phase}]")
        try:
            if phase == "smoke":
                run.summaries[phase] = phase_smoke(run)
            elif phase == "seed":
                run.summaries[phase] = phase_seed(run)
            elif phase == "retrieval":
                run.summaries[phase] = phase_retrieval(run)
            elif phase == "workflows":
                run.summaries[phase] = phase_workflows(run)
            elif phase == "capture":
                run.summaries[phase] = phase_capture(run)
            elif phase == "adversarial":
                run.summaries[phase] = phase_adversarial(run)
            elif phase == "capture_abuse":
                run.summaries[phase] = phase_capture_abuse(run)
            elif phase == "longitudinal":
                run.summaries[phase] = phase_longitudinal(run)
            elif phase == "scale":
                sizes = [int(s) for s in (args.scale_sizes or "").split(",") if s.strip()] \
                    or kit.scale_plan.get("memory_sizes", [])
                run.summaries[phase] = phase_scale(run, Path(args.corpus_dir), sizes)
            elif phase == "score":
                run.summaries[phase] = phase_score(run)
        except OperationNotConfigured as e:
            failures += 1
            run.summaries[phase] = {"error": str(e)}
            print(f"  SKIPPED: {e}")
        except AdapterError as e:
            failures += 1
            run.summaries[phase] = {"error": str(e)}
            print(f"  FAILED: {e}")
            if phase in ("smoke", "seed"):
                print("  aborting: later phases depend on this one.")
                break
        except Exception as e:  # keep evidence, don't lose the run
            failures += 1
            run.summaries[phase] = {"error": f"{type(e).__name__}: {e}"}
            traceback.print_exc()

    (out_dir / "phase_summaries.json").write_text(
        json.dumps(run.summaries, indent=2, ensure_ascii=False))
    print(f"\ndone -> {out_dir}")
    if "score" in run.summaries and "report" in run.summaries["score"]:
        print(f"report: {run.summaries['score']['report']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
