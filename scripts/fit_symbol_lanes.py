"""How many symbol-level lanes fit a local model's window, on the 37 lanes-main tasks. $0.

For each task of results/swepro-lanes/main (the La arm's root task.created events):

1. fetch the task's scope files at the base commit from raw.githubusercontent.com into
   data/sources/ (gitignored; upstream licences, never committed); a 404 is a file the task creates;
2. take the contract units the final governed merge touched (the last La root task.submitted diff:
   changed base lines and insertion points mapped to functions, classes or methods);
3. pack them into symbol lanes with parataxis.symbols.plan_symbol_lanes (lane count = number of
   units, capped at --max-lanes; each lane prompt = the shared part + its files as lane views);
4. compare with whole-file lanes (the API study's design) and with covering every unit of the scope.

Token counts. The API study logged, per task, an exact count_tokens of the single-worker prompt
(``prompt_tokens_exact.d_worker``) and contraprova's characters/3 estimate of the same prompt
(``worker_prompt_tokens_est``). Their ratio calibrates this script's characters/3 estimates per
task. The shared part of a lane prompt is the exact lead-prompt count (``d_lead``: statement,
requirements, interface, outline of every scope file, visible test names) plus --board-tokens for
the lane's contract and the interface board. These are Claude-tokenizer counts; a local model's
tokenizer differs, so the local pre-flight must re-count with that model's tokenizer.

Usage: python scripts/fit_symbol_lanes.py [--log results/swepro-lanes/main/log.jsonl]
       [--out results/symbol-lanes-fit] [--target 24000] [--max-lanes 8] [--offline]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parataxis.symbols import (  # noqa: E402
    Span,
    est_tokens,
    plan_symbol_lanes,
    touched_units,
    units,
)

CPT = 3.0  # contraprova's CHARS_PER_TOKEN, so the calibration ratio applies directly


def load_tasks(log: Path) -> list[dict]:
    created: dict[str, dict] = {}
    final_diff: dict[str, str] = {}
    for line in log.open():
        e = json.loads(line)
        p = e.get("payload", {})
        tid = p.get("task_id", "")
        if not tid.startswith("La:") or tid.count(":") != 1:
            continue
        if e["type"] == "task.created":
            created[tid] = p
        elif e["type"] == "task.submitted":
            final_diff[tid] = p.get("diff", "")
    return [dict(created[t], final_diff=final_diff.get(t, "")) for t in created]


def fetch(repo: str, commit: str, path: str, cache: Path, offline: bool) -> str | None:
    dest = cache / repo / commit / path
    missing = dest.with_name(dest.name + ".404")
    if dest.exists():
        return dest.read_text(encoding="utf-8", errors="replace")
    if missing.exists():
        return None
    if offline:
        raise SystemExit(f"not cached and --offline: {repo}@{commit}:{path}")
    url = f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            missing.parent.mkdir(parents=True, exist_ok=True)
            missing.write_text("")
            return None
        raise
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data.decode("utf-8", errors="replace")


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_diff(diff: str) -> dict[str, tuple[list[int], list[int], int]]:
    """path -> (base lines removed, base insertion points, added line count). A created file has
    no base lines; its added count is reported."""
    out: dict[str, tuple[list[int], list[int], int]] = {}
    path = None
    base_line = 0
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            target = line[4:].strip()
            path = target[2:] if target.startswith("b/") else target
            out.setdefault(path, ([], [], 0))
            continue
        if line.startswith("--- ") or line.startswith("diff --git") or path is None:
            continue
        m = _HUNK.match(line)
        if m:
            base_line = int(m.group(1)) - (0 if m.group(2) != "0" else -1)
            continue
        removed, inserts, added = out[path]
        if line.startswith("-"):
            removed.append(base_line)
            base_line += 1
        elif line.startswith("+"):
            if not removed or removed[-1] != base_line - 1:
                inserts.append(base_line - 1)
            out[path] = (removed, inserts, added + 1)
        elif line.startswith(" "):
            base_line += 1
    return out


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summarize(xs: list[float], nd: int = 1) -> dict:
    return {"median": round(statistics.median(xs), nd), "p90": round(pct(xs, 0.9), nd),
            "max": round(max(xs), nd), "min": round(min(xs), nd)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", type=Path, default=ROOT / "results/swepro-lanes/main/log.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "results/symbol-lanes-fit")
    ap.add_argument("--cache", type=Path, default=ROOT / "data/sources")
    ap.add_argument("--target", type=int, default=24_000)
    ap.add_argument("--max-lanes", type=int, default=8)
    ap.add_argument("--board-tokens", type=int, default=400)
    ap.add_argument("--split-class-lines", type=int, default=120)
    ap.add_argument("--offline", action="store_true", help="use only cached sources")
    args = ap.parse_args(argv)

    rows = []
    for t in load_tasks(args.log):
        ex = t["exercise_id"]
        exact = t["prompt_tokens_exact"]
        cal = exact["d_worker"] / t["worker_prompt_tokens_est"]
        shared = exact["d_lead"] + args.board_tokens
        sources: dict[str, str] = {}
        created = []
        for path in t["scope"]:
            text = fetch(t["repo"], t["base_commit"], path, args.cache, args.offline)
            if text is None:
                created.append(path)
            else:
                sources[path] = text
        files_est = sum(est_tokens(s, CPT) for s in sources.values())

        touched: list[Span] = []
        new_file_lines = {}
        for path, (removed, inserts, added) in parse_diff(t["final_diff"]).items():
            if path in sources:
                touched += touched_units(path, sources[path], removed, insert_points=inserts,
                                         split_class_lines=args.split_class_lines)
            else:
                new_file_lines[path] = added
                touched.append(Span(path, 1, max(1, added), "<new file>", "block"))
        touched = sorted(set(touched))

        def scaled(n: float) -> int:
            return round(n * cal)

        # (a) whole-file lanes over the touched files (the API study's ownership unit), one file
        # per lane: the largest lane is the shared part plus the largest touched file in full
        touched_files = sorted({s.path for s in touched if s.path in sources})
        file_tokens = {p: est_tokens(sources[p], CPT) for p in touched_files}
        file_lane_max = shared + scaled(max(file_tokens.values(), default=0))
        file_share = (max(file_tokens.values()) / sum(file_tokens.values())) if file_tokens else 0.0

        # (b) symbol lanes over the touched units
        plan = plan_symbol_lanes(touched, sources, shared_tokens=0, target_tokens=args.target,
                                 max_lanes=args.max_lanes, chars_per_token=CPT,
                                 split_class_lines=args.split_class_lines)
        lane_prompts = [shared + scaled(ln.prompt_tokens) for ln in plan.lanes]

        # (c) symbol lanes covering every unit of the scope files (no knowledge of the edit)
        all_units = [u for p, s in sources.items() for u in units(p, s, split_class_lines=args.split_class_lines)]
        cover = plan_symbol_lanes(all_units, sources, shared_tokens=0, target_tokens=args.target,
                                  max_lanes=args.max_lanes, chars_per_token=CPT,
                                  split_class_lines=args.split_class_lines)
        cover_prompts = [shared + scaled(ln.prompt_tokens) for ln in cover.lanes]

        rows.append({
            "exercise_id": ex, "repo": t["repo"], "language": t["language"],
            "calibration": round(cal, 4), "shared_tokens": shared,
            "d_worker_exact": exact["d_worker"], "scope_files": len(t["scope"]), "created_files": created,
            "scope_file_tokens": scaled(files_est),
            "touched_files": len(touched_files) + len(new_file_lines), "touched_units": len(touched),
            "file_lanes": {"k": len(touched_files) + len(new_file_lines), "max_prompt": file_lane_max,
                           "largest_code_share": round(file_share, 3)},
            "symbol_lanes": {"k": plan.k, "prompts": lane_prompts, "max_prompt": max(lane_prompts),
                             "largest_code_share": round(plan.largest_code_share, 3),
                             "lanes": [[u.unit_id for u in ln.owned] for ln in plan.lanes]},
            "cover_lanes": {"k": cover.k, "units": cover.n_units, "max_prompt": max(cover_prompts),
                            "largest_code_share": round(cover.largest_code_share, 3)},
        })

    def frac(key: str, limit: int) -> str:
        n = sum(1 for r in rows if r[key]["max_prompt"] <= limit)
        return f"{n}/{len(rows)}"

    summary = {
        "tasks": len(rows), "target_tokens": args.target, "max_lanes": args.max_lanes,
        "board_tokens": args.board_tokens, "split_class_lines": args.split_class_lines,
        "calibration": summarize([r["calibration"] for r in rows], 3),
        "shared_tokens": summarize([r["shared_tokens"] for r in rows]),
        "touched_units": summarize([r["touched_units"] for r in rows]),
        "file_lanes": {
            "k": summarize([r["file_lanes"]["k"] for r in rows]),
            "max_prompt": summarize([r["file_lanes"]["max_prompt"] for r in rows]),
            "largest_code_share": summarize([r["file_lanes"]["largest_code_share"] for r in rows], 3),
            "fit": {str(w): frac("file_lanes", w) for w in (16_000, 24_000, 32_000)},
        },
        "symbol_lanes": {
            "k": summarize([r["symbol_lanes"]["k"] for r in rows]),
            "k_histogram": {str(k): sum(1 for r in rows if r["symbol_lanes"]["k"] == k)
                            for k in range(1, args.max_lanes + 1)},
            "max_prompt": summarize([r["symbol_lanes"]["max_prompt"] for r in rows]),
            "all_lane_prompts": summarize([p for r in rows for p in r["symbol_lanes"]["prompts"]]),
            "largest_code_share": summarize([r["symbol_lanes"]["largest_code_share"] for r in rows], 3),
            "fit": {str(w): frac("symbol_lanes", w) for w in (16_000, 24_000, 32_000)},
        },
        "cover_lanes": {
            "k": summarize([r["cover_lanes"]["k"] for r in rows]),
            "max_prompt": summarize([r["cover_lanes"]["max_prompt"] for r in rows]),
            "largest_code_share": summarize([r["cover_lanes"]["largest_code_share"] for r in rows], 3),
            "fit": {str(w): frac("cover_lanes", w) for w in (16_000, 24_000, 32_000)},
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "fit.json").write_text(json.dumps({"summary": summary, "tasks": rows}, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
