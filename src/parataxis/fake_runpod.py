"""A fake RunPod REST API v2 (``/v2/pods``: create, get, list, delete; the shapes of
https://api.runpod.io/v2/openapi.json) for $0 dry runs of the pod lifecycle. ``python -m parataxis.fake_runpod --port 8100`` serves it until killed."""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeRunPod:
    def __init__(self, cost=0.69, status="RUNNING", port=0):
        self.pods, self.calls, self.cost, self.status = {}, [], cost, status
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None):
                data = b"" if obj is None else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                fake.calls.append(("POST", self.path, body))
                if self.path != "/v2/pods":
                    return self._send(404)
                if not body.get("name") or not body.get("image") or "gpu" not in body:
                    return self._send(400, {"title": "name, image and gpu are required"})
                pid = f"pod{len(fake.pods) + 1}"
                fake.pods[pid] = {"id": pid, "name": body["name"], "status": fake.status, "cost": fake.cost,
                                  "env": body["env"], "cloud": body.get("cloud", "SECURE"),
                                  "entrypoint": body.get("entrypoint", []), "cmd": body.get("cmd", [])}
                self._send(201, fake.pods[pid])

            def do_GET(self):
                fake.calls.append(("GET", self.path, None))
                if self.path.split("?")[0] == "/v2/pods":
                    return self._send(200, {"pods": list(fake.pods.values()), "pagination": {"nextCursor": None}})
                pid = self.path.rsplit("/", 1)[-1]
                return self._send(200, fake.pods[pid]) if pid in fake.pods else self._send(404)

            def do_DELETE(self):
                fake.calls.append(("DELETE", self.path, None))
                fake.pods.pop(self.path.rsplit("/", 1)[-1], None)
                self._send(204)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v2"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()



def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--cost", type=float, default=0.69)
    a = ap.parse_args(argv)
    fake = FakeRunPod(cost=a.cost, port=a.port)
    print(f"fake runpod on {fake.url}", flush=True)
    fake.server.serve_forever()


if __name__ == "__main__":
    main()
