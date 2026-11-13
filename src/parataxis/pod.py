"""The rented GPU's lifecycle on RunPod: create, wait until vLLM serves, run, **terminate**.

    python -m parataxis.pod create  --name parataxis-smoke --max-hours 1.5 [--cloud COMMUNITY]
    python -m parataxis.pod wait    --pod <id>
    python -m parataxis.pod smoke   --pod <id> --out results/local-smoke/smoke.json
    python -m parataxis.pod exec    --pod <id> -- python -m parataxis.run --local ...   # endpoint in env
    python -m parataxis.pod watchdog --pod <id> --idle-minutes 10
    python -m parataxis.pod terminate --pod <id>
    python -m parataxis.pod reap                                # terminate every parataxis-* pod
    python -m parataxis.pod spend                               # GPU dollars so far, from the ledger

Rules this module enforces:

- **Terminate, never stop.** A stopped pod still bills its disk. There is no stop call here at all;
  ``terminate`` is ``DELETE /pods/{id}``, and it is checked afterwards.
- **A key per pod.** vLLM's ``--api-key`` (``VLLM_API_KEY`` in the pod's environment) is generated
  here with ``secrets``, written to ``runs/pods/<id>.key`` (mode 600, gitignored) and never printed
  or logged. RunPod's HTTP proxy is public, so the key is the endpoint's only protection. ``exec``
  hands it to a child process in ``PARATAXIS_VLLM_KEY``.
- **The RunPod API key is never handled.** It is a network secret: the environment's proxy injects
  the ``Authorization`` header into requests to RunPod's API. No header is sent from here (unless
  ``RUNPOD_API_KEY`` is set to a real value, which is not the plan).
- **A GPU budget.** Every pod's creation and termination go into ``runs/pods/ledger.jsonl`` with its
  hourly price; ``create`` refuses if the spend so far plus ``--max-hours`` x price would pass the
  cap (``--cap-usd``, default $10, the pre-registered base plan's kill switch).
- **Idle and lifetime limits.** ``watchdog`` terminates the pod after ``--idle-minutes`` with no
  request running or waiting in vLLM, at ``--max-hours`` after creation, or when the ledger reaches
  the cap. Inside the pod, a best-effort guard also deletes the pod at its maximum lifetime using
  the pod-scoped ``RUNPOD_API_KEY`` RunPod provides (unverified that this key may delete; the local
  watchdog is the guard that counts).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

API = "https://api.runpod.io/v2"  # RunPod REST API v2 (openapi: https://api.runpod.io/v2/openapi.json)
GPU_5090 = "NVIDIA GeForce RTX 5090"
PORT = 8000
POD_DIR = Path("runs/pods")
LEDGER = POD_DIR / "ledger.jsonl"
NAME_PREFIX = "parataxis-"
DEFAULT_CAP_USD = 10.0
# RunPod's API and its pod proxy sit behind Cloudflare, which refuses urllib's default User-Agent
# (error 1010); a plain client name is enough. It carries nothing about the user.
USER_AGENT = "parataxis/0.1"

# The serving configuration (pre-registered; the day-1 smoke test may fall back as PREREGISTRATION.md says).
# PREREGISTRATION.md named v0.27.2; that tag does not exist on Docker Hub (checked 2026-11-13), so its
# fallback 2 applies: the newest release tag at or above 0.27.2. v0.33.0 is built on CUDA 13.0
# (NVIDIA_REQUIRE_CUDA=cuda>=13.0), hence MIN_CUDA for the host.
DEFAULT_IMAGE = "vllm/vllm-openai:v0.33.0"
MIN_CUDA = "13.0"
DEFAULT_MODEL = "sakamakismile/Qwen3.8-27B-MTP-NVFP4"
SERVED_NAME = "qwen3.8-27b"


def vllm_args(model: str = DEFAULT_MODEL, *, max_model_len: int = 32768, max_num_seqs: int = 16,
              mtp_tokens: int | None = 3, mtp_method: str = "qwen3_5_mtp", gpu_util: float = 0.92) -> list[str]:
    """``vllm serve`` arguments. The API key comes from ``VLLM_API_KEY`` in the environment, never
    the command line. Recent vLLM does not log request contents by default; the smoke test checks
    the served flags rather than relying on a flag name that changes between versions."""
    args = ["--model", model, "--served-model-name", SERVED_NAME, "--host", "0.0.0.0", "--port", str(PORT),
            "--max-model-len", str(max_model_len), "--max-num-seqs", str(max_num_seqs),
            "--kv-cache-dtype", "fp8", "--enable-prefix-caching", "--gpu-memory-utilization", str(gpu_util),
            "--generation-config", "vllm"]
    if mtp_tokens:
        args += ["--speculative-config", json.dumps({"method": mtp_method, "num_speculative_tokens": mtp_tokens},
                                                    separators=(",", ":"))]
    return args


def start_script(serve_args: Sequence[str], max_seconds: int) -> str:
    """The pod's entry: the in-pod lifetime guard in the background, then vLLM in the foreground."""
    py = ("import os,urllib.request as u;u.urlopen(u.Request('https://api.runpod.io/v2/pods/'+os.environ['RUNPOD_POD_ID'],"
          "method='DELETE',headers={'Authorization':'Bearer '+os.environ.get('RUNPOD_API_KEY',''),"
          "'User-Agent':'parataxis/0.1'}),timeout=30)")
    guard = f"(sleep {int(max_seconds)}; python3 -c {shlex.quote(py)} >/dev/null 2>&1) &"
    return guard + " exec vllm serve " + " ".join(shlex.quote(a) for a in serve_args)


# ------------------------------------------------------------------ the RunPod REST client


class PodError(Exception):
    pass


@dataclass
class RunPod:
    base: str = API
    timeout: float = 60.0
    opener: Callable[..., Any] = urllib.request.urlopen

    def _req(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        headers = {"content-type": "application/json", "accept": "application/json", "user-agent": USER_AGENT}
        token = os.environ.get("RUNPOD_API_KEY", "")
        if token and token != "proxy-injected":  # normally unset: the environment's proxy adds the header
            headers["authorization"] = "Bearer " + token
        req = urllib.request.Request(self.base.rstrip("/") + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with self.opener(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise PodError(f"RunPod {method} {path}: HTTP {exc.code}") from None
        return json.loads(raw) if raw else {}

    def create(self, body: Mapping[str, Any]) -> dict[str, Any]:
        got = self._req("POST", "/pods", body)
        if not got or "id" not in got:
            raise PodError("RunPod create returned no pod id")
        return got

    def get(self, pod_id: str) -> dict[str, Any] | None:
        return self._req("GET", f"/pods/{pod_id}")

    def list(self) -> list[dict[str, Any]]:
        """Every pod, following v2's pagination (``pagination.nextCursor``)."""
        pods: list[dict[str, Any]] = []
        cursor = None
        while True:
            got = self._req("GET", "/pods" + (f"?cursor={urllib.parse.quote(cursor)}" if cursor else "")) or {}
            pods += list(got.get("pods") or [])
            cursor = (got.get("pagination") or {}).get("nextCursor")
            if not cursor:
                return pods

    def delete(self, pod_id: str) -> None:
        self._req("DELETE", f"/pods/{pod_id}")


def pod_body(name: str, key: str, *, image: str = DEFAULT_IMAGE, cloud: str = "COMMUNITY", disk_gb: int = 80,
             min_cuda: str | None = MIN_CUDA,
             serve_args: Sequence[str] | None = None, max_seconds: int = 5400,
             extra_env: Mapping[str, str] | None = None) -> dict[str, Any]:
    if not name.startswith(NAME_PREFIX):
        raise ValueError(f"pod names start with {NAME_PREFIX!r}, so reap can find them")
    if cloud not in ("COMMUNITY", "SECURE"):
        raise ValueError("cloud is COMMUNITY or SECURE")
    env = {"VLLM_API_KEY": key, "HF_HUB_ENABLE_HF_TRANSFER": "1", **dict(extra_env or {})}
    # v2 create body: name, image, gpu {id, count}, cloud, disk (container disk, GB), ports, env (object),
    # entrypoint and cmd in exec form (the entrypoint overrides the image's own)
    gpu = {"id": GPU_5090, "count": 1, **({"minCudaVersion": min_cuda} if min_cuda else {})}
    return {"name": name, "image": image, "gpu": gpu, "cloud": cloud,
            "disk": int(disk_gb), "ports": [f"{PORT}/http"], "env": env, "entrypoint": ["bash", "-lc"],
            "cmd": [start_script(serve_args or vllm_args(), max_seconds)]}


def endpoint(pod_id: str) -> str:
    return f"https://{pod_id}-{PORT}.proxy.runpod.net"


# ------------------------------------------------------------------ ledger and budget


def ledger_append(row: Mapping[str, Any], ledger: Path = LEDGER) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **row}, sort_keys=True) + "\n")


def ledger_spend(ledger: Path = LEDGER, now: float | None = None) -> dict[str, Any]:
    """GPU dollars per pod: (terminated, or now if still open) - created, times its hourly price."""
    now = time.time() if now is None else now
    pods: dict[str, dict[str, Any]] = {}
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            p = pods.setdefault(r["pod"], {"rate": 0.0, "start": None, "end": None})
            if r["event"] == "created":
                p.update(rate=float(r.get("cost_per_hr") or 0.0), start=r["t"])
            elif r["event"] == "terminated":
                p["end"] = r["t"]
    out = {}
    for pid, p in pods.items():
        if p["start"] is None:
            continue
        hours = ((p["end"] or now) - p["start"]) / 3600
        out[pid] = {"hours": round(hours, 4), "usd": round(hours * p["rate"], 4), "open": p["end"] is None}
    return {"pods": out, "usd": round(sum(v["usd"] for v in out.values()), 4)}


def key_path(pod_id: str, pod_dir: Path = POD_DIR) -> Path:
    return pod_dir / f"{pod_id}.key"


# ------------------------------------------------------------------ lifecycle


def create(rp: RunPod, name: str, *, max_hours: float, cap_usd: float = DEFAULT_CAP_USD, cloud: str = "COMMUNITY",
           assumed_rate: float = 0.99, ledger: Path = LEDGER, pod_dir: Path = POD_DIR, **body_kw) -> str:
    spent = ledger_spend(ledger)["usd"]
    if spent + max_hours * assumed_rate > cap_usd:
        raise PodError(f"refused: spend ${spent:.2f} + {max_hours} h x ${assumed_rate}/h would pass the ${cap_usd} cap")
    key = secrets.token_urlsafe(32)
    pod = rp.create(pod_body(name, key, cloud=cloud, max_seconds=int(max_hours * 3600), **body_kw))
    pid = str(pod["id"])
    kp = key_path(pid, pod_dir)
    kp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    rate = float(pod.get("cost") or assumed_rate)  # v2: the pod's hourly compute rate in USD
    ledger_append({"event": "created", "pod": pid, "name": name, "cost_per_hr": rate, "cloud": cloud,
                   "max_hours": max_hours, "image": body_kw.get("image", DEFAULT_IMAGE)}, ledger)
    if spent + max_hours * rate > cap_usd:  # the real price is higher than assumed
        terminate(rp, pid, ledger=ledger, reason="over the cap at the real price")
        raise PodError(f"terminated at once: the real price ${rate}/h passes the ${cap_usd} cap")
    return pid


def terminate(rp: RunPod, pod_id: str, *, ledger: Path = LEDGER, reason: str = "done", tries: int = 4,
              sleep: Callable[[float], None] = time.sleep) -> None:
    for i in range(tries):
        try:
            rp.delete(pod_id)
            got = rp.get(pod_id)
            if got is None or got.get("status") == "TERMINATED":
                ledger_append({"event": "terminated", "pod": pod_id, "reason": reason}, ledger)
                return
        except PodError:
            if i == tries - 1:
                raise
        sleep(2 ** i)
    raise PodError(f"pod {pod_id} still present after {tries} delete attempts: terminate it in the RunPod console")


def _http(url: str, key: str | None, timeout: float = 10.0, opener=urllib.request.urlopen) -> tuple[int, str]:
    headers = {"user-agent": USER_AGENT, **({"authorization": "Bearer " + key} if key else {})}
    try:
        with opener(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, ""


def wait_ready(rp: RunPod, pod_id: str, *, url: str | None = None, timeout_s: float = 2400, poll_s: float = 15,
               ledger: Path = LEDGER, pod_dir: Path = POD_DIR, sleep: Callable[[float], None] = time.sleep,
               clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """Until vLLM answers ``/health`` and lists the served model. Returns timings (the model download
    and load are most of it). On timeout the pod is terminated."""
    url = url or endpoint(pod_id)
    key = key_path(pod_id, pod_dir).read_text().strip()
    t0, running_at = clock(), None
    while clock() - t0 < timeout_s:
        pod = rp.get(pod_id)
        if pod is None or pod.get("status") in ("TERMINATED", "ERROR"):
            terminate(rp, pod_id, ledger=ledger, reason="error while starting") if pod is not None else None
            raise PodError(f"pod {pod_id} {'failed' if pod else 'disappeared'} while starting")
        if pod.get("status") == "RUNNING" and running_at is None:
            running_at = clock()
        if _http(url + "/health", None)[0] == 200:
            code, body = _http(url + "/v1/models", key)
            if code == 200 and SERVED_NAME in body:
                out = {"pod": pod_id, "running_s": round((running_at or clock()) - t0, 1),
                       "ready_s": round(clock() - t0, 1)}
                ledger_append({"event": "ready", **out}, ledger)
                return out
        sleep(poll_s)
    terminate(rp, pod_id, ledger=ledger, reason="not ready in time")
    raise PodError(f"pod {pod_id} not serving after {timeout_s} s; terminated")


_METRIC = re.compile(r"^(vllm:[a-z_]+)(?:\{[^}]*\})?\s+([0-9.eE+-]+)$", re.M)


def metrics(url: str, key: str | None, opener=urllib.request.urlopen) -> dict[str, float]:
    code, body = _http(url + "/metrics", key, opener=opener)
    out: dict[str, float] = {}
    if code == 200:
        for name, val in _METRIC.findall(body):
            out[name] = out.get(name, 0.0) + float(val)
    return out


def watchdog(rp: RunPod, pod_id: str, *, idle_minutes: float = 10, max_hours: float = 2.0,
             cap_usd: float = DEFAULT_CAP_USD, url: str | None = None, poll_s: float = 30,
             ledger: Path = LEDGER, pod_dir: Path = POD_DIR, sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], float] = time.time, created_at: float | None = None) -> str:
    """Terminate the pod on idle (counted from when vLLM first answers), at its maximum lifetime, or at
    the GPU cap. Returns the reason."""
    url = url or endpoint(pod_id)
    key = key_path(pod_id, pod_dir).read_text().strip()
    start = created_at or clock()
    last_busy = None  # the idle clock starts once vLLM answers: the model download is not idleness
    while True:
        if rp.get(pod_id) is None:
            return "gone"
        m = metrics(url, key)
        busy = m.get("vllm:num_requests_running", 0) + m.get("vllm:num_requests_waiting", 0)
        now = clock()
        if m and (busy > 0 or last_busy is None):
            last_busy = now
        reason = None
        if last_busy is not None and now - last_busy >= idle_minutes * 60:
            reason = f"idle {idle_minutes} min"
        elif now - start >= max_hours * 3600:
            reason = f"max lifetime {max_hours} h"
        elif ledger_spend(ledger, now)["usd"] >= cap_usd:
            reason = f"GPU cap ${cap_usd}"
        if reason:
            terminate(rp, pod_id, ledger=ledger, reason="watchdog: " + reason)
            return reason
        sleep(poll_s)


def reap(rp: RunPod, *, ledger: Path = LEDGER) -> list[str]:
    gone = []
    for pod in rp.list():
        if str(pod.get("name", "")).startswith(NAME_PREFIX) and pod.get("status") != "TERMINATED":
            terminate(rp, str(pod["id"]), ledger=ledger, reason="reap")
            gone.append(str(pod["id"]))
    return gone


def child_env(pod_id: str, *, url: str | None = None, pod_dir: Path = POD_DIR) -> dict[str, str]:
    env = dict(os.environ)
    env["PARATAXIS_VLLM_URL"] = url or endpoint(pod_id)
    env["PARATAXIS_VLLM_KEY"] = key_path(pod_id, pod_dir).read_text().strip()
    env["PARATAXIS_VLLM_MODEL"] = SERVED_NAME
    return env


# ------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m parataxis.pod", description=__doc__.split("\n")[0])
    ap.add_argument("--api", default=API, help=argparse.SUPPRESS)  # a fake RunPod API in dry runs
    ap.add_argument("--url", default=None, help="the pod's endpoint (default: RunPod's proxy URL)")
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--pod-dir", type=Path, default=POD_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--name", required=True)
    c.add_argument("--max-hours", type=float, required=True)
    c.add_argument("--cap-usd", type=float, default=DEFAULT_CAP_USD)
    c.add_argument("--cloud", default="COMMUNITY", choices=["COMMUNITY", "SECURE"])
    c.add_argument("--image", default=DEFAULT_IMAGE)
    c.add_argument("--model", default=DEFAULT_MODEL)
    c.add_argument("--mtp-tokens", type=int, default=3, help="0 serves without MTP (the fallback)")
    c.add_argument("--mtp-method", default="qwen3_5_mtp")
    c.add_argument("--max-model-len", type=int, default=32768)
    c.add_argument("--disk-gb", type=int, default=80)
    for name in ("wait", "terminate", "watchdog", "exec", "smoke", "window"):
        p = sub.add_parser(name)
        p.add_argument("--pod", required=True)
        if name == "watchdog":
            p.add_argument("--idle-minutes", type=float, default=10)
            p.add_argument("--max-hours", type=float, default=2.0)
            p.add_argument("--cap-usd", type=float, default=DEFAULT_CAP_USD)
        if name == "wait":
            p.add_argument("--timeout-s", type=float, default=2400)
        if name in ("smoke", "window"):
            p.add_argument("--out", type=Path, required=True)
        if name == "window":
            p.add_argument("--single-tokens", type=int, default=80_000)
            p.add_argument("--lane-tokens", type=int, default=22_000)
        if name == "exec":
            p.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("reap")
    sub.add_parser("spend")
    a = ap.parse_args(argv)
    rp = RunPod(a.api)
    if a.cmd == "create":
        pid = create(rp, a.name, max_hours=a.max_hours, cap_usd=a.cap_usd, cloud=a.cloud, image=a.image,
                     serve_args=vllm_args(a.model, max_model_len=a.max_model_len, mtp_tokens=a.mtp_tokens or None,
                                          mtp_method=a.mtp_method),
                     disk_gb=a.disk_gb, ledger=a.ledger, pod_dir=a.pod_dir)
        print(json.dumps({"pod": pid, "endpoint": a.url or endpoint(pid)}))
    elif a.cmd == "wait":
        print(json.dumps(wait_ready(rp, a.pod, url=a.url, timeout_s=a.timeout_s, ledger=a.ledger, pod_dir=a.pod_dir)))
    elif a.cmd == "terminate":
        terminate(rp, a.pod, ledger=a.ledger)
        print(json.dumps({"pod": a.pod, "terminated": True}))
    elif a.cmd == "watchdog":
        print(json.dumps({"pod": a.pod, "terminated": watchdog(rp, a.pod, idle_minutes=a.idle_minutes,
                                                                max_hours=a.max_hours, cap_usd=a.cap_usd, url=a.url,
                                                                ledger=a.ledger, pod_dir=a.pod_dir)}))
    elif a.cmd == "exec":
        cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
        return subprocess.call(cmd, env=child_env(a.pod, url=a.url, pod_dir=a.pod_dir))
    elif a.cmd == "smoke":
        from .smoke import run_smoke

        env = child_env(a.pod, url=a.url, pod_dir=a.pod_dir)
        out = run_smoke(env["PARATAXIS_VLLM_URL"], env["PARATAXIS_VLLM_KEY"])
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
        print(json.dumps({"pass": out["pass"], "failed": out["failed"]}))
        return 0 if out["pass"] else 4
    elif a.cmd == "window":
        from .smoke import run_window_check

        env = child_env(a.pod, url=a.url, pod_dir=a.pod_dir)
        out = run_window_check(env["PARATAXIS_VLLM_URL"], env["PARATAXIS_VLLM_KEY"], single_tokens=a.single_tokens,
                               lane_tokens=a.lane_tokens)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
        print(json.dumps({"pass": out["pass"], "single": out["single"]["prompt_tokens"],
                          "lanes": out["lanes"]["prompt_tokens"]}))
        return 0 if out["pass"] else 4
    elif a.cmd == "reap":
        print(json.dumps({"terminated": reap(rp, ledger=a.ledger)}))
    elif a.cmd == "spend":
        print(json.dumps(ledger_spend(a.ledger), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
