"""Symbol-level lanes through arm La: two lanes share one file by units, a third creates a file; a
stray edit outside a lane's units is undone and counted; the planner sees large files' units."""

import json

import pytest

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
    assert "lib/m.py::f3" in on and "## Files and units" in on and '"changes"' in on
    assert "lib/m.py::f3" not in off and "## Files and units" not in off


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


# ------------------------------------------------------------------ the lane count comes from the units

IMPORT_SRC = '"""Mod."""\nimport os\n\n\ndef first(x):\n    return x + 1\n\n\ndef second(y):\n    return y * 2\n'


def _ex(orig=None, new=None):
    orig = orig or {"lib/m.py": M_SRC}
    new = new or NEW
    return make_ex(IID, orig=orig, new=new, interface="", f2p=["tests/test_m.py::test_first"])


def _plan(*lanes):
    return "```json\n" + json.dumps({"lanes": list(lanes), "interfaces": [], "rationale": "r"}) + "\n```"


def _changes(*changes, interfaces=()):
    return "```json\n" + json.dumps({"changes": list(changes), "interfaces": list(interfaces), "rationale": "r"}) + "\n```"


def test_the_kernel_packs_one_lane_per_listed_change():
    ex = _ex()
    got = parse_plan(_changes({"units": ["lib/m.py::first"], "goal": "a", "provides": ["first(x)"]},
                              {"units": ["lib/m.py::second"], "goal": "b", "uses": ["first(x)"]},
                              {"units": ["lib/d.py"], "goal": "c"},
                              interfaces=[{"symbol": "first", "signature": "first(x) -> int", "path": "lib/m.py",
                                           "owner": "lib/m.py::first"}]),
                     ex, ex.test_split, max_lanes=8, symbol_lanes=True)
    assert got.plan is not None and got.plan.k == 3, got.errors
    by_unit = {u: ln.lane_id for ln in got.plan.lanes for u in (*ln.units, *ln.files)}
    assert len({by_unit["lib/m.py::first"], by_unit["lib/m.py::second"], by_unit["lib/d.py"]}) == 3
    first = got.plan.lane(by_unit["lib/m.py::first"])
    assert first.exports == ("first(x)",) and "lib/m.py::first: a" in first.goal
    assert [i.owner for i in got.plan.interfaces if i.symbol == "first"] == [first.lane_id]
    again = parse_plan(_changes({"units": ["lib/d.py"], "goal": "c"}, {"units": ["lib/m.py::second"], "goal": "b"},
                                {"units": ["lib/m.py::first"], "goal": "a"}), ex, ex.test_split, max_lanes=8,
                       symbol_lanes=True)
    assert again.plan.k == 3  # deterministic packing, whatever the order


def test_a_change_naming_several_units_stays_in_one_lane_and_the_count_is_capped():
    src = "\n\n".join(f"def f{i}(x):\n    return x + {i}\n" for i in range(12))
    ex = _ex({"lib/m.py": src}, {"lib/m.py": src.replace("return x + 1\n", "return x - 1\n")})
    many = [{"units": [f"lib/m.py::f{i}"], "goal": "g"} for i in range(2, 12)]
    got = parse_plan(_changes({"units": ["lib/m.py::f0", "lib/m.py::f1"], "goal": "move"}, *many), ex, ex.test_split,
                     max_lanes=8, symbol_lanes=True)
    assert got.plan is not None and got.plan.k == 8
    holder = [ln for ln in got.plan.lanes if "lib/m.py::f0" in ln.units]
    assert len(holder) == 1 and "lib/m.py::f1" in holder[0].units


@pytest.mark.parametrize("changes, says", [
    ([{"units": ["lib/m.py::nope"]}, {"units": ["lib/d.py"]}], "has no unit 'nope'"),
    ([{"units": ["lib/m.py::first"]}, {"units": ["lib/m.py::first"]}, {"units": ["lib/d.py"]}], "listed in changes 1 and 2"),
    ([{"units": ["lib/m.py::first"]}, {"units": ["tests/test_m.py"]}, {"units": ["lib/d.py"]}], "test file"),
    ([{"units": ["lib/m.py::first"]}], "assigned to no lane"),
    ([{"units": ["lib/m.py"]}, {"units": ["lib/m.py::first"]}, {"units": ["lib/d.py"]}], "both owned whole"),
    ([], "non-empty"),
])
def test_bad_change_lists_are_refused(changes, says):
    ex = _ex()
    got = parse_plan(_changes(*changes), ex, ex.test_split, max_lanes=8, symbol_lanes=True)
    assert got.plan is None and any(says in e for e in got.errors), got.errors


def test_module_lines_are_a_unit_a_lane_can_own(tmp_path):
    from parataxis.lanes import planner_units, restrict_lane_files

    new_src = IMPORT_SRC.replace("import os", "import os\nimport re").replace("return y * 2", "return re or y")
    ex = _ex({"lib/m.py": IMPORT_SRC}, {"lib/m.py": new_src})
    assert [n for n, _ in planner_units("lib/m.py", IMPORT_SRC)] == ["first", "second", "<module>"]
    got = parse_plan(_changes({"units": ["lib/m.py::<module>"], "goal": "import"},
                              {"units": ["lib/m.py::second"], "goal": "second"}),
                     ex, ex.test_split, max_lanes=8, symbol_lanes=True)
    assert got.plan is not None and got.errors == ()
    mod = next(ln for ln in got.plan.lanes if "lib/m.py::<module>" in ln.units)
    kept, rejected = restrict_lane_files(ex, mod, {"lib/m.py": new_src})
    assert "import re" in kept["lib/m.py"] and "return y * 2" in kept["lib/m.py"] and rejected
    h, _, _ = harness(tmp_path, {IID: ex})
    ctx = _planner_context(h, ex, ex.test_split, 8, True)
    assert "lib/m.py::<module>" in ctx and "Give each unit its own change" in ctx and "Use fewer lanes" not in ctx


def test_an_edit_to_a_unit_no_lane_owns_is_counted_as_unlisted(tmp_path):
    from parataxis.lanes import unowned_unit

    ex = _ex()
    plan = parse_plan(_changes({"units": ["lib/m.py::first"], "goal": "a"}, {"units": ["lib/d.py"], "goal": "d"}),
                      ex, ex.test_split, max_lanes=8, symbol_lanes=True).plan
    second_line = M_SRC.split("\n").index("    return y * 2  # second_marker") + 1
    assert unowned_unit(ex, plan, "lib/m.py", second_line) == "lib/m.py::second"
    assert unowned_unit(ex, plan, "lib/m.py", second_line - 7) is None  # first: owned


def test_plans_only_logs_the_plan_and_a_replayed_plan_costs_the_preflight_nothing(tmp_path, monkeypatch):
    from contraprova.harness.swepro_arms import ProFakeClient

    from parataxis import lanes

    ex = _ex()
    exercises = {IID: ex}
    cfg = LaneConfig(ladder=LOCAL_LADDER, max_lanes=8, symbol_lanes=True, plans_only=True)
    h, _, client = harness(tmp_path, exercises, client=Scripted(exercises), cfg=cfg)
    assert h.run_task("La", ex, ex.test_split, "lanes-probe") is False
    h.log.verify()
    assert len(events_of(h, "lane.planned")) == 1 and not events_of(h, "task.submitted")
    assert all("## Request: lane plan" in c["prompt"] for c in client.calls)  # the planner only
    count = lambda **kw: 1000  # noqa: E731
    paid = lanes.lane_preflight(h, ex, ex.test_split, count, LaneConfig(ladder=LOCAL_LADDER, symbol_lanes=True))
    monkeypatch.setenv("PARATAXIS_PLAN_REPLAY", str(tmp_path / "log.jsonl"))
    free = lanes.lane_preflight(h, ex, ex.test_split, count, LaneConfig(ladder=LOCAL_LADDER, symbol_lanes=True))
    assert paid.by_part["planner"] > 0 and free.by_part["planner"] == 0
