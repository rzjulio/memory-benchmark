#!/usr/bin/env python3
"""Generate synthetic noise corpora for the scale/degradation phase.

Builds corpora of N memories following the noise mix defined in
data-kb-benchmark-kit/stress/scale_test_plan.json. The 30 real seed
memories are ALWAYS included (the retrieval cases target their IDs), and
the remaining slots are filled per the mix. Deterministic given --seed.

Usage:
    python tools/generate_scale_corpus.py --sizes 100,1000,10000 --out-dir corpora
    python runner.py --adapter command --phases scale --scale-sizes 100,1000
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent / "data-kb-benchmark-kit"

TOPICS = ["architecture", "storage", "testing", "retrieval", "security",
          "quality", "viewer", "commands", "performance", "eval", "release"]
TOOLS = ["data-api", "data-sync", "kb-lite", "memcache-pro", "vector-hub",
         "doc-indexer", "log-miner", "task-queue", "report-gen"]
TECH = ["FastAPI", "Redis", "Celery", "GraphQL", "Kafka", "React", "gRPC",
        "Elasticsearch", "RabbitMQ", "Terraform", "Kubernetes"]
DATAKB_TERMS = ["viewer", "recall", "memory", "SQLite", "PostgreSQL", "scope",
                "namespace", "benchmark", "retrieval", "capture", "MCP", "CLI"]
WRONG_OWNERS = ["project://other-tool", "project://legacy-app",
                "user://other-user", "team://security", "team://frontend"]
GENERIC = ["The quarterly planning doc was moved to the shared drive.",
           "Standup meetings start five minutes later on Fridays.",
           "The office coffee machine requires a maintenance ticket.",
           "Conference talk proposals are due at the end of the month.",
           "The onboarding checklist has twelve steps in total."]


def load_seeds() -> list[dict]:
    path = KIT / "seeds" / "memories.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def make_filler(kind: str, i: int, rng: random.Random, seeds: list[dict]) -> dict:
    topic = rng.choice(TOPICS)
    if kind == "near_duplicate":
        src = rng.choice(seeds)
        words = src["content"].split()
        if len(words) > 6:  # light shuffle in the middle to stay "near"
            a, b = sorted(rng.sample(range(1, len(words) - 1), 2))
            words[a], words[b] = words[b], words[a]
        content = " ".join(words) + " (see also the project notes)."
        ns, scope, status = src["namespace"], src["scope"], "active"
        prefix = "DUP"
    elif kind == "semantic_distractor":
        content = (f"The {rng.choice(TOOLS)} tool uses {rng.choice(TECH)} for its "
                   f"{rng.choice(DATAKB_TERMS)} layer and a separate "
                   f"{rng.choice(DATAKB_TERMS)} pipeline.")
        ns, scope, status = f"project://data-kb/{topic}", "project", "active"
        prefix = "DIS"
    elif kind == "same_namespace_irrelevant":
        content = rng.choice(GENERIC)
        ns, scope, status = f"project://data-kb/{topic}", "project", "active"
        prefix = "IRR"
    elif kind == "wrong_scope":
        owner = rng.choice(WRONG_OWNERS)
        content = (f"{owner.split('//')[1]} relies on {rng.choice(TECH)} and keeps "
                   f"its {rng.choice(DATAKB_TERMS)} configuration in a private repo.")
        ns = f"{owner}/{topic}"
        scope = owner.split(":")[0]
        status = "active"
        prefix = "WSC"
    elif kind == "obsolete_or_temporary":
        status = rng.choice(["deprecated", "temporary", "speculative"])
        content = (f"({status}) An earlier plan suggested moving the "
                   f"{rng.choice(DATAKB_TERMS)} component to {rng.choice(TECH)}; "
                   f"this is no longer the current decision.")
        ns, scope = f"project://data-kb/{topic}", "project"
        prefix = "OBS"
    else:  # random_irrelevant
        content = rng.choice(GENERIC) + f" (note {i})"
        ns, scope, status = "project://misc/notes", "project", "active"
        prefix = "RND"
    return {"memory_id": f"{prefix}{i:06d}", "scope": scope, "namespace": ns,
            "content": content, "tags": ["synthetic", kind], "status": status}


def generate(size: int, mix: dict[str, float], rng: random.Random) -> list[dict]:
    seeds = load_seeds()
    corpus = list(seeds)
    fill = max(0, size - len(seeds))
    kinds = [k for k in mix if k != "exact_relevant"]  # seeds cover relevance
    weights = [mix[k] for k in kinds]
    total_w = sum(weights)
    counts = {k: round(fill * w / total_w) for k, w in zip(kinds, weights)}
    # fix rounding drift
    drift = fill - sum(counts.values())
    counts[kinds[0]] += drift
    i = 0
    for kind, n in counts.items():
        for _ in range(max(0, n)):
            i += 1
            corpus.append(make_filler(kind, i, rng, seeds))
    rng.shuffle(corpus)
    return corpus


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", default="100,1000",
                    help="comma list, e.g. 100,1000,10000,50000")
    ap.add_argument("--out-dir", default="corpora")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    plan = json.loads((KIT / "stress" / "scale_test_plan.json").read_text())
    mix = plan["noise_mix"]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)
    for size in [int(s) for s in args.sizes.split(",") if s.strip()]:
        rng = random.Random(args.seed + size)  # deterministic per size
        corpus = generate(size, mix, rng)
        path = out_dir / f"corpus_{size}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for mem in corpus:
                fh.write(json.dumps(mem, ensure_ascii=False) + "\n")
        print(f"{path}: {len(corpus)} memories (seeds included)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
