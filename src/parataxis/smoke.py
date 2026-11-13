"""The day-1 smoke test against a running vLLM endpoint (PREREGISTRATION.md, "day 1").

Checks, each recorded with its numbers:

1. ``models``: the endpoint lists the served model, and refuses a request without the key.
2. ``sanity``: a short coding prompt at concurrency 1 returns code (``def`` and ``return``), mostly
   printable text, and stops on its own.
3. ``sweep``: aggregate and per-stream decode tok/s at 1, 2, 4, 8 and 16 concurrent streams (512
   output tokens each, ``ignore_eos``), with the MTP acceptance rate over the sweep from vLLM's
   ``/metrics`` (accepted / draft tokens). MTP must accept something, if it is on.
4. ``long``: 8 concurrent streams with ~20K-token prompts and 1K outputs, the local track's worst
   lane shape: no request may fail, and preemptions are counted (any preemption fails the check;
   the fallback is fewer lanes or a 16K window).
5. ``prefix``: two requests sharing a long prefix; prefix-cache hits must rise, where vLLM exports
   the counter (otherwise the check is recorded as unverified, not failed).

Pass = 1, 2, 3 (MTP accepted > 0) and 4 all pass. The output never contains the key.
"""

from __future__ import annotations

import json
import string
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .local import VLLMClient
from .pod import SERVED_NAME, _http, metrics

SWEEP = (1, 2, 4, 8, 16)
FILLER = ("The quick brown fox jumps over the lazy dog while the compiler reports a warning about unused "
          "variables in module seven. ")


def _stream(client: VLLMClient, prompt: str, max_tokens: int, ignore_eos: bool) -> dict[str, Any]:
    body = {"model": SERVED_NAME, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}, **client.sampling}
    if ignore_eos:
        body["ignore_eos"] = True
    t0 = time.monotonic()
    try:
        resp = client._request("/v1/chat/completions", body)
        text, finish, usage, _ = client.read_stream(resp)
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        return {"ok": False, "error": type(exc).__name__, "wall_s": time.monotonic() - t0}
    wall = time.monotonic() - t0
    return {"ok": True, "text": text, "finish": finish, "wall_s": wall,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0)}


def _parallel(client: VLLMClient, prompts: list[str], max_tokens: int, ignore_eos: bool) -> dict[str, Any]:
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(prompts)) as pool:
        rows = list(pool.map(lambda p: _stream(client, p, max_tokens, ignore_eos), prompts))
    wall = time.monotonic() - t0
    ok = [r for r in rows if r["ok"]]
    out_tokens = sum(r["completion_tokens"] for r in ok)
    return {"n": len(prompts), "failed": len(rows) - len(ok), "wall_s": round(wall, 2),
            "aggregate_tok_s": round(out_tokens / wall, 1) if wall else 0.0,
            "per_stream_tok_s": round(sum(r["completion_tokens"] / r["wall_s"] for r in ok if r["wall_s"]) / max(len(ok), 1), 1),
            "prompt_tokens": max((r["prompt_tokens"] for r in ok), default=0)}


def _delta(after: dict[str, float], before: dict[str, float], *names: str) -> float | None:
    for n in names:
        if n in after:
            return after[n] - before.get(n, 0.0)
    return None


def run_smoke(url: str, key: str, *, mtp: bool = True, sweep: tuple[int, ...] = SWEEP, sweep_tokens: int = 512,
              long_prompt_tokens: int = 20_000, long_out: int = 1024) -> dict[str, Any]:
    client = VLLMClient(url, key=key, served_model=SERVED_NAME, max_retries=1)
    checks: dict[str, Any] = {}

    code_ok, body = _http(url + "/v1/models", key)
    code_nokey, _ = _http(url + "/v1/models", None)
    checks["models"] = {"pass": code_ok == 200 and SERVED_NAME in body and code_nokey in (401, 403),
                        "status": code_ok, "status_without_key": code_nokey}

    r = _stream(client, "Write a Python function add(a, b) that returns a + b. Reply with the code only.", 256, False)
    text = r.get("text", "")
    printable = sum(ch in string.printable for ch in text) / max(len(text), 1)
    checks["sanity"] = {"pass": bool(r["ok"] and "def" in text and "return" in text and printable > 0.95
                                     and r.get("finish") == "stop"),
                        "finish": r.get("finish"), "printable": round(printable, 3),
                        "completion_tokens": r.get("completion_tokens"), "error": r.get("error")}

    before = metrics(url, key)
    rows = [_parallel(client, [f"Count from 1 upwards in words, stream {i}." for i in range(n)], sweep_tokens, True)
            for n in sweep]
    after = metrics(url, key)
    accepted = _delta(after, before, "vllm:spec_decode_num_accepted_tokens_total", "vllm:spec_decode_num_accepted_tokens")
    drafted = _delta(after, before, "vllm:spec_decode_num_draft_tokens_total", "vllm:spec_decode_num_draft_tokens")
    rate = (accepted / drafted) if accepted is not None and drafted else None
    checks["sweep"] = {"pass": all(x["failed"] == 0 for x in rows) and (not mtp or (rate or 0) > 0),
                       "rows": rows, "mtp_on": mtp, "mtp_acceptance": None if rate is None else round(rate, 3),
                       "mtp_accepted": accepted, "mtp_drafted": drafted}

    before = metrics(url, key)
    reps = max(1, long_prompt_tokens * 4 // len(FILLER))
    longp = [f"Stream {i}. " + FILLER * reps + "\nSummarise the text above in one paragraph." for i in range(8)]
    lr = _parallel(client, longp, long_out, True)
    after = metrics(url, key)
    pre = _delta(after, before, "vllm:num_preemptions_total", "vllm:num_preemptions")
    checks["long"] = {"pass": lr["failed"] == 0 and not pre, **lr, "preemptions": pre}

    before = metrics(url, key)
    shared = FILLER * 400
    for tail in ("First question: what animal jumps?", "Second question: what reports a warning?"):
        _stream(client, shared + tail, 16, False)
    after = metrics(url, key)
    hits = _delta(after, before, "vllm:prefix_cache_hits_total", "vllm:prefix_cache_hits",
                  "vllm:gpu_prefix_cache_hits_total")
    checks["prefix"] = {"pass": None if hits is None else hits > 0, "hits": hits,
                        "note": "unverified: no prefix-cache counter exported" if hits is None else ""}

    failed = [k for k in ("models", "sanity", "sweep", "long") if not checks[k]["pass"]]
    return {"pass": not failed, "failed": failed, "checks": checks, "endpoint_kind": "runpod-proxy" if
            "proxy.runpod.net" in url else "other", "t": round(time.time())}


if __name__ == "__main__":  # pragma: no cover
    import os
    import sys

    print(json.dumps(run_smoke(sys.argv[1], os.environ["PARATAXIS_VLLM_KEY"]), indent=1))
