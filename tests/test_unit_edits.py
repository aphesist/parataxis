"""The symbol-unit edit format (PREREGISTRATION.md b.6): locating units, expanding UNIT/AFTER blocks
into exact SEARCH/REPLACE blocks, the installed prompts, and L1 and La end to end over the fake vLLM."""

import pytest

from contraprova.harness.edits import EDIT_FORMAT, apply_edits, parse_edits
from contraprova.harness.swepro_arms import ProFakeClient, ProHarness

from parataxis import unit_edits as ue
from parataxis.unit_edits import expand_unit_blocks, locate, strip_blocks, to_unit_reply

from test_lanes import exercises  # noqa: F401  (a fixture)

PY = '''"""A module."""
import os

LIMIT = 3


@cache
def alpha(x):
    """Alpha."""
    return x + 1


class Box:
    size = 2

    def open(self):
        return "open"

    @property
    def label(self):
        return "box"

    class Inner:
        def peek(self):
            return 1


if os.name == "nt":
    def beta():
        return "nt"
'''

JS = '''/**
 * The hash helpers.
 */
function top(a) {
    return a + 1;
}

class Store {
    constructor() {
        this.x = 1;
    }

    get(key) {
        return this.x;
    }
}

module.exports = function (Hash) {
    Hash.incrObjectFieldBy = async function (key, field) {
        return key + field;
    };
};
'''


def span_text(src, got):
    return "\n".join(src.split("\n")[got[0] - 1:got[1]])


def apply_reply(text, files):
    x = expand_unit_blocks(text, files)
    p = parse_edits(x.text)
    a = apply_edits(p.blocks, files)
    return {**files, **a.files}, list(x.errors + p.errors + a.errors), x


# ------------------------------------------------------------------ locate


@pytest.mark.parametrize("name, first, last", [
    ("alpha", "@cache", "    return x + 1"),
    ("Box", "class Box:", "            return 1"),
    ("Box.open", "    def open(self):", '        return "open"'),
    ("Box.label", "    @property", '        return "box"'),
    ("Box.Inner.peek", "        def peek(self):", "            return 1"),
    ("beta", "    def beta():", '        return "nt"'),
])
def test_python_units_run_from_the_first_decorator_to_the_last_line(name, first, last):
    got = locate("m.py", PY, name)
    assert not isinstance(got, str), got
    lines = span_text(PY, got).split("\n")
    assert lines[0] == first and lines[-1] == last


@pytest.mark.parametrize("name, first, last", [
    ("top", "function top(a) {", "}"),
    ("Store.get", "    get(key) {", "    }"),
    ("Hash.incrObjectFieldBy", "    Hash.incrObjectFieldBy = async function (key, field) {", "    };"),
])
def test_js_units_exclude_comments_above_and_find_assigned_names(name, first, last):
    got = locate("h.js", JS, name)
    assert not isinstance(got, str), got
    lines = span_text(JS, got).split("\n")
    assert lines[0] == first and lines[-1] == last


@pytest.mark.parametrize("path, name, says", [
    ("m.py", "gamma", "no function, method or class named 'gamma'"),
    ("m.py", "Box.shut", "at Box"),
    ("m.yml", "x", "SEARCH/REPLACE"),
    ("m.py", "", "no unit name"),
])
def test_unresolvable_names_explain_why(path, name, says):
    got = locate(path, PY, name)
    assert isinstance(got, str) and says in got


# ------------------------------------------------------------------ expand


def test_unit_replaces_the_whole_unit_and_keeps_everything_else():
    files = {"m.py": PY}
    reply = "Done.\n<<<<<<< UNIT m.py::Box.open\n    def open(self):\n        return 'opened'\n>>>>>>> END\n"
    new, errors, x = apply_reply(reply, files)
    assert errors == [] and x.unit_blocks == 1 and x.refs == ("m.py::Box.open",)
    assert new["m.py"] == PY.replace('        return "open"', "        return 'opened'")


def test_after_inserts_below_the_unit_and_merges_with_a_unit_block():
    files = {"m.py": PY}
    reply = ("<<<<<<< UNIT m.py::alpha\ndef alpha(x):\n    return x + 2\n>>>>>>> END\n"
             "<<<<<<< AFTER m.py::alpha\ndef gamma():\n    return 0\n>>>>>>> END\n")
    new, errors, _ = apply_reply(reply, files)
    assert errors == []
    assert "def alpha(x):\n    return x + 2\n\ndef gamma():\n    return 0\n\n\nclass Box:" in new["m.py"]
    assert "@cache" not in new["m.py"]  # the decorator belongs to the unit the block replaced


def test_an_empty_unit_body_deletes_the_unit():
    new, errors, _ = apply_reply("<<<<<<< UNIT m.py::Box.Inner\n>>>>>>> END\n", {"m.py": PY})
    assert errors == [] and "Inner" not in new["m.py"] and "def label" in new["m.py"]


def test_search_blocks_pass_through_in_order():
    reply = ("<<<<<<< SEARCH m.py\nLIMIT = 3\n=======\nLIMIT = 4\n>>>>>>> REPLACE\n"
             "<<<<<<< UNIT m.py::alpha\ndef alpha(x):\n    return x\n>>>>>>> END\n")
    new, errors, x = apply_reply(reply, {"m.py": PY})
    assert errors == [] and "LIMIT = 4" in new["m.py"] and "    return x\n" in new["m.py"]
    assert x.text.index("LIMIT = 4") < x.text.index("return x\n")


def test_js_unit_inside_a_wrapper_function():
    reply = ("<<<<<<< UNIT h.js::Hash.incrObjectFieldBy\n    Hash.incrObjectFieldBy = async function (key, field) {\n"
             "        return key * field;\n    };\n>>>>>>> END\n")
    new, errors, _ = apply_reply(reply, {"h.js": JS})
    assert errors == [] and "key * field" in new["h.js"] and "key + field" not in new["h.js"]


@pytest.mark.parametrize("reply, says", [
    ("<<<<<<< UNIT m.py::alpha\ndef alpha(x):\n", "block truncated"),
    ("<<<<<<< UNIT m.py::nope\nx\n>>>>>>> END\n", "units in this file: alpha, Box, beta"),
    ("<<<<<<< UNIT other.py::alpha\nx\n>>>>>>> END\n", "not one of the files shown"),
    ("<<<<<<< UNIT alpha\nx\n>>>>>>> END\n", "must be path::name"),
    ("<<<<<<< UNIT m.py::alpha\nx\n>>>>>>> END\n<<<<<<< UNIT m.py::alpha\ny\n>>>>>>> END\n", "already replaced"),
    ("<<<<<<< UNIT m.py::Box\nx\n>>>>>>> END\n<<<<<<< UNIT m.py::Box.open\ny\n>>>>>>> END\n", "overlaps"),
])
def test_bad_blocks_are_dropped_with_an_error_naming_the_ref(reply, says):
    x = expand_unit_blocks(reply, {"m.py": PY})
    assert any(says in e for e in x.errors), x.errors


def test_a_repeated_unit_text_gets_context_from_above():
    files = {"k.py": "class K:\n    def f(self):\n        return 1\n\n\nclass L:\n    def f(self):\n        return 1\n"}
    reply = "<<<<<<< UNIT k.py::L.f\n    def f(self):\n        return 2\n>>>>>>> END\n"
    new, errors, x = apply_reply(reply, files)
    assert errors == [] and "class L:\n" in x.text.split("=======")[0]
    assert new["k.py"] == files["k.py"][:-len("return 1\n")] + "return 2\n"


def test_a_unit_at_the_end_of_a_file_without_final_newline():
    files = {"n.py": "X = 1\n\n\ndef last():\n    return 1"}
    new, errors, _ = apply_reply("<<<<<<< UNIT n.py::last\ndef last():\n    return 9\n>>>>>>> END\n", files)
    assert errors == [] and new["n.py"] == "X = 1\n\n\ndef last():\n    return 9"


def test_strip_blocks_leaves_the_notes():
    reply = ("I changed alpha.\n<<<<<<< UNIT m.py::alpha\nx\n>>>>>>> END\n"
             "<<<<<<< SEARCH m.py\na\n=======\nb\n>>>>>>> REPLACE\nRelies on Box.\n<<<<<<< AFTER m.py::Box\ncut off")
    assert strip_blocks(reply).split() == ["I", "changed", "alpha.", "Relies", "on", "Box."]


def test_gold_replies_round_trip_through_unit_blocks():
    files = {"m.py": PY, "h.js": JS}
    new_py = PY.replace('return "open"', 'return "opened"').replace("return x + 1", "return x + 10")
    new_py = new_py.replace("LIMIT = 3", "LIMIT = 5")
    new_js = JS.replace("return this.x;", "return this.x + key;")
    reply = ("<<<<<<< SEARCH m.py\nLIMIT = 3\n=======\nLIMIT = 5\n>>>>>>> REPLACE\n"
             "<<<<<<< SEARCH m.py\n    return x + 1\n=======\n    return x + 10\n>>>>>>> REPLACE\n"
             '<<<<<<< SEARCH m.py\n        return "open"\n=======\n        return "opened"\n>>>>>>> REPLACE\n'
             "<<<<<<< SEARCH h.js\n        return this.x;\n=======\n        return this.x + key;\n>>>>>>> REPLACE\n")
    units_reply = to_unit_reply(reply, files)
    assert units_reply.count("<<<<<<< UNIT") == 3 and units_reply.count("<<<<<<< SEARCH") == 1
    new, errors, _ = apply_reply(units_reply, files)
    assert errors == [] and new == {"m.py": new_py, "h.js": new_js}


# ------------------------------------------------------------------ installed


@pytest.fixture()
def units_installed():
    import parataxis.lanes as lanes

    before = (ProHarness.worker_system, lanes.LANE_SYSTEM, ProHarness.__dict__["_work"])
    ue.install()
    yield
    ue.uninstall()
    assert (ProHarness.worker_system, lanes.LANE_SYSTEM, ProHarness.__dict__["_work"]) == before


def test_install_swaps_the_prompts_and_uninstall_restores_them(units_installed):
    import parataxis.lanes as lanes
    from contraprova.harness import swepro_arms as sa

    for system in (ProHarness.worker_system, lanes.LANE_SYSTEM):
        assert ue.UNIT_EDIT_FORMAT in system and EDIT_FORMAT not in system
    assert "as edit blocks" in sa.PRO_WORKER_RETRY and "as edit blocks" in lanes.LANE_RETRY
    assert "SEARCH/REPLACE" not in sa.REPAIR_TRUNCATED + sa.REPAIR_ERRORS
    assert "Outside your edit blocks" in lanes.BOARD_LANE


def test_l1_and_la_run_end_to_end_in_unit_blocks(tmp_path, exercises, units_installed, monkeypatch):
    from contraprova.projections import outcomes

    from parataxis.arms import install as install_arms
    from parataxis.fake_vllm import FakeVLLM
    from parataxis.lanes import LOCAL_LADDER, LOCAL_LANE_MAX_TOKENS, LaneConfig
    from parataxis.local import KEY_ENV, LocalRoleClients, VLLMClient

    from test_lanes import IDS, events_of, harness  # noqa: F811

    monkeypatch.setenv(KEY_ENV, "test-key-not-a-secret")
    install_arms()
    offline = ue.unit_fake_client(ProFakeClient)(exercises, lanes_k=3)

    def responder(model, msgs, max_tokens):
        return offline._worker_text(offline._task_of(msgs[-1]["content"]), model, msgs[-1]["content"])

    cfg = LaneConfig(ladder=LOCAL_LADDER, max_lanes=8, lane_max_tokens=LOCAL_LANE_MAX_TOKENS)
    with FakeVLLM(responder, key="test-key-not-a-secret") as fake:
        client = LocalRoleClients(local=VLLMClient(fake.url, sleep=lambda s: None), cloud=offline)
        h, _, _ = harness(tmp_path, exercises, client=client, cfg=cfg)
        ex = exercises[IDS[0]]
        assert h.run_task("La", ex, ex.test_split, "lanes-probe")
        assert h.run_task("L1", ex, ex.test_split, "lanes-probe")
    h.log.verify()
    subs = [s for s in events_of(h, "task.submitted") if "original_failure" in s]  # worker replies, not merges
    assert subs and all(s["edit_format"] == "units" and s["final_failure"] is None for s in subs)
    assert sum(s["unit_blocks"] for s in subs) > 0 and all(s["unit_errors"] == [] for s in subs)
    assert all("<<<<<<< UNIT" in s["response"] for s in subs if s["unit_blocks"])
    got = outcomes(h.log.events())
    assert got[("La", ex.id)] and got[("L1", ex.id)]
    systems = {c["system"] for c in offline.calls if c["role"] != "orchestrator"}
    assert all(ue.UNIT_EDIT_FORMAT in s for s in systems if s)
