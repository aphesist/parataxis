"""The local track's pre-registered analysis (PREREGISTRATION.md, "primary" and "secondary").

    python scripts/analyze_local.py --log runs/local-main.jsonl --tasks results/local/tasks-main.txt \\
        [--api-log results/swepro-lanes/main/log.jsonl] [--ledger runs/pods/ledger.jsonl] \\
        [--tokenize-url URL] --out results/local-main/analysis.json

- **primary:** La vs La-shadow, exact McNemar (two-sided), with a paired bootstrap 95% CI
  (10,000 resamples, seed 20261113) of the solve-rate difference.
- **secondary:** La vs L1, Lb vs La, local La vs the API study's Haiku La (paired by task), test-gated
  and raw tok/s per arm, wall time to a passing solution, coordination failures by kind (La vs Lb,
  Wilcoxon signed-rank, normal approximation), lane counts, blame rules, repair rescues, throughput
  (aggregate tok/s, tail share, MTP-free per-request rate), planner and GPU cost.

Times. A task's end-to-end time runs from its ``task.created`` to its final arm outcome, minus the
verifier's seconds inside it (each verifier run counted once: runs are keyed by the files they
scored). Tokens of the shipped diff are counted with the local tokenizer when ``--tokenize-url`` is
given (vLLM ``/tokenize``, key from ``PARATAXIS_VLLM_KEY``), else estimated as characters / 3 and
the output says so.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contraprova.stats import discordant, mcnemar_exact, paired_bootstrap_ci, wilson_interval  # noqa: E402

SEED = 20261113
ITERS = 10_000
ARMS = ("L1", "La", "La-shadow", "La-first", "Lb", "Lb-shadow", "Lb-first")


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def arm_outcomes(events: list[dict]) -> dict[tuple[str, str], dict]:
    """(arm, exercise id) -> the final arm outcome payload (gate replays and forks skipped)."""
    out = {}
    for e in events:
        p = e["payload"]
        if e["type"] == "outcome.scored" and "arm" in p and "gate_seq" not in p and "fork_id" not in p:
            out[(p["arm"], p["task_id"])] = {**p, "_ts": ts(e["ts"])}
    return out


def verifier_seconds(events: list[dict]) -> dict[str, float]:
    """kernel task id -> verifier seconds inside it, each run (files scored) counted once."""
    seen: dict[str, set] = defaultdict(set)
    secs: dict[str, float] = defaultdict(float)

    def add(task: str, ev: dict) -> None:
        run = ev.get("run", ev) if isinstance(ev, dict) else {}
        s = run.get("seconds")
        key = (run.get("files_sha256") or ev.get("files_sha256"), ev.get("tests_sha256"))
        if s is None or key in seen[task]:
            return
        seen[task].add(key)
        secs[task] += float(s)

    for e in events:
        p = e["payload"]
        if e["type"] == "gate.decided":
            task = p["task_id"].split(":")[0] + ":" + p["task_id"].split(":")[1] if p["task_id"].count(":") >= 1 else p["task_id"]
            for r in p.get("results", []):
                if isinstance(r.get("evidence"), dict):
                    add(task, r["evidence"])
        elif e["type"] == "outcome.scored" and isinstance(p.get("evidence"), dict) and p.get("log_task_id"):
            add(p["log_task_id"], p["evidence"])
    return secs


def shipped_diffs(events: list[dict]) -> dict[str, str]:
    """kernel task id (arm:exercise) -> the diff of its last submission (the merge for lane arms)."""
    out = {}
    for e in events:
        p = e["payload"]
        if e["type"] == "task.submitted" and p["task_id"].count(":") == 1:
            out[p["task_id"]] = p.get("diff", "")
    return out


def make_counter(url: str | None):
    if not url:
        return (lambda text: math.ceil(len(text) / 3)), "estimated (characters / 3)"
    from parataxis.local import VLLMClient
    from parataxis.lanes import LOCAL_MODEL
    from contraprova.interfaces import Message

    client = VLLMClient(url)
    return (lambda text: client.count_tokens(model=LOCAL_MODEL, system="", messages=[Message("user", text)])
            if text else 0), "local tokenizer (vLLM /tokenize)"


def ratio_ci(nums: list[float], dens: list[float]) -> tuple[float, float, float]:
    """Sum(nums) / sum(dens) with a percentile bootstrap CI over tasks."""
    n = len(nums)
    if not n or sum(dens) <= 0:
        return (float("nan"),) * 3
    rng = random.Random(SEED)
    vals = []
    for _ in range(ITERS):
        idx = [rng.randrange(n) for _ in range(n)]
        d = sum(dens[i] for i in idx)
        vals.append(sum(nums[i] for i in idx) / d if d else 0.0)
    vals.sort()
    return sum(nums) / sum(dens), vals[int(0.025 * ITERS)], vals[min(ITERS - 1, int(0.975 * ITERS))]


def paired(a_arm: str, b_arm: str, oa: dict, ob: dict, tasks: list[str]) -> dict | None:
    both = [t for t in tasks if (a_arm, t) in oa and (b_arm, t) in ob]
    if not both:
        return None
    a = [bool(oa[(a_arm, t)]["solved"]) for t in both]
    b = [bool(ob[(b_arm, t)]["solved"]) for t in both]
    a_only, b_only = discordant(a, b)
    mean, lo, hi = paired_bootstrap_ci([float(x) - float(y) for x, y in zip(a, b)], ITERS, 0.05, SEED)
    return {"n": len(both), "a": a_arm, "b": b_arm, "a_solved": sum(a), "b_solved": sum(b),
            "a_only": a_only, "b_only": b_only, "p_mcnemar": mcnemar_exact(a_only, b_only),
            "diff_points": round(100 * mean, 1), "ci_points": [round(100 * lo, 1), round(100 * hi, 1)]}


def wilcoxon(x: list[float], y: list[float]) -> dict:
    d = [a - b for a, b in zip(x, y) if a != b]
    n = len(d)
    if n == 0:
        return {"n_nonzero": 0, "p": 1.0}
    ranks = sorted(range(n), key=lambda i: abs(d[i]))
    r = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[ranks[j + 1]]) == abs(d[ranks[i]]):
            j += 1
        for k in range(i, j + 1):
            r[ranks[k]] = (i + j) / 2 + 1
        i = j + 1
    w = sum(rv for rv, dv in zip(r, d) if dv > 0)
    mu, sd = n * (n + 1) / 4, math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (w - mu) / sd if sd else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"n_nonzero": n, "w_plus": w, "z": round(z, 3), "p": round(p, 4)}


def throughput(events: list[dict]) -> dict[str, dict]:
    """Per lane arm: per task, the local requests' union span, aggregate output tok/s over it and the
    tail share (time with fewer than the most concurrent requests active)."""
    by: dict[tuple[str, str], list[tuple[float, float, int]]] = defaultdict(list)
    for e in events:
        p = e["payload"]
        if e["type"] == "usage.recorded" and str(p.get("model", "")).startswith("local:") and "t_start" in p:
            ex = str(p.get("task_id", "")).split(":")[1] if ":" in str(p.get("task_id", "")) else ""
            by[(p.get("arm", ""), ex)].append((p["t_start"], p["t_end"], int(p.get("output_tokens", 0))))
    out: dict[str, dict] = defaultdict(lambda: {"aggregate_tok_s": [], "tail_share": [], "per_request_tok_s": []})
    for (arm, _), reqs in by.items():
        points = sorted({t for a, b, _ in reqs for t in (a, b)})
        span = 0.0
        tail = 0.0
        peak = 0
        segs = []
        for a, b in zip(points, points[1:]):
            k = sum(1 for s, e, _ in reqs if s <= a and e >= b)
            if k:
                segs.append((b - a, k))
                peak = max(peak, k)
        for dt, k in segs:
            span += dt
            if k < peak:
                tail += dt
        toks = sum(t for _, _, t in reqs)
        if span > 0:
            out[arm]["aggregate_tok_s"].append(toks / span)
            out[arm]["tail_share"].append(tail / span)
        out[arm]["per_request_tok_s"] += [t / (e - s) for s, e, t in reqs if e > s]
    return {arm: {k: ({"median": round(statistics.median(v), 2),
                       "iqr": [round(q, 2) for q in statistics.quantiles(v, n=4)[::2]] if len(v) >= 2 else None,
                       "n": len(v)} if v else None) for k, v in d.items()} for arm, d in out.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--api-log", type=Path, default=ROOT / "results/swepro-lanes/main/log.jsonl")
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--tokenize-url", default=None)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    events = load(a.log)
    tasks = [t.strip() for t in a.tasks.read_text().splitlines() if t.strip()]
    outc = arm_outcomes(events)
    created = {e["payload"]["task_id"]: ts(e["ts"]) for e in events if e["type"] == "task.created"}
    vsec = verifier_seconds(events)
    diffs = shipped_diffs(events)
    count, count_kind = make_counter(a.tokenize_url)
    arms = [x for x in ARMS if any((x, t) in outc for t in tasks)]

    res: dict = {"log": str(a.log), "tasks": len(tasks), "arms": arms, "token_count": count_kind, "seed": SEED}
    res["solve_rates"] = {}
    for arm in arms:
        got = [bool(outc[(arm, t)]["solved"]) for t in tasks if (arm, t) in outc]
        lo, hi = wilson_interval(sum(got), len(got)) if got else (float("nan"), float("nan"))
        res["solve_rates"][arm] = {"solved": sum(got), "n": len(got), "wilson95": [round(lo, 3), round(hi, 3)]}

    res["primary"] = paired("La", "La-shadow", outc, outc, tasks)
    sec = {"La_vs_L1": paired("La", "L1", outc, outc, tasks), "Lb_vs_La": paired("Lb", "La", outc, outc, tasks)}
    if a.api_log and a.api_log.exists():
        api = arm_outcomes(load(a.api_log))
        sec["local_La_vs_api_La"] = paired("La", "La", outc, api, tasks)
    res["secondary"] = sec

    # test-gated and raw tok/s, wall time to a passing solution
    local_out: dict[str, float] = defaultdict(float)
    for e in events:
        p = e["payload"]
        if e["type"] == "usage.recorded" and str(p.get("model", "")).startswith("local:"):
            local_out[str(p.get("task_id", "")).split(":")[0] + ":" + str(p.get("task_id", "")).split(":")[1]] += \
                int(p.get("output_tokens", 0))
    tok = {}
    walls: dict[str, dict[str, float]] = defaultdict(dict)
    for arm in ("L1", "La", "Lb"):
        nums, raws, dens = [], [], []
        for t in tasks:
            o = outc.get((arm, t))
            tid = f"{arm}:{t}"
            if o is None or tid not in created:
                continue
            wall = max(0.0, o["_ts"] - created[tid] - vsec.get(tid, 0.0))
            dens.append(wall)
            nums.append(float(count(diffs.get(tid, ""))) if o["solved"] else 0.0)
            raws.append(local_out.get(tid, 0.0))
            if o["solved"]:
                walls[arm][t] = wall
        if dens:
            g, glo, ghi = ratio_ci(nums, dens)
            r, rlo, rhi = ratio_ci(raws, dens)
            tok[arm] = {"tasks": len(dens), "test_gated_tok_s": [round(g, 2), round(glo, 2), round(ghi, 2)],
                        "raw_tok_s": [round(r, 2), round(rlo, 2), round(rhi, 2)],
                        "wall_s_total": round(sum(dens), 1)}
    res["tok_s"] = tok
    both = [t for t in tasks if t in walls.get("La", {}) and t in walls.get("L1", {})]
    if both:
        m, lo, hi = paired_bootstrap_ci([walls["La"][t] - walls["L1"][t] for t in both], ITERS, 0.05, SEED)
        res["wall_to_pass_La_minus_L1_s"] = {"n": len(both), "mean": round(m, 1), "ci": [round(lo, 1), round(hi, 1)]}

    # coordination failures, lane counts, blame, rescues
    kinds: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        p = e["payload"]
        if e["type"] == "coordination.detected":
            arm, ex = p["task_id"].split(":")[0], p["task_id"].split(":")[1]
            kinds[arm][(ex, p["kind"])] += 1
    res["coordination"] = {arm: dict(Counter(k for (_, k) in c.elements())) for arm, c in kinds.items()}
    totals = {arm: [sum(v for (ex, _), v in kinds[arm].items() if ex == t) for t in tasks] for arm in ("La", "Lb")}
    res["coordination_La_vs_Lb"] = wilcoxon(totals["La"], totals["Lb"]) if kinds.get("Lb") else None
    res["lane_counts"] = dict(Counter(e["payload"]["k"] for e in events if e["type"] == "lane.planned"))
    res["blame_rules"] = dict(Counter(str(e["payload"].get("blame_rule")) for e in events
                                      if e["type"] == "merge.decided" and e["payload"].get("verdict") == "block"))
    res["capped"] = {arm: sum(1 for t in tasks if outc.get((arm, t), {}).get("capped")) for arm in ("L1", "La", "Lb")}
    res["throughput"] = throughput(events)

    # cost
    from contraprova.pricing import DEFAULT_TABLE, PRICE_TABLES, request_cost

    import parataxis.local  # noqa: F401  (local model priced at $0)

    planner = sum(request_cost(e["payload"], PRICE_TABLES[DEFAULT_TABLE]) for e in events
                  if e["type"] == "usage.recorded" and not str(e["payload"].get("model", "")).startswith("local:"))
    res["cost"] = {"planner_usd": round(planner, 4)}
    if a.ledger and a.ledger.exists():
        from parataxis.pod import ledger_spend

        res["cost"]["gpu"] = ledger_spend(a.ledger)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"primary": res["primary"], "solve_rates": res["solve_rates"], "tok_s": res["tok_s"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
