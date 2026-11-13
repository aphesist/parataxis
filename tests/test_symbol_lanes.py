"""Symbol-level lanes through arm La: two lanes share one file by units, a third creates a file; a
stray edit outside a lane's units is undone and counted; the planner sees large files' units."""

import json

from contraprova.harness.edits import diff_to_blocks, format_blocks, unified_patch
from contraprova.harness.swepro_arms import ProFakeClient
from contraprova.interfaces import Completion

from parataxis.lanes import LaneConfig, LOCAL_LADDER, _planner_context, parse_plan

from test_lanes import events_of, harness, make_ex

M_SRC = '''"""Two functions."""


def first(x):
    """One."""
    return x + 1  # first_marker


def second(y):
    """Two."""
    return y * 2  # second_marker
'''
ORIG = {"lib/m.py": M_SRC}
NEW = {"lib/m.py": M_SRC.replace("return x + 1", "return x + 10").replace("return y * 2", "return y * 20"),
       "lib/d.py": '"""Summaries."""\n\n\ndef summarize(items):\n    return len(items)\n'}
IID = "instance_ansible__ansible-" + "%040x" % 99 + "-vnan"

PLAN = {"lanes": [
    {"lane_id": "L1", "goal": "first", "units": ["lib/m.py::first"], "tests": []},
    {"lane_id": "L2", "goal": "second", "units": ["lib/m.py::second"], "tests": []},
    {"lane_id": "L3", "goal": "summaries", "files": ["lib/d.py"], "tests": []}],
    "interfaces": [], "rationale": "one lane per function"}


def only(change: str) -> dict:
    """The gold change of one unit (first or second) of lib/m.py."""
    if change == "first":
        return {"lib/m.py": M_SRC.replace("return x + 1", "return x + 10")}
    return {"lib/m.py": M_SRC.replace("return y * 2", "return y * 20")}


class Scripted(ProFakeClient):
    """The planner returns PLAN; each lane its unit's gold change. ``stray`` makes L1 also edit
    second(), outside its units."""

    def __init__(self, exercises, stray=False):
        super().__init__(exercises)
        self.stray = stray

    def _worker_text(self, tid, model, prompt):
        if "## Request: lane plan" in prompt:
            return "```json\n" + json.dumps(PLAN) + "\n```\n"
        lane = self._LANE_LINE.search(prompt).group(1)
        if lane == "L3":
            return format_blocks(diff_to_blocks(unified_patch({}, {"lib/d.py": NEW["lib/d.py"]}), {}))
        target = only("first" if lane == "L1" else "second")
        if lane == "L1" and self.stray:
            target = {"lib/m.py": target["lib/m.py"].replace("return y * 2", "return y * 999")}
        return format_blocks(diff_to_blocks(unified_patch(ORIG, target), ORIG))


def _run(tmp_path, stray):
    ex = make_ex(IID, orig=ORIG, new=NEW, interface="", f2p=["tests/test_m.py::test_first"])
    exercises = {IID: ex}
    cfg = LaneConfig(ladder=LOCAL_LADDER[:1] + LOCAL_LADDER[1:], max_lanes=8, symbol_lanes=True)
    from parataxis import local  # noqa: F401  (prices the local model)

    h, _, _ = harness(tmp_path, exercises, client=Scripted(exercises, stray), cfg=cfg)
    ok = h.run_task("La", ex, ex.test_split, "lanes-probe")
    h.log.verify()
    return h, ex, ok


def test_two_lanes_share_a_file_by_units_and_merge(tmp_path):
    h, ex, ok = _run(tmp_path, stray=False)
    assert ok
    planned = events_of(h, "lane.planned")[0]
    assert planned["k"] == 3 and planned["fallback"] is None
    units = {ln["lane_id"]: ln.get("units", []) for ln in planned["lanes"]}
    assert units == {"L1": ["lib/m.py::first"], "L2": ["lib/m.py::second"], "L3": []}
    merges = [m for m in events_of(h, "merge.decided") if m["mode"] == "governed"]
    assert merges[0]["verdict"] == "pass" and not merges[0].get("conflicts")
    l1 = [c for c in h.client.calls if "Lane: L1 of 3" in c["prompt"]][0]["prompt"]
    assert "first_marker" in l1 and "second_marker" not in l1  # its unit in full, the other outlined
    assert "[units] in this file you own only first" in l1


def test_a_stray_edit_outside_the_units_is_undone_and_counted(tmp_path):
    h, ex, ok = _run(tmp_path, stray=True)
    assert ok  # L2's own change to second() wins; L1's stray edit there is undone
    clashes = [c for c in events_of(h, "coordination.detected") if c["kind"] == "scope_violation"]
    assert clashes and clashes[0]["lanes"] == ["L1"] and clashes[0]["evidence"]["level"] == "unit"


def test_parse_plan_validates_units():
    ex = make_ex(IID, orig=ORIG, new=NEW, interface="", f2p=["tests/test_m.py::test_first"])
    ts = ex.test_split

    def parse(plan):
        return parse_plan("```json\n" + json.dumps(plan) + "\n```", ex, ts, max_lanes=8, symbol_lanes=True)

    assert parse(PLAN).plan is not None
    bad_unit = {**PLAN, "lanes": [dict(PLAN["lanes"][0], units=["lib/m.py::nope"]), *PLAN["lanes"][1:]]}
    assert any("no unit 'nope'" in e for e in parse(bad_unit).errors)
    twice = {**PLAN, "lanes": [dict(PLAN["lanes"][0], units=["lib/m.py::second"]), *PLAN["lanes"][1:]]}
    assert any("assigned to lanes L1, L2" in e for e in parse(twice).errors)
    both = {**PLAN, "lanes": [*PLAN["lanes"][:2], dict(PLAN["lanes"][2], files=["lib/d.py", "lib/m.py"])]}
    assert any("both owned whole" in e for e in parse(both).errors)
    off = parse_plan("```json\n" + json.dumps(PLAN) + "\n```", ex, ts, max_lanes=8)  # API-study mode: no units
    assert any("assigned to no lane" in e for e in off.errors)


def test_planner_sees_units_of_large_files_only_in_symbol_mode(tmp_path):
    big = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(60))
    ex = make_ex(IID, orig={"lib/m.py": big}, new={"lib/m.py": big.replace("return 3\n", "return 33\n")},
                 interface="", f2p=["tests/test_m.py::test_first"])
    h, _, _ = harness(tmp_path, {IID: ex})
    on = _planner_context(h, ex, ex.test_split, 8, True)
    off = _planner_context(h, ex, ex.test_split, 8, False)
    assert "lib/m.py::f3" in on and "Units (below file level)" in on and '"units"' in on
    assert "lib/m.py::f3" not in off and "Units (below file level)" not in off


def test_a_logged_plan_is_replayed_at_zero_tokens(tmp_path):
    from contraprova.pricing import DEFAULT_TABLE, PRICE_TABLES, request_cost

    from parataxis.local import PlanReplay

    h1, ex, ok = _run(tmp_path, stray=False)
    assert ok
    first = events_of(h1, "lane.planned")[0]

    class NoPlanner(Scripted):
        def _worker_text(self, tid, model, prompt):
            assert "## Request: lane plan" not in prompt, "the planner must not be called on a replay"
            return super()._worker_text(tid, model, prompt)

    exercises = {IID: ex}
    cfg = LaneConfig(ladder=LOCAL_LADDER, max_lanes=8, symbol_lanes=True)
    client = PlanReplay(NoPlanner(exercises), [str(tmp_path / "log.jsonl")])
    h2, _, _ = harness(tmp_path, exercises, client=client, cfg=cfg, name="replay.jsonl")
    assert h2.run_task("La", ex, ex.test_split, "lanes-probe")
    second = events_of(h2, "lane.planned")[0]
    assert second["plan_sha256"] == first["plan_sha256"] and client.replayed == 1
    planner = [u for u in events_of(h2, "usage.recorded") if u.get("lane_role") == "planner"]
    assert planner and planner[0]["replay"] is True
    assert request_cost(planner[0], PRICE_TABLES[DEFAULT_TABLE]) == 0.0
