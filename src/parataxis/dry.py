"""Offline fakes for $0 dry runs of the local track (``python -m parataxis.run --local --dry-run``).

contraprova's ``ProFakeClient`` plans by file (``by_file_plan``) and gives each lane the gold blocks
of its files. Under the local track's rule (PREREGISTRATION.md: the lane count comes from the
contract units) that does not exercise wide fan-out. :func:`fake_client` subclasses it:

- **the planner** answers a unit-lane plan request with one lane per unit the gold patch touches
  (:func:`unit_plan`): each listed unit (``<module>`` included), each file owned whole, each new file.
  Above ``max_lanes`` units, consecutive units share lanes with the reason ``cap``.
- **each lane** answers with its own share of the gold patch: whole files as gold blocks; in a file
  split by units, the gold change restricted to the lane's units (the scope gate's own rule). With
  ``units=True`` the reply is rewritten in unit blocks (:func:`parataxis.unit_edits.to_unit_reply`).

Nothing here runs outside a dry run; no model sees the gold patch in a real run.
"""

from __future__ import annotations

import json
from typing import Any

from contraprova.harness.edits import apply_edits, diff_to_blocks, format_blocks, unified_patch

from .symbols import restrict_to_spans, spans_for, unit_groups


def gold_new_files(ex) -> dict[str, str]:
    blocks = diff_to_blocks(ex.task.patch, ex.context.files)
    return {**dict(ex.context.files), **apply_edits(blocks, ex.context.files).files}


def unit_plan(ex, max_lanes: int = 8) -> dict[str, Any]:
    """The plan a planner following the units rule would give for the gold patch (dry runs)."""
    from .lanes import SPLIT_CLASS_LINES, planner_units

    new = gold_new_files(ex)
    # items: lists of (kind, ref) that must share a lane; kind "unit" ("path::name"), "file" or "new"
    items: list[list[tuple[str, str]]] = []
    for path in sorted(ex.context.files):
        base = ex.context.files[path]
        if new.get(path, base) == base:
            items.append([("file", path)])  # a scope file the gold patch leaves alone is still owned
            continue
        groups = unit_groups(path, base, new[path], split_class_lines=SPLIT_CLASS_LINES) \
            if planner_units(path, base) else []
        items += [[("unit", f"{path}::{n}") for n in g] for g in groups] or [[("file", path)]]
    items += [[("new", p)] for p in sorted(ex.context.new_files)]
    k = max(1, min(max_lanes, len(items)))
    cuts = [items[i * len(items) // k:(i + 1) * len(items) // k] for i in range(k)]
    lanes = []
    for n, cut in enumerate(cuts, 1):
        group = [x for item in cut for x in item]
        lane: dict[str, Any] = {
            "lane_id": f"L{n}", "goal": "change " + ", ".join(ref for _, ref in group),
            "units": [ref for kind, ref in group if kind == "unit"],
            "files": [ref for kind, ref in group if kind in ("file", "new")], "symbols": [], "tests": []}
        if len(cut) > 1:
            lane["merge"] = {"reason": "cap", "why": f"the change needs {len(items)} unit groups for {max_lanes} lanes"}
        elif len(group) > 1:
            lane["merge"] = {"reason": "same-unit", "why": "one contiguous change crosses these units"}
        lanes.append(lane)
    return {"lanes": lanes, "interfaces": [], "rationale": "one lane per touched unit (dry run)"}


def lane_share(ex, lane: dict[str, Any]) -> str:
    """A lane's share of the gold patch as a SEARCH/REPLACE reply."""
    from .lanes import SPLIT_CLASS_LINES

    new = gold_new_files(ex)
    mine: dict[str, str] = {}
    by_path: dict[str, list[str]] = {}
    for uid in lane.get("units", []):
        path, _, name = uid.partition("::")
        by_path.setdefault(path, []).append(name)
    for path, names in by_path.items():
        base = ex.context.files[path]
        text, _ = restrict_to_spans(base, new[path], spans_for(path, base, names, split_class_lines=SPLIT_CLASS_LINES))
        if text != base:
            mine[path] = text
    for path in lane.get("files", []):
        if new.get(path) is not None and new.get(path) != ex.context.files.get(path):
            mine[path] = new[path]
    changed = {p: t for p, t in mine.items() if p in ex.context.files}
    patch = unified_patch({p: ex.context.files[p] for p in changed}, changed) if changed else ""
    text = format_blocks(diff_to_blocks(patch, dict(ex.context.files))) if patch else ""
    for p in sorted(set(mine) - set(changed)):  # created files: an empty SEARCH part creates the file
        content = mine[p] if mine[p].endswith("\n") else mine[p] + "\n"
        text += f"\n<<<<<<< SEARCH {p}\n=======\n{content}>>>>>>> REPLACE\n"
    return "Here are the changes for my lane.\n\n" + text


def local_mode(policy) -> str | None:
    """contraprova's ``--dry-solve escalate|conflict`` policies key on the Haiku ladder; read which
    one is set so the local ladder gets the same story: ``escalate`` (the last lane's first reply
    makes no change; it is blamed and its local repair gets its share) or ``conflict`` (lane L1's
    first reply also edits a unit of another lane, which the governed merge must reject)."""
    if policy is None:
        return None
    from contraprova.interfaces import HAIKU

    if policy("t", HAIKU, ("L3", 3)) == "none":
        return "escalate"
    if policy("t", HAIKU, ("L1", 3)) == "conflict":
        return "conflict"
    return None


def conflicting_block(ex, plan: dict[str, Any], lane_id: str) -> str:
    """One SEARCH/REPLACE block that breaks the first line of a unit another lane owns."""
    from .lanes import SPLIT_CLASS_LINES

    for ln in plan["lanes"]:
        if ln["lane_id"] == lane_id:
            continue
        for uid in ln.get("units", []):
            path, _, name = uid.partition("::")
            spans = spans_for(path, ex.context.files[path], [name], split_class_lines=SPLIT_CLASS_LINES)
            src = ex.context.files[path].split("\n")
            for sp in spans:
                line = src[sp.start - 1]
                if line.strip() and ex.context.files[path].count(line + "\n") == 1:
                    return f"\n<<<<<<< SEARCH {path}\n{line}\n=======\n{line}\nconflicting line from another lane\n>>>>>>> REPLACE\n"
    return ""


def fake_client(base, *, units: bool = True, unit_plans: bool = True):
    """A subclass of contraprova's offline ``ProFakeClient`` for the local track's dry runs."""
    from .unit_edits import to_unit_reply

    class LocalDryClient(base):
        def _worker_text(self, tid, model, prompt):
            if tid not in self.exercises:
                return super()._worker_text(tid, model, prompt)
            ex = self.exercises[tid]
            plans = self.__dict__.setdefault("_unit_plans", {})
            if "## Request: lane plan" in prompt:
                if not (unit_plans and "## Files and units" in prompt):
                    return super()._worker_text(tid, model, prompt)
                plans[tid] = unit_plan(ex, getattr(self, "max_lanes", 8))
                return "```json\n" + json.dumps(plans[tid], indent=1) + "\n```\n"
            m = self._LANE_LINE.search(prompt)
            if m is not None and tid in plans:
                lane = next((ln for ln in plans[tid]["lanes"] if ln["lane_id"] == m.group(1)), None)
                if lane is not None:
                    first = "previous attempt was rejected" not in prompt  # not a retry after blame
                    mode = local_mode(self.policy)
                    if mode == "escalate" and first and m.group(1) == f"L{m.group(2)}":
                        return "I could not find a safe change."  # the last lane fails once, is blamed, repairs
                    text = lane_share(ex, lane)
                    if mode == "conflict" and first and m.group(1) == "L1":
                        text += conflicting_block(ex, plans[tid], "L1")
                    return to_unit_reply(text, ex.context.files) if units and "<<<<<<< SEARCH" in text else text
            text = super()._worker_text(tid, model, prompt)
            if units and "<<<<<<< SEARCH" in text:
                return to_unit_reply(text, ex.context.files)
            return text

    return LocalDryClient
