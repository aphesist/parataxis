"""A fake OpenAI-compatible vLLM server for $0 dry runs: the same routes the local client uses
(``/health``, ``/v1/models``, ``/v1/chat/completions`` streamed, ``/tokenize``), bearer-key checks,
and a pluggable responder. Tokens are counted as characters / 4.

    python -m parataxis.fake_vllm --port 8000 --key-env PARATAXIS_VLLM_KEY [--reply "no change"]
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

Responder = Callable[[str, list[dict[str, str]], int], str]


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeVLLM:
    """Serve on 127.0.0.1:<port> in a background thread. ``responder(model, messages, max_tokens)``
    returns the reply text; a reply longer than ``max_tokens`` tokens is cut and reported as
    ``finish_reason: length``. ``requests`` records every chat request body."""

    def __init__(self, responder: Responder | None = None, *, key: str | None = None, model: str = "qwen3.8-27b",
                 port: int = 0, chunk_chars: int = 64):
        self.responder = responder or (lambda model, messages, max_tokens: "I could not find a safe change.")
        self.key = key
        self.model = model
        self.chunk_chars = chunk_chars
        self.requests: list[dict[str, Any]] = []
        self.unauthorized = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _auth(self) -> bool:
                if fake.key and self.headers.get("authorization") != "Bearer " + fake.key:
                    fake.unauthorized += 1
                    self._json(401, {"error": "unauthorized"})
                    return False
                return True

            def _json(self, code: int, obj: Any) -> None:
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.end_headers()
                    return
                if not self._auth():
                    return
                if self.path == "/v1/models":
                    self._json(200, {"data": [{"id": fake.model, "object": "model"}]})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                if not self._auth():
                    return
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                if body.get("model") != fake.model:
                    self._json(404, {"error": f"model {body.get('model')!r} not served"})
                    return
                msgs = body.get("messages") or []
                prompt_text = "".join(m.get("content", "") for m in msgs)
                if self.path == "/tokenize":
                    self._json(200, {"count": _tokens(prompt_text), "max_model_len": 32768})
                    return
                if self.path != "/v1/chat/completions":
                    self._json(404, {"error": "not found"})
                    return
                fake.requests.append(body)
                max_tokens = int(body.get("max_tokens") or 16)
                text = fake.responder(body["model"], msgs, max_tokens)
                finish = "stop"
                if _tokens(text) > max_tokens:
                    text, finish = text[: max_tokens * 4], "length"
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                rid = f"chatcmpl-fake-{len(fake.requests)}"
                for i in range(0, len(text), fake.chunk_chars):
                    chunk = {"id": rid, "choices": [{"index": 0, "delta": {"content": text[i:i + fake.chunk_chars]},
                                                     "finish_reason": None}]}
                    self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                self.wfile.write(b"data: " + json.dumps({"id": rid, "choices": [
                    {"index": 0, "delta": {}, "finish_reason": finish}]}).encode() + b"\n\n")
                usage = {"prompt_tokens": _tokens(prompt_text), "completion_tokens": _tokens(text),
                         "prompt_tokens_details": {"cached_tokens": 0}}
                self.wfile.write(b"data: " + json.dumps({"id": rid, "choices": [], "usage": usage}).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "FakeVLLM":
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--key-env", default="PARATAXIS_VLLM_KEY", help="require this env var's value as the bearer key")
    ap.add_argument("--model", default="qwen3.8-27b")
    ap.add_argument("--reply", default="I could not find a safe change.")
    args = ap.parse_args(argv)
    fake = FakeVLLM(lambda m, msgs, n: args.reply, key=os.environ.get(args.key_env) or None, model=args.model,
                    port=args.port)
    print(f"fake vllm on {fake.url}", flush=True)
    fake.server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
