"""The pod lifecycle against a fake RunPod API and a fake vLLM endpoint: create, wait, smoke, exec,
watchdog, terminate, reap, the GPU budget and the key handling. $0, nothing rented."""

import json
import os
import stat

import pytest

from parataxis import pod
from parataxis.fake_runpod import FakeRunPod
from parataxis.fake_vllm import FakeVLLM
from parataxis.smoke import run_smoke


CODE = "def add(a, b):\n    return a + b\n"


@pytest.fixture()
def dirs(tmp_path):
    return {"ledger": tmp_path / "pods" / "ledger.jsonl", "pod_dir": tmp_path / "pods"}


def test_create_writes_a_private_key_and_never_uses_stop(dirs):
    with FakeRunPod() as rp_fake:
        rp = pod.RunPod(rp_fake.url)
        pid = pod.create(rp, "parataxis-test", max_hours=1.0, **dirs)
        kp = pod.key_path(pid, dirs["pod_dir"])
        key = kp.read_text()
        assert len(key) >= 40 and stat.S_IMODE(os.stat(kp).st_mode) == 0o600
        body = rp_fake.calls[0][2]
        assert body["gpu"] == {"id": pod.GPU_5090, "count": 1} and body["ports"] == ["8000/http"]
        assert body["cloud"] == "COMMUNITY" and body["entrypoint"] == ["bash", "-lc"]
        assert body["env"]["VLLM_API_KEY"] == key
        assert key not in " ".join(body["cmd"])  # the key is never on a command line
        assert "--api-key" not in " ".join(body["cmd"])
        pod.terminate(rp, pid, ledger=dirs["ledger"], sleep=lambda s: None)
        assert pid not in rp_fake.pods
        assert not any("/stop" in c[1] or "/action" in c[1] for c in rp_fake.calls)
    spend = pod.ledger_spend(dirs["ledger"])
    assert spend["pods"][pid]["open"] is False


def test_create_refuses_past_the_cap_and_kills_an_overpriced_pod(dirs):
    with FakeRunPod(cost=9.0) as rp_fake:
        rp = pod.RunPod(rp_fake.url)
        with pytest.raises(pod.PodError, match="refused"):
            pod.create(rp, "parataxis-x", max_hours=20, cap_usd=10, **dirs)
        assert not rp_fake.pods
        with pytest.raises(pod.PodError, match="terminated at once"):
            pod.create(rp, "parataxis-x", max_hours=2, cap_usd=10, assumed_rate=0.5, **dirs)
        assert not rp_fake.pods  # created, then terminated because the real price passed the cap


def test_names_must_be_reapable():
    with pytest.raises(ValueError):
        pod.pod_body("smoke", "k")


def test_wait_smoke_exec_watchdog_and_reap(dirs, monkeypatch, tmp_path):
    with FakeRunPod() as rp_fake, FakeVLLM(lambda m, msgs, n: CODE, key=None, model=pod.SERVED_NAME) as vl:
        rp = pod.RunPod(rp_fake.url)
        pid = pod.create(rp, "parataxis-smoke", max_hours=1.0, **dirs)
        key = pod.key_path(pid, dirs["pod_dir"]).read_text()
        vl.key = key  # the fake endpoint now demands the pod's key
        ready = pod.wait_ready(rp, pid, url=vl.url, poll_s=0, sleep=lambda s: None, **dirs)
        assert ready["pod"] == pid

        out = run_smoke(vl.url, key, sweep=(1, 2), sweep_tokens=32, long_prompt_tokens=2000, long_out=32)
        assert out["pass"], out["failed"]
        assert out["checks"]["sweep"]["mtp_acceptance"] == 0.6
        assert out["checks"]["prefix"]["pass"] is True
        assert key not in json.dumps(out)

        env = pod.child_env(pid, url=vl.url, pod_dir=dirs["pod_dir"])
        assert env["PARATAXIS_VLLM_KEY"] == key and env["PARATAXIS_VLLM_URL"] == vl.url

        t = {"now": 1000.0}
        reason = pod.watchdog(rp, pid, idle_minutes=1, max_hours=1, url=vl.url, poll_s=0, created_at=1000.0,
                              sleep=lambda s: t.__setitem__("now", t["now"] + 30), clock=lambda: t["now"], **dirs)
        assert reason == "idle 1 min" and pid not in rp_fake.pods

        a = pod.create(rp, "parataxis-a", max_hours=0.5, **dirs)
        rp_fake.pods["other"] = {"id": "other", "name": "someone-else", "status": "RUNNING"}
        assert pod.reap(rp, ledger=dirs["ledger"]) == [a]
        assert "other" in rp_fake.pods  # only parataxis-* pods are reaped


def test_cli_create_prints_no_key(dirs, capsys):
    with FakeRunPod() as rp_fake:
        assert pod.main(["--api", rp_fake.url, "--ledger", str(dirs["ledger"]), "--pod-dir", str(dirs["pod_dir"]),
                         "create", "--name", "parataxis-cli", "--max-hours", "1"]) == 0
        printed = capsys.readouterr().out
        pid = json.loads(printed)["pod"]
        assert pod.key_path(pid, dirs["pod_dir"]).read_text() not in printed
        assert pod.main(["--api", rp_fake.url, "--ledger", str(dirs["ledger"]), "--pod-dir", str(dirs["pod_dir"]),
                         "terminate", "--pod", pid]) == 0
