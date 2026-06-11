"""Adapters that connect the benchmark runner to a memory tool.

Two adapters are provided:

- CommandAdapter: wraps the real data-kb CLI using the command templates
  defined in benchmark_config.toml ([commands.*] sections). This is the
  one you configure for a real run. See INTEGRATION.md.
- MockAdapter: a self-contained in-process memory store, so the whole
  pipeline (runner -> scorer -> reporter) can be exercised end to end
  WITHOUT data-kb installed. Its results are illustrative only; it
  exists to validate the harness and to show example outputs.

Adapter contract (every adapter implements):

    reset() -> None
    import_memory(memory: dict) -> {"ok": bool, "id": str|None, "skipped": bool, "note": str}
    recall(query, scope, namespace, top_k) -> {"ids": [str], "latency_ms": float|None}
    capture(text, scope, namespace) -> {"action": str|None, "saved_ids": [str], "latency_ms": float|None}
    export_memories() -> [{"id", "content", "scope", "namespace", "status"}]
    generate(prompt, context_blocks) -> {"answer", "input_tokens", "output_tokens", "latency_ms"} | None
    available(op: str) -> bool
"""

from __future__ import annotations

import json
import re
import subprocess
import time


class AdapterError(RuntimeError):
    pass


class OperationNotConfigured(AdapterError):
    def __init__(self, op: str):
        super().__init__(
            f"operation '{op}' is not configured. Add a [commands.{op}] section "
            f"to benchmark_config.toml (see INTEGRATION.md)."
        )
        self.op = op


# ---------------------------------------------------------------------------
# Template helpers (shared by CommandAdapter)
# ---------------------------------------------------------------------------

_PLACEHOLDER_FULL = re.compile(r"^\{([\w.]+)(?::(int|float|json))?\}$")
_PLACEHOLDER_PART = re.compile(r"\{([\w.]+)\}")


def _resolve(ctx: dict, dotted: str):
    """Resolve a dotted path like 'memory.content' against a context dict."""
    cur = ctx
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise AdapterError(f"unknown placeholder '{{{dotted}}}' (context keys: {sorted(ctx)})")
    return cur


def substitute(value, ctx: dict):
    """Recursively substitute {placeholders} in strings/dicts/lists.

    A string that is EXACTLY one placeholder keeps the native type of the
    resolved value ('{memory}' -> the whole dict, '{top_k:int}' -> int).
    Placeholders embedded in longer strings are substituted as text.
    """
    if isinstance(value, str):
        m = _PLACEHOLDER_FULL.match(value)
        if m:
            resolved = _resolve(ctx, m.group(1))
            cast = m.group(2)
            if cast == "int":
                return int(resolved)
            if cast == "float":
                return float(resolved)
            if cast == "json":
                return json.dumps(resolved, ensure_ascii=False)
            return resolved
        return _PLACEHOLDER_PART.sub(lambda mm: str(_resolve(ctx, mm.group(1))), value)
    if isinstance(value, dict):
        return {k: substitute(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, ctx) for v in value]
    return value


def extract(obj, path: str | None):
    """Extract a value from parsed JSON using a simple dotted path.

    'memories[].id' means: for each element of obj['memories'], take ['id'].
    Returns None when the path does not resolve.
    """
    if path is None or path == "":
        return obj

    def walk(o, parts):
        if not parts:
            return o
        p = parts[0]
        if p.endswith("[]"):
            key = p[:-2]
            lst = o.get(key) if key else o
            if not isinstance(lst, list):
                return None
            out = []
            for item in lst:
                v = walk(item, parts[1:])
                if v is not None:
                    out.append(v)
            return out
        if isinstance(o, dict) and p in o:
            return walk(o[p], parts[1:])
        return None

    return walk(obj, path.split("."))


def _parse_json_output(stdout: str):
    """Parse the tool's stdout as JSON; tolerate log lines around it."""
    stdout = stdout.strip()
    if not stdout:
        raise AdapterError("command produced no output (expected JSON on stdout)")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass
    # Try line by line, last JSON object wins (tools often log before output).
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith(("{", "[")):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise AdapterError(f"could not parse JSON from command output: {stdout[:300]!r}")


# ---------------------------------------------------------------------------
# CommandAdapter: wraps the real data-kb CLI
# ---------------------------------------------------------------------------

class CommandAdapter:
    """Runs the operations through configurable shell commands.

    Each operation is described in benchmark_config.toml:

        [commands.recall]
        argv = ["data-kb", "tool", "--json", "{payload}"]
        timeout_s = 60
        [commands.recall.payload]      # optional: built and exposed as {payload}
        action = "recall"
        query = "{query}"
        scope = "{scope}"
        namespace = "{namespace}"
        top_k = "{top_k:int}"
        [commands.recall.response]     # how to read the JSON the tool prints
        ids = "memories[].id"
        latency_ms = "latency_ms"
    """

    def __init__(self, config: dict):
        self.commands = config.get("commands", {})
        self.vars = dict(config.get("vars", {}))
        if not self.commands:
            raise AdapterError(
                "adapter is 'command' but no [commands.*] sections are configured. "
                "Fill them in benchmark_config.toml (see INTEGRATION.md)."
            )

    def available(self, op: str) -> bool:
        return op in self.commands

    def _run(self, op: str, ctx: dict) -> tuple[dict | list, float]:
        cfg = self.commands.get(op)
        if cfg is None:
            raise OperationNotConfigured(op)
        full_ctx = {**self.vars, **ctx}
        if "payload" in cfg:
            payload_obj = substitute(cfg["payload"], full_ctx)
            full_ctx["payload"] = json.dumps(payload_obj, ensure_ascii=False)
        argv = [substitute(tok, full_ctx) for tok in cfg["argv"]]
        argv = [tok if isinstance(tok, str) else json.dumps(tok, ensure_ascii=False) for tok in argv]
        timeout = cfg.get("timeout_s", 120)
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, check=False
            )
        except FileNotFoundError as e:
            raise AdapterError(f"[commands.{op}] executable not found: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise AdapterError(f"[commands.{op}] timed out after {timeout}s") from e
        latency_ms = (time.perf_counter() - t0) * 1000.0
        if proc.returncode != 0:
            raise AdapterError(
                f"[commands.{op}] exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout)[:300]!r}"
            )
        if cfg.get("response", {}).get("format") == "none":
            return {}, latency_ms
        return _parse_json_output(proc.stdout), latency_ms

    def _resp(self, op: str, data, key: str, default=None):
        path = self.commands.get(op, {}).get("response", {}).get(key)
        if path is None:
            return default
        value = extract(data, path)
        return default if value is None else value

    # -- operations ---------------------------------------------------------

    def reset(self) -> None:
        self._run("reset", {})

    def import_memory(self, memory: dict) -> dict:
        ctx = {"memory": memory, "memory_json": json.dumps(memory, ensure_ascii=False)}
        data, _ = self._run("import", ctx)
        new_id = self._resp("import", data, "id")
        accepted = self._resp("import", data, "accepted", default=True)
        return {
            "ok": bool(accepted),
            "id": str(new_id) if new_id is not None else None,
            "skipped": not bool(accepted),
            "note": "",
        }

    def recall(self, query: str, scope: str, namespace: str, top_k: int) -> dict:
        ctx = {"query": query, "scope": scope, "namespace": namespace, "top_k": top_k}
        data, wall_ms = self._run("recall", ctx)
        ids = self._resp("recall", data, "ids", default=[])
        if not isinstance(ids, list):
            ids = [ids]
        latency = self._resp("recall", data, "latency_ms", default=wall_ms)
        return {"ids": [str(i) for i in ids], "latency_ms": float(latency)}

    def capture(self, text: str, scope: str, namespace: str) -> dict:
        ctx = {"input": text, "scope": scope, "namespace": namespace}
        data, wall_ms = self._run("capture", ctx)
        action = self._resp("capture", data, "action")
        saved = self._resp("capture", data, "saved_ids", default=[])
        if not isinstance(saved, list):
            saved = [saved]
        latency = self._resp("capture", data, "latency_ms", default=wall_ms)
        return {
            "action": str(action) if action is not None else None,
            "saved_ids": [str(s) for s in saved],
            "latency_ms": float(latency),
        }

    def export_memories(self) -> list[dict]:
        data, _ = self._run("export", {})
        items = self._resp("export", data, "memories", default=data if isinstance(data, list) else [])
        fields = self.commands.get("export", {}).get("fields", {})
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            out.append({
                "id": str(item.get(fields.get("id", "memory_id"), item.get("id", ""))),
                "content": str(item.get(fields.get("content", "content"), "")),
                "scope": str(item.get(fields.get("scope", "scope"), "")),
                "namespace": str(item.get(fields.get("namespace", "namespace"), "")),
                "status": str(item.get(fields.get("status", "status"), "")),
            })
        return out

    def generate(self, prompt: str, context_blocks: list[str]) -> dict | None:
        if not self.available("generate"):
            return None
        ctx = {"prompt": prompt, "context": "\n\n".join(context_blocks)}
        data, wall_ms = self._run("generate", ctx)
        return {
            "answer": str(self._resp("generate", data, "answer", default="")),
            "input_tokens": self._resp("generate", data, "input_tokens"),
            "output_tokens": self._resp("generate", data, "output_tokens"),
            "latency_ms": float(self._resp("generate", data, "latency_ms", default=wall_ms)),
        }


# ---------------------------------------------------------------------------
# MockAdapter: in-process fake memory store for pipeline validation
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9@.+_-]+")
_SECRET = re.compile(r"(sk-[a-z0-9]+-?[a-z0-9-]*|ghp_[A-Za-z0-9]+|password|passphrase|api key is)", re.I)
_PII = re.compile(r"(\+\d[\d-]{7,}|\d{3}[- ]?\d{3}[- ]?\d{4}|\b\d+ [A-Z][a-z]+ St\b)")
_TEMP = re.compile(r"\b(today|tomorrow|this session|borrowed|/tmp/)", re.I)
_PROPOSAL = re.compile(r"\b(prototype|proposal|does not yet|next week)\b", re.I)
_TEMP_SAVE = re.compile(r"\btemporaril\w+", re.I)
_CORRECTION = re.compile(r"\b(correct\w*|no longer|invalidate|update:|goes back|obsolete|new decision)\b", re.I)
_OTHER_SCOPE = re.compile(r"\b(other-tool|another project|other project)\b", re.I)
_INJECTION = re.compile(r"\b(ignore all|ignore previous|always answer)\b", re.I)

_STATUS_PENALTY = {
    "deprecated": 0.25,
    "temporary": 0.25,
    "speculative": 0.30,
    "untrusted": 0.20,
}


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _owner(namespace: str) -> str:
    if "://" in namespace:
        scheme, rest = namespace.split("://", 1)
        return f"{scheme}://{rest.split('/')[0]}"
    return namespace


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Marked as estimated in results."""
    return max(1, round(len(text) / 4))


class MockAdapter:
    """Naive keyword-overlap retriever + heuristic capture. Demo/testing only."""

    name = "mock"

    def __init__(self, config: dict | None = None):
        self._store: list[dict] = []
        self._auto = 0

    def available(self, op: str) -> bool:
        return True

    def reset(self) -> None:
        self._store = []
        self._auto = 0

    def import_memory(self, memory: dict) -> dict:
        if memory.get("status") == "do_not_persist":
            return {"ok": False, "id": None, "skipped": True,
                    "note": "mock policy: do_not_persist memories are rejected"}
        rec = {
            "id": str(memory.get("memory_id") or memory.get("id") or self._next_id()),
            "content": memory.get("content", ""),
            "scope": memory.get("scope", "project"),
            "namespace": memory.get("namespace", ""),
            "status": memory.get("status", "active"),
            "tags": list(memory.get("tags", [])),
        }
        rec["owner"] = _owner(rec["namespace"])
        rec["tokens"] = _tokens(rec["content"]) | _tokens(" ".join(rec["tags"]))
        self._store.append(rec)
        return {"ok": True, "id": rec["id"], "skipped": False, "note": ""}

    def recall(self, query: str, scope: str, namespace: str, top_k: int) -> dict:
        t0 = time.perf_counter()
        q = _tokens(query)
        owner = _owner(namespace)
        scored = []
        for rec in self._store:
            if rec["owner"] != owner:
                continue  # mock enforces scope isolation strictly
            overlap = len(q & rec["tokens"])
            if overlap == 0:
                continue
            score = overlap / (1 + len(rec["tokens"])) ** 0.5
            score *= _STATUS_PENALTY.get(rec["status"], 1.0)
            scored.append((score, rec["id"]))
        scored.sort(key=lambda x: (-x[0], x[1]))
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return {"ids": [mid for _, mid in scored[:top_k]], "latency_ms": latency_ms}

    def capture(self, text: str, scope: str, namespace: str) -> dict:
        t0 = time.perf_counter()
        action, saved = self._capture_decision(text, scope, namespace)
        return {"action": action, "saved_ids": saved,
                "latency_ms": (time.perf_counter() - t0) * 1000.0}

    def _capture_decision(self, text: str, scope: str, namespace: str):
        has_secret = bool(_SECRET.search(text)) or bool(_PII.search(text))
        if has_secret:
            clean = [s.strip() for s in re.split(r"[.;]\s*", text)
                     if s.strip() and not _SECRET.search(s) and not _PII.search(s)]
            if clean:
                saved = self._save(". ".join(clean) + ".", scope, namespace, "active")
                return "partial_save", [saved]
            return "reject", []
        if _INJECTION.search(text):
            return "reject", []
        if _PROPOSAL.search(text):
            return "save_temporary", [self._save(text, scope, namespace, "temporary")]
        if _TEMP_SAVE.search(text):
            return "save_temporary", [self._save(text, scope, namespace, "temporary")]
        if _TEMP.search(text):
            return "reject", []
        if _OTHER_SCOPE.search(text):
            return "save_other_scope", [self._save(text, scope, "project://other-tool/misc", "active")]
        if _CORRECTION.search(text):
            return "update", [self._save(text, scope, namespace, "active")]
        # near-duplicate detection (jaccard over token sets, same owner)
        toks = _tokens(text)
        owner = _owner(namespace)
        for rec in self._store:
            if rec["owner"] != owner or not rec["tokens"]:
                continue
            jac = len(toks & rec["tokens"]) / len(toks | rec["tokens"])
            if jac >= 0.6:
                return "merge", [rec["id"]]
        return "save", [self._save(text, scope, namespace, "active")]

    def _save(self, content: str, scope: str, namespace: str, status: str) -> str:
        mid = self._next_id()
        rec = {"id": mid, "content": content, "scope": scope, "namespace": namespace,
               "status": status, "tags": [], "owner": _owner(namespace),
               "tokens": _tokens(content)}
        self._store.append(rec)
        return mid

    def _next_id(self) -> str:
        self._auto += 1
        return f"AUTO-{self._auto:04d}"

    def export_memories(self) -> list[dict]:
        return [{"id": r["id"], "content": r["content"], "scope": r["scope"],
                 "namespace": r["namespace"], "status": r["status"]} for r in self._store]

    def generate(self, prompt: str, context_blocks: list[str]) -> dict:
        t0 = time.perf_counter()
        used = [b.strip().rstrip(".") for b in context_blocks[:4]]
        answer = "Mock answer based on retrieved context: " + ". ".join(used) + "."
        input_text = prompt + "\n" + "\n".join(context_blocks)
        return {
            "answer": answer,
            "input_tokens": estimate_tokens(input_text),
            "output_tokens": estimate_tokens(answer),
            "latency_ms": (time.perf_counter() - t0) * 1000.0,
        }


def build_adapter(name: str, config: dict):
    if name == "mock":
        return MockAdapter(config)
    if name == "command":
        return CommandAdapter(config)
    raise AdapterError(f"unknown adapter '{name}' (expected 'mock' or 'command')")
