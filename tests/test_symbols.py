"""Symbol-level lanes: units, lane views, packing and the scope gate. Pure; no contraprova."""

import pytest

from parataxis.symbols import (
    ELIDED,
    Span,
    blank_js,
    changed_lines,
    js_units,
    lane_view,
    plan_symbol_lanes,
    python_units,
    scope_violations,
    touched_units,
    units,
)

PY = '''"""Module."""
import os

LIMIT = 3


def alpha(x):
    return x + 1


@decorate
def beta(y):
    if y:
        return y
    return 0


class Gamma:
    """A class."""

    size = 2

    def one(self):
        return 1

    def two(self):
        return 2
'''

JS = '''import { thing } from "./thing";

const LIMIT = 3;

export function alpha(x) {
    const s = "a { brace in a string";
    return x + 1; // } in a comment
}

export const beta = async (y) => {
    return y;
};

/** Doc for Gamma. */
export class Gamma {
    constructor() {
        this.n = 1;
    }

    one() {
        return `tmpl ${"}"}`;
    }

    async two(a, b) {
        return a + b;
    }
}

Topics.getThing = async function (tid) {
    return tid;
};

module.exports = Topics;
'''


def names(spans):
    return [s.name for s in spans]


def test_python_units_whole_and_split_classes():
    assert names(python_units("m.py", PY)) == ["alpha", "beta", "Gamma"]
    beta = python_units("m.py", PY)[1]
    assert PY.split("\n")[beta.start - 1] == "@decorate"
    split = python_units("m.py", PY, split_class_lines=5)
    assert names(split) == ["alpha", "beta", "Gamma", "Gamma.one", "Gamma.two"]
    header, one, two = split[2:]
    assert header.kind == "class-header" and header.end == one.start - 1
    assert one.end == two.start - 1  # the blank line goes with the method above
    assert two.end == len(PY.rstrip("\n").split("\n"))


def test_js_blanking_keeps_lines_and_hides_braces():
    b = blank_js(JS)
    assert b.count("\n") == JS.count("\n")
    assert "brace in a string" not in b and "in a comment" not in b


def test_js_units_functions_arrows_classes_and_prototype_style():
    us = js_units("m.js", JS)
    assert names(us) == ["alpha", "beta", "Gamma", "Topics.getThing", "module.exports"]
    alpha = us[0]
    assert JS.split("\n")[alpha.end - 1] == "}"
    gamma = us[2]
    assert JS.split("\n")[gamma.start - 1].startswith("/**")  # doc comment included
    split = js_units("m.js", JS, split_class_lines=5)
    assert names(split)[2:6] == ["Gamma", "Gamma.constructor", "Gamma.one", "Gamma.two"]


def test_unparsable_or_unknown_files_split_into_line_blocks():
    assert names(units("x.py", "def (:\n")) == ["L1-1"]
    assert names(units("x.txt", "a\nb\n")) == ["L1-2"]
    yml = "\n".join(f"key{i}:\n  - a\n  - b\n" for i in range(60))  # 240 lines, blank every 4th
    us = units("conf.yml", yml, chunk_lines=60)
    assert len(us) == 4 and us[0].start == 1 and us[-1].end == len(yml.split("\n")) - 1
    assert all(60 <= u.lines <= 120 for u in us[:-1])
    dense = "\n".join("x" for _ in range(300))  # no blank line: hard cut at twice the size
    assert [u.lines for u in units("d.xml", dense, chunk_lines=60)] == [120, 120, 60]


def test_lane_view_shows_owned_in_full_and_outlines_the_rest():
    us = units("m.py", PY, split_class_lines=5)
    owned = [u for u in us if u.name == "Gamma.two"]
    view = lane_view("m.py", PY, owned, us)
    assert "return 2" in view  # owned body
    assert "return 1" not in view and "return x + 1" not in view  # other bodies elided
    assert "def alpha(x):" in view and "def one(self):" in view  # their first lines stay
    assert "import os" in view and "LIMIT = 3" in view  # module-level lines stay
    assert ELIDED in view
    assert len(view) < len(PY)


def test_plan_spreads_units_and_counts_shared_part():
    src = {"a.py": "\n\n".join(f"def f{i}():\n" + "    x = 1\n" * (10 * (i + 1)) for i in range(6)) + "\n"}
    us = units("a.py", src["a.py"])
    plan = plan_symbol_lanes(us, src, shared_tokens=1000, target_tokens=10_000, max_lanes=4)
    assert plan.k == 4 and plan.n_units == 6
    assert sorted(u.name for ln in plan.lanes for u in ln.owned) == sorted(u.name for u in us)
    assert all(ln.prompt_tokens > 1000 for ln in plan.lanes)
    assert plan.fits
    assert plan.largest_code_share < 0.5  # no lane holds most of the code
    one = plan_symbol_lanes(us[:1], src, shared_tokens=1000, max_lanes=8)
    assert one.k == 1


def test_plan_reports_a_lane_over_target():
    src = {"a.py": "def big():\n" + "    x = 1\n" * 4000}
    plan = plan_symbol_lanes(units("a.py", src["a.py"]), src, shared_tokens=4000, target_tokens=8000)
    assert plan.k == 1 and not plan.fits


def test_changed_lines_and_touched_units():
    new = PY.replace("return 2", "return 22").replace("    return x + 1\n", "    return x + 1\n\n\ndef helper():\n    pass\n")
    changed, inserts = changed_lines(PY, new)
    assert changed and inserts
    hit = touched_units("m.py", PY, changed, insert_points=inserts, split_class_lines=5)
    assert names(hit) == ["alpha", "Gamma.two"]


def test_scope_gate_accepts_owned_edits_and_helpers_below():
    us = units("m.py", PY, split_class_lines=5)
    owned = [u for u in us if u.name in ("alpha",)]
    new = PY.replace("return x + 1", "return x + 2").replace(
        "    return x + 2\n\n\n", "    return x + 2\n\n\ndef helper():\n    return 0\n\n\n")
    assert scope_violations(owned, {"m.py": PY}, {"m.py": new}) == []


def test_scope_gate_rejects_edits_outside_owned_spans():
    us = units("m.py", PY, split_class_lines=5)
    owned = [u for u in us if u.name == "alpha"]
    new = PY.replace("return 2", "return 3")
    v = scope_violations(owned, {"m.py": PY}, {"m.py": new})
    assert [x.what for x in v] == ["changed"]
    assert "outside" in v[0].reason()
    # a file with no owned span, and an unlisted new file
    v2 = scope_violations(owned, {"m.py": PY, "n.py": "x = 1\n"}, {"m.py": PY, "n.py": "x = 2\n", "new.py": "y"})
    assert sorted((x.path, x.what) for x in v2) == [("n.py", "file"), ("new.py", "file")]
    assert scope_violations(owned, {}, {"new.py": "y"}, new_files=["new.py"]) == []


@pytest.mark.parametrize("path,src", [("m.py", PY), ("m.js", JS)])
def test_units_never_overlap_and_stay_in_the_file(path, src):
    us = units(path, src, split_class_lines=5)
    n = len(src.split("\n"))
    for a, b in zip(us, us[1:]):
        assert a.end < b.start
    assert all(1 <= u.start <= u.end <= n for u in us)
    assert all(isinstance(u, Span) for u in us)


def test_restrict_keeps_owned_changes_and_undoes_the_rest():
    from parataxis.symbols import restrict_to_spans, spans_for

    owned = spans_for("m.py", PY, ["alpha"])
    new = (PY.replace("return x + 1", "return x + 2").replace("return 2", "return 3")
           .replace("    return x + 2\n\n\n", "    return x + 2\n\n\ndef helper():\n    return 0\n\n\n"))
    kept, rejected = restrict_to_spans(PY, new, owned)
    assert "return x + 2" in kept and "def helper" in kept  # own body and a helper right below
    assert "return 3" not in kept and "return 2" in kept  # another unit's change undone
    assert len(rejected) == 1


def test_merge_span_edits_combines_lanes_and_reports_overlaps():
    from parataxis.symbols import merge_span_edits

    a = PY.replace("return x + 1", "return x + 2")
    b = PY.replace("return 2", "return 22")
    merged, conflicts = merge_span_edits(PY, [("L1", a), ("L2", b)])
    assert "return x + 2" in merged and "return 22" in merged and not conflicts
    c = PY.replace("return x + 1", "return x * 9")
    merged2, conflicts2 = merge_span_edits(PY, [("L1", a), ("L2", c)])
    assert "return x + 2" in merged2 and "x * 9" not in merged2
    assert conflicts2 and conflicts2[0][:2] == ("L2", "L1")
    assert merge_span_edits(PY, [("L1", PY)]) == (PY, [])
