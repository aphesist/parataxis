"""The local lane worker over HTTP: the vLLM client against the fake server, and a full arm La run
with local lanes (the planner faked offline), exercising the local ladder end to end. $0, no GPU."""

import pytest

from contraprova.harness.swepro_arms import ProFakeClient
from contraprova.interfaces import OPUS, Message
from contraprova.pricing import DEFAULT_TABLE, PRICE_TABLES, request_cost
from contraprova.projections import outcomes

from parataxis.fake_vllm import FakeVLLM
from parataxis.lanes import LOCAL_LADDER, LOCAL_LANE_MAX_TOKENS, LOCAL_MODEL, LaneConfig
from parataxis.local import KEY_ENV, LocalError, LocalRoleClients, VLLMClient

from test_lanes import IDS, events_of, exercises, harness  # noqa: F401  (exercises is a fixture)

KEY = "test-key-not-a-secret"


@pytest.fixture()
def keyed(monkeypatch):
    monkeypatch.setenv(KEY_ENV, KEY)


def test_client_streams_counts_and_reports_truncation(keyed):
    with FakeVLLM(lambda m, msgs, n: "x" * 400, key=KEY) as fake:
        c = VLLMClient(fake.url, sleep=lambda s: None)
        done = c.complete(model=LOCAL_MODEL, system="sys", messages=[Message("user", "hello")], max_tokens=1000,
                          tags={"role": "worker", "arm": "La"})
        assert done.text == "x" * 400 and done.stop_reason == "end_turn" and done.model == LOCAL_MODEL
        assert done.usage["output_tokens"] == 100 and done.usage["role"] == "worker" and done.usage["engine"] == "vllm"
        assert fake.requests[0]["chat_template_kwargs"] == {"enable_thinking": False}
        assert fake.requests[0]["stream"] is True and fake.requests[0]["temperature"] == 0.7
        cut = c.complete(model=LOCAL_MODEL, system="", messages=[Message("user", "hi")], max_tokens=10)
        assert cut.stop_reason == "max_tokens" and len(cut.text) == 40
        assert c.count_tokens(model=LOCAL_MODEL, system="sys", messages=[Message("user", "hello")]) == 2
    assert KEY not in repr(c)


def test_client_refuses_a_wrong_key_and_cloud_models(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "wrong")
    with FakeVLLM(key=KEY) as fake:
        c = VLLMClient(fake.url, sleep=lambda s: None)
        with pytest.raises(LocalError, match="401"):
            c.complete(model=LOCAL_MODEL, system="", messages=[Message("user", "hi")], max_tokens=10)
        with pytest.raises(ValueError):
            c.complete(model=OPUS, system="", messages=[Message("user", "hi")], max_tokens=10)
    assert fake.unauthorized == 1


def test_local_tokens_cost_nothing():
    assert request_cost({"model": LOCAL_MODEL, "input_tokens": 10**6, "output_tokens": 10**6},
                        PRICE_TABLES[DEFAULT_TABLE]) == 0.0


def _responder(offline, fail_first_l1=False):
    """Lane requests over HTTP get their share of the gold patch (or, once, nothing for L1)."""
    seen = {"L1": 0}

    def responder(model, msgs, max_tokens):
        prompt = msgs[-1]["content"]
        m = offline._LANE_LINE.search(prompt)
        if fail_first_l1 and m and m.group(1) == "L1":
            seen["L1"] += 1
            if seen["L1"] == 1:
                return "I could not find a safe change."
        return offline._worker_text(offline._task_of(prompt), model, prompt)

    return responder


@pytest.mark.parametrize("fail_first_l1", [False, True])
def test_arm_la_runs_with_local_lanes_end_to_end(tmp_path, exercises, keyed, fail_first_l1):
    cfg = LaneConfig(ladder=LOCAL_LADDER, max_lanes=8, lane_max_tokens=LOCAL_LANE_MAX_TOKENS)
    offline = ProFakeClient(exercises, lanes_k=3)  # the planner (Opus) stays offline in a dry run
    responder = _responder(offline, fail_first_l1)
    with FakeVLLM(responder, key=KEY) as fake:
        client = LocalRoleClients(local=VLLMClient(fake.url, sleep=lambda s: None), cloud=offline)
        h, _, _ = harness(tmp_path, exercises, client=client, cfg=cfg)
        ex = exercises[IDS[0]]
        assert h.run_task("La", ex, ex.test_split, "lanes-probe")
    h.log.verify()
    usage = events_of(h, "usage.recorded")
    lanes = [u for u in usage if u["role"] == "worker"]
    assert lanes and all(u["model"] == LOCAL_MODEL and u["engine"] == "vllm" for u in lanes)
    assert all(u["model"] == OPUS for u in usage if u["role"] == "orchestrator")
    assert sum(request_cost(u, PRICE_TABLES[DEFAULT_TABLE]) for u in lanes) == 0.0
    tiers = {s.get("tier") for s in events_of(h, "task.submitted") if s.get("tier")}
    assert tiers == ({"local", "local-repair"} if fail_first_l1 else {"local"})
    assert outcomes(h.log.events())[("La", ex.id)]
    assert (len(fake.requests) > 3) if fail_first_l1 else (len(fake.requests) == 3)  # blame may re-run several lanes


def test_local_lanes_run_concurrently_and_log_the_same_events(tmp_path, exercises, keyed):
    import threading
    import time

    def run(concurrency, name):
        offline = ProFakeClient(exercises, lanes_k=3)
        gold = _responder(offline)
        state = {"now": 0, "max": 0}
        lock = threading.Lock()

        def slow(model, msgs, max_tokens):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.3)
            with lock:
                state["now"] -= 1
            return gold(model, msgs, max_tokens)

        cfg = LaneConfig(ladder=LOCAL_LADDER, max_lanes=8, lane_max_tokens=LOCAL_LANE_MAX_TOKENS,
                         concurrency=concurrency)
        with FakeVLLM(slow, key=KEY) as fake:
            client = LocalRoleClients(local=VLLMClient(fake.url, sleep=lambda s: None), cloud=offline)
            h, _, _ = harness(tmp_path, exercises, client=client, cfg=cfg, name=name)
            ex = exercises[IDS[0]]
            t0 = time.monotonic()
            assert h.run_task("La", ex, ex.test_split, "lanes-probe")
            wall = time.monotonic() - t0
        h.log.verify()
        kinds = [(e.type, e.payload.get("task_id")) for e in h.log.events()]
        return state["max"], wall, kinds

    serial_max, serial_wall, serial_kinds = run(1, "serial.jsonl")
    par_max, par_wall, par_kinds = run(3, "parallel.jsonl")
    assert serial_max == 1 and par_max == 3
    assert par_wall < serial_wall - 0.3
    assert par_kinds == serial_kinds  # same events, same order: the single writer is unchanged
