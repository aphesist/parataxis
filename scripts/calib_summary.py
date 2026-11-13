"""The calibration's pre-registered checks and the choice of n (PREREGISTRATION.md, "calibrating n").

    python scripts/calib_summary.py --dir results/local-calib --out results/local-calib/calibration.json

Reads each pass's logs (``logs/``) and its analysis (``analysis/<pass>.json``, from
``scripts/analyze_local.py``; ``analysis/<pass>-est.json`` is the same with tokens estimated as
characters / 3, written for every pass so that passes compare on one count). Per pass:

- **solves** of the pass's arm and its shadow;
- **test-gated tok/s** (ratio of sums with its bootstrap CI), tokenized where the pod was alive, and
  estimated for every pass;
- **output caps:** local requests that reached the 8K output cap (stop rule 4: invalid above 10%);
- **format compliance:** gated submissions whose edits failed to parse or apply (``T0.edits``; the
  threshold is 20% of L1's edits);
- **throughput noise:** the aggregate tok/s iqr width over its median (stop rule 5: repeats above 25%).

Then the choice rule: the n with the most test-gated tok/s (estimated count, the one every pass has)
and no preemption; if another n solves at least one more probe task, the larger of the two.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

CAP_TOKENS = 8000


def checks(paths: list[Path], cap_tokens: int = CAP_TOKENS) -> dict:
    events = [json.loads(line) for p in paths for line in p.open(encoding="utf-8")]
    use = [e["payload"] for e in events if e["type"] == "usage.recorded" and e["payload"].get("engine") == "vllm"]
    capped = sum(u["output_tokens"] >= cap_tokens for u in use)
    gates = [e["payload"] for e in events if e["type"] == "gate.decided"]
    kinds: Counter = Counter()
    last_sub: dict[str, dict] = {}
    for e in events:
        if e["type"] == "task.submitted":
            last_sub[e["payload"]["task_id"]] = e["payload"]
        if e["type"] != "gate.decided":
            continue
        g = e["payload"]
        bad = [r for r in g["results"] if r.get("gate") == "T0.edits" and r.get("verdict") != "pass"]
        if bad:
            why = bad[0].get("reason", "")
            sub = last_sub.get(g.get("task_id"), {})
            if sub.get("final_failure") == "tool_call":
                kinds["tool call (no edit)"] += 1
                continue
            kinds["no block applied" if "no file was changed" in why else
                  "SEARCH text not found" if "SEARCH text not found" in why else
                  "truncated block" if "truncated" in why else "missing path" if "path" in why else "other"] += 1
    subs = [e["payload"] for e in events if e["type"] == "task.submitted"]
    return {
        "local_requests": len(use), "cap_hits": capped, "cap_hit_rate": round(capped / max(1, len(use)), 3),
        "gated_submissions": len(gates), "edit_failures": sum(kinds.values()),
        "edit_failure_rate": round(sum(kinds.values()) / max(1, len(gates)), 3), "edit_failure_kinds": dict(kinds),
        "first_response_failures": dict(Counter(s.get("original_failure") or "none" for s in subs)),
        "tool_call_replies": sum(bool(s.get("tool_call")) + bool(s.get("repair_tool_call")) for s in subs),
        "unit_added": sum(len(s.get("unit_added", [])) + len(s.get("repair_unit_added", [])) for s in subs),
        "cap_tokens": cap_tokens,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--preemptions", type=int, required=True, help="vllm:num_preemptions_total at the end")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--passes", default="La8=La8 La4=La4 La2=La2 L1=L1,L1b,L1c",
                    help="pass=log[,log...] pairs (the first calibration's by default)")
    ap.add_argument("--l1-cap16", action="store_true", help="L1 ran with 16K output tokens (b.5 item 10)")
    a = ap.parse_args(argv)
    passes = {kv.split("=")[0]: kv.split("=")[1].split(",") for kv in a.passes.split()}
    res: dict = {"preemptions_total": a.preemptions, "passes": {}}
    for name, logs in passes.items():
        arm = "L1" if name.startswith("L1") else "La"
        tok = json.loads((a.dir / "analysis" / f"{name}.json").read_text())
        est = json.loads((a.dir / "analysis" / f"{name}-est.json").read_text())
        thr = est["throughput"][arm]["aggregate_tok_s"]
        row = {
            "logs": [f"logs/{x}.jsonl" for x in logs],
            "solved": est["solve_rates"][arm]["solved"], "n": est["solve_rates"][arm]["n"],
            "shadow_solved": est["solve_rates"].get(f"{arm}-shadow", {}).get("solved"),
            "test_gated_tok_s_est": est["tok_s"][arm]["test_gated_tok_s"],
            "test_gated_tok_s": tok["tok_s"][arm]["test_gated_tok_s"] if tok["token_count"].startswith("local") else None,
            "raw_tok_s": est["tok_s"][arm]["raw_tok_s"],
            "aggregate_tok_s": thr, "iqr_over_median": round((thr["iqr"][1] - thr["iqr"][0]) / thr["median"], 3),
            "capped_tasks": est["capped"].get(arm, 0),
            **checks([a.dir / "logs" / f"{x}.jsonl" for x in logs], 16_000 if arm == "L1" and a.l1_cap16 else CAP_TOKENS),
        }
        row["rule4_output_caps_ok"] = row["cap_hit_rate"] <= 0.10
        row["rule5_noise_ok"] = row["iqr_over_median"] <= 0.25
        res["passes"][name] = row
    l1 = next(v for k, v in res["passes"].items() if k.startswith("L1"))
    res["format_compliance"] = {"l1_edit_failure_rate": l1["edit_failure_rate"], "threshold": 0.20,
                                "ok": l1["edit_failure_rate"] <= 0.20}
    la = {}
    for k, v in res["passes"].items():  # La2 and La2b: the choice uses the first run of each n
        if k.startswith("La") and k[2:].isdigit():
            la[int(k[2:])] = v
    ok = {n: v for n, v in la.items() if a.preemptions == 0}
    best = max(ok, key=lambda n: ok[n]["test_gated_tok_s_est"][0])
    more = [n for n in ok if ok[n]["solved"] >= ok[best]["solved"] + 1]
    chosen = max([best, *more]) if more else best
    res["choice"] = {"by_tok_s": best, "solving_one_more": more, "n": chosen}
    a.out.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({k: res[k] for k in ("choice", "format_compliance")}))
    for k, v in res["passes"].items():
        print(k, v["solved"], v["shadow_solved"], v["test_gated_tok_s_est"], v["test_gated_tok_s"], v["cap_hit_rate"],
              v["edit_failure_rate"], v["iqr_over_median"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
