"""The local lane worker: a client for an OpenAI-compatible vLLM endpoint, and a role client that
sends local models there and every other model (the Opus planner) to the Claude API.

Run with contraprova's harness through ``python -m parataxis.run ... --client parataxis.local:LocalRoleClients``.

- **Endpoint.** ``PARATAXIS_VLLM_URL`` (e.g. ``https://<pod>-8000.proxy.runpod.net``) and the bearer
  key in ``PARATAXIS_VLLM_KEY``, generated per pod by :mod:`parataxis.pod` and never committed or
  logged. RunPod's HTTP proxy is public, so the key is the only protection.
- **Streaming.** RunPod's proxy (Cloudflare) cuts a request at 100 s; a lane writing 8K tokens at
  ~50 tok/s takes longer, so every completion is streamed (server-sent events keep the connection
  alive) and usage is taken from the final chunk (``stream_options.include_usage``).
- **Sampling.** Thinking off (``chat_template_kwargs.enable_thinking = false``) and fixed sampling
  parameters (:data:`SAMPLING`), part of the pre-registration.
- **Cost.** Local models are priced at $0 per token in contraprova's price table (registered on
  import), so La's dollar cost is the planner only; GPU time is accounted by :mod:`parataxis.pod`.
- **Token counts.** ``count_tokens`` for a local model uses vLLM's ``/tokenize`` with the chat
  template, i.e. the local tokenizer.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Sequence

from contraprova.interfaces import Completion, Message
from contraprova.pricing import DEFAULT_TABLE, PRICE_TABLES, ModelPrice
from contraprova.usage import usage_payload

from .lanes import LOCAL_MODEL, LOCAL_PREFIX, is_local

URL_ENV = "PARATAXIS_VLLM_URL"
KEY_ENV = "PARATAXIS_VLLM_KEY"
SERVED_ENV = "PARATAXIS_VLLM_MODEL"  # the --served-model-name on the pod; default: the part after "local:"
API_BUDGET_ENV = "PARATAXIS_API_BUDGET_USD"
# Qwen's recommended non-thinking sampling; pre-registered.
SAMPLING: dict[str, Any] = {"temperature": 0.7, "top_p": 0.8, "top_k": 20}
RETRYABLE = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524})


def register_local_price(model: str = LOCAL_MODEL) -> None:
    """Local tokens cost $0 in every price table (GPU time is a separate projection)."""
    for table in PRICE_TABLES.values():
        table.setdefault(model, ModelPrice(0.0, 0.0, 0.0))


register_local_price()


class LocalError(Exception):
    """The local endpoint failed, or retries ran out."""


class VLLMClient:
    """:class:`contraprova.interfaces.LLMClient` over an OpenAI-compatible vLLM server, via urllib."""

    def __init__(self, base_url: str | None = None, *, key_env: str = KEY_ENV, served_model: str | None = None,
                 timeout: float = 900.0, max_retries: int = 4, backoff_base: float = 2.0,
                 sampling: Mapping[str, Any] | None = None, opener: Callable[..., Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.base_url = (base_url or os.environ.get(URL_ENV, "")).rstrip("/")
        self.key_env = key_env
        self.served_model = served_model or os.environ.get(SERVED_ENV)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.sampling = dict(SAMPLING if sampling is None else sampling)
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep

    def __repr__(self) -> str:  # never anything key-related beyond the variable name
        return f"VLLMClient(base_url={self.base_url!r}, key_env={self.key_env!r})"

    # -- request construction (pure)

    def served(self, model: str) -> str:
        if not is_local(model):
            raise ValueError(f"VLLMClient serves local models only, got {model!r}")
        return self.served_model or model[len(LOCAL_PREFIX):]

    @staticmethod
    def chat_messages(system: str, messages: Sequence[Message]) -> list[dict[str, str]]:
        out = [{"role": "system", "content": system}] if system else []
        return out + [{"role": m.role, "content": m.content} for m in messages]

    def build_body(self, *, model: str, system: str, messages: Sequence[Message], max_tokens: int) -> dict[str, Any]:
        return {"model": self.served(model), "messages": self.chat_messages(system, messages),
                "max_tokens": int(max_tokens), "stream": True, "stream_options": {"include_usage": True},
                "chat_template_kwargs": {"enable_thinking": False}, **self.sampling}

    # -- transport

    def _request(self, path: str, body: Mapping[str, Any]):
        if not self.base_url:
            raise LocalError(f"no endpoint: set {URL_ENV}")
        key = os.environ.get(self.key_env, "")
        headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
        if key:
            headers["authorization"] = "Bearer " + key
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(), method="POST",
                                     headers=headers)
        attempt = 0
        while True:
            try:
                return self._open(req, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRYABLE or attempt >= self.max_retries:
                    raise LocalError(f"{path}: HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt >= self.max_retries:
                    raise LocalError(f"{path}: {type(exc).__name__}") from None
            attempt += 1
            self._sleep(self.backoff_base * (2 ** (attempt - 1)) * (0.5 + random.random() / 2))

    @staticmethod
    def read_stream(resp) -> tuple[str, str | None, dict[str, Any], str | None]:
        """(text, finish_reason, usage, response id) from an SSE chat-completions stream."""
        parts: list[str] = []
        finish, usage, rid = None, {}, None
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            rid = chunk.get("id") or rid
            for ch in chunk.get("choices") or []:
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    parts.append(delta["content"])
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
            if chunk.get("usage"):
                usage = chunk["usage"]
        return "".join(parts), finish, usage, rid

    # -- LLMClient

    def complete(self, *, model: str, system: str, messages: Sequence[Message], max_tokens: int,
                 effort: str | None = None, tags: Mapping[str, Any] | None = None) -> Completion:
        body = self.build_body(model=model, system=system, messages=messages, max_tokens=max_tokens)
        t0 = time.monotonic()
        resp = self._request("/v1/chat/completions", body)
        try:
            text, finish, usage, rid = self.read_stream(resp)
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
        wall = time.monotonic() - t0
        prompt = int(usage.get("prompt_tokens") or 0)
        cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        out = int(usage.get("completion_tokens") or 0)
        payload = usage_payload({"input_tokens": max(prompt - cached, 0), "cache_read_input_tokens": cached,
                                 "output_tokens": out}, model, **dict(tags or {}))
        payload.update({"engine": "vllm", "wall_s": round(wall, 3)})
        stop = {"length": "max_tokens", "stop": "end_turn"}.get(finish or "", finish or "end_turn")
        return Completion(text=text, model=model, usage=payload, stop_reason=stop, request_id=rid)

    def count_tokens(self, *, model: str, system: str, messages: Sequence[Message]) -> int:
        """Prompt tokens under the local tokenizer and chat template (vLLM ``/tokenize``)."""
        body = {"model": self.served(model), "messages": self.chat_messages(system, messages),
                "add_generation_prompt": True, "chat_template_kwargs": {"enable_thinking": False}}
        resp = self._request("/tokenize", body)
        try:
            got = json.loads(resp.read().decode())
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
        if "count" not in got:
            raise LocalError("/tokenize response has no count")
        return int(got["count"])


class LocalRoleClients:
    """Local models to :class:`VLLMClient`; any other model to the Claude API client for the request's
    role (``tags["role"]``), sharing one dollar budget (``PARATAXIS_API_BUDGET_USD``, default $2.5; the
    harness's own budget guard checks the log before every request as well)."""

    def __init__(self, local: Any | None = None, cloud: Any | None = None):
        self.local = local or VLLMClient()
        if cloud is None:
            from contraprova.harness.run import anthropic_role_clients
            from contraprova.llm import Budget

            cloud = anthropic_role_clients(Budget(float(os.environ.get(API_BUDGET_ENV, "2.5"))))
        self.cloud = cloud

    def complete(self, *, model: str, system: str, messages: Sequence[Message], max_tokens: int,
                 effort: str | None = None, tags: Mapping[str, Any] | None = None) -> Completion:
        target = self.local if is_local(model) else self.cloud
        return target.complete(model=model, system=system, messages=messages, max_tokens=max_tokens,
                               effort=effort, tags=tags)

    def count_tokens(self, *, model: str, system: str, messages: Sequence[Message]) -> int:
        if is_local(model):
            return self.local.count_tokens(model=model, system=system, messages=messages)
        cloud = getattr(self.cloud, "clients", {}).get("worker", self.cloud)
        return cloud.count_tokens(model=model, system=system, messages=messages)
