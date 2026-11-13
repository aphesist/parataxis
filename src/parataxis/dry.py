"""Offline fakes for $0 dry runs of the local track (``python -m parataxis.run --local --dry-run``).

contraprova's ``ProFakeClient`` plans by file (``by_file_plan``) and gives each lane the gold blocks
of its files. Under the local track's rule (PREREGISTRATION.md: the lane count comes from the
contract units) that does not exercise wide fan-out. :func:`fake_client` subclasses it:

- **the planner** answers a unit-lane plan request with the change list the gold patch implies
  (:func:`unit_plan`): one change per touched unit group (``<module>`` included), each file listed as
  one unit, each new file. The kernel packs it into lanes exactly as in a run (:func:`packed_lanes`).
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
    """The change list a planner following the units rule would give for the gold patch (dry runs):
    one change per unit group the gold patch touches (units one hunk crosses stay together), each
    file listed as one unit, each new file. The kernel packs them into lanes."""
    from .lanes import SPLIT_CLASS_LINES, planner_units

    new = gold_new_files(ex)
    changes: list[dict[str, Any]] = []
    for path in sorted(ex.context.files):
        base = ex.context.files[path]
        groups = unit_groups(path, base, new[path], split_class_lines=SPLIT_CLASS_LINES) \
            if new.get(path, base) != base and planner_units(path, base) else []
        refs = [[f"{path}::{n}" for n in g] for g in groups] or [[path]]
        changes += [{"units": r, "goal": "make the gold change in " + ", ".join(r)} for r in refs]
    changes += [{"units": [p], "goal": f"create {p}"} for p in sorted(ex.context.new_files)]
    return {"changes": changes, "interfaces": [], "rationale": "one change per touched unit group (dry run)"}


def packed_lanes(ex, changes: dict[str, Any], max_lanes: int = 8) -> dict[str, dict[str, Any]]:
    """lane id -> {"units", "files"} of the kernel's packing of a change list (as run_la gets it)."""
    from .lanes import parse_plan

    got = parse_plan("```json\n" + json.dumps(changes) + "\n```", ex, ex.test_split, max_lanes=max_lanes,
                     symbol_lanes=True)
    if got.plan is None:
        raise ValueError(f"the dry change list does not parse: {got.errors}")
    return {ln.lane_id: {"units": list(ln.units), "files": [*(f for f in ln.allowed if f not in ln.unit_paths),
                                                          *ln.new_files]} for ln in got.plan.lanes}


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
    patch = unified_patch({p: ex.context.files[p] for p in mine}, mine) if mine else ""
    blocks = diff_to_blocks(patch, dict(ex.context.files)) if patch else []
    whole = set(lane.get("files", []))  # files owned whole or created: exactly their gold blocks
    blocks += [b for b in diff_to_blocks(ex.task.patch, ex.context.files) if b.path in whole]
    return "Here are the changes for my lane.\n\n" + format_blocks(blocks)


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


def conflicting_block(ex, plan: dict[str, dict[str, Any]], lane_id: str) -> str:
    """One SEARCH/REPLACE block that breaks the first line of a unit another lane owns."""
    from .lanes import SPLIT_CLASS_LINES

    for lid, ln in plan.items():
        if lid == lane_id:
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
                changes = unit_plan(ex)
                plans[tid] = packed_lanes(ex, changes, getattr(self, "max_lanes", 8))
                return "```json\n" + json.dumps(changes, indent=1) + "\n```\n"
            m = self._LANE_LINE.search(prompt)
            if m is not None and tid in plans:
                lane = plans[tid].get(m.group(1))
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
