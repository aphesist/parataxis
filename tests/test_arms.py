"""Arm L1 (one local worker, one retry on gate feedback) through the harness, offline."""

from contraprova.harness.swepro_arms import ProFakeClient

from parataxis import local  # noqa: F401  (prices the local model)
from parataxis.arms import L1_ARM, install
from parataxis.lanes import LOCAL_MODEL

from test_lanes import IDS, events_of, exercises, harness  # noqa: F401  (exercises is a fixture)


def _outcome(h):
    return [o for o in events_of(h, "outcome.scored") if o.get("arm") == L1_ARM][0]


def test_l1_solves_in_one_attempt(tmp_path, exercises):
    install()
    h, _, client = harness(tmp_path, exercises)
    ex = exercises[IDS[0]]
    assert h.run_task(L1_ARM, ex, ex.test_split, "lanes-probe")
    h.log.verify()
    o = _outcome(h)
    assert o["solved"] and o["shipped"] and o["attempts"] == 1
    assert {c["model"] for c in client.calls} == {LOCAL_MODEL}
    assert all(c["max_tokens"] == 8000 for c in client.calls)


def test_l1_retries_once_with_the_gate_feedback(tmp_path, exercises):
    install()
    seen = {"n": 0}

    def policy(tid, model, lane):
        seen["n"] += 1
        return "none" if seen["n"] == 1 else "gold"

    h, _, client = harness(tmp_path, exercises, client=ProFakeClient(exercises, policy=policy))
    ex = exercises[IDS[0]]
    assert h.run_task(L1_ARM, ex, ex.test_split, "lanes-probe")
    o = _outcome(h)
    assert o["attempts"] == 2 and o["solved"]
    retry = [c for c in client.calls if c["tags"].get("tier") == "local-retry"]
    assert retry and "rejected" in retry[0]["prompt"].lower()


def test_l1_unsolved_after_the_retry_is_not_shipped(tmp_path, exercises):
    install()
    h, _, _ = harness(tmp_path, exercises, client=ProFakeClient(exercises, solve=lambda i: False))
    ex = exercises[IDS[0]]
    assert not h.run_task(L1_ARM, ex, ex.test_split, "lanes-probe")
    o = _outcome(h)
    assert not o["shipped"] and not o["solved"] and o["attempts"] == 2


MARK = "----- everything above is shared by all lanes"


def test_lb_text_shares_one_prefix_and_feeds_the_board_to_the_next_round(tmp_path, exercises):
    from parataxis.arms import LB_ARM
    from parataxis.lanes import LOCAL_LADDER, LaneConfig

    install()
    first_l1 = {"n": 0}

    def policy(tid, model, lane):
        if lane and lane[0] == "L1":
            first_l1["n"] += 1
            return "none" if first_l1["n"] == 1 else "gold"
        return "gold"

    client = ProFakeClient(exercises, policy=policy)
    h, _, _ = harness(tmp_path, exercises, client=client, cfg=LaneConfig(ladder=LOCAL_LADDER, max_lanes=8))
    ex = exercises[IDS[0]]
    assert h.run_task(LB_ARM, ex, ex.test_split, "lanes-probe")
    h.log.verify()
    lanes = [c for c in client.calls if c["role"] == "worker"]
    round0 = lanes[:3]
    prefixes = {c["prompt"].split(MARK)[0] for c in round0}
    assert len(prefixes) == 1 and "(empty: this is the first round)" in prefixes.pop()
    later = [c for c in lanes[3:] if MARK in c["prompt"]]
    assert later and "### L2, round 0" in later[0]["prompt"].split(MARK)[0]  # peers' round-0 changes on the board
    arms = {o["arm"] for o in events_of(h, "outcome.scored")}
    assert {"Lb", "Lb-shadow", "Lb-first"} <= arms and "La" not in arms
    assert all(t.startswith("Lb:") for t in {e.payload["task_id"] for e in h.log.events() if e.type == "task.created"})
