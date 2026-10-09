"""Start a minimal OpenAI-compatible stub server to exercise the model client.

This is not a model: it returns a canned reply. Its purpose is to exercise the
parts of the client that a real endpoint would exercise - URL handling, request
shape, response parsing, retry on a 5xx - without downloading weights or needing
a GPU. Never report its output as a model result.

    py -3 tools/stub_model_server.py --port 8765 [--fail-first N] [--require-token T]
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = """Here is the module.

```verilog
module TopModule (
  output zero
);

  assign zero = 1'b0;

endmodule
```
"""


class StubHandler(BaseHTTPRequestHandler):
    attempts = 0
    fail_first = 0
    require_token = ""
    model_name = "stub-coder"
    last_request: dict = {}

    def log_message(self, *args):  # silence the default stderr logging
        return

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            self._send(400, {"error": {"message": "body was not JSON"}})
            return
        type(self).last_request = request

        if type(self).require_token:
            expected = f"Bearer {type(self).require_token}"
            if self.headers.get("Authorization") != expected:
                self._send(401, {"error": {"message": "missing or wrong bearer token"}})
                return

        type(self).attempts += 1
        if type(self).attempts <= type(self).fail_first:
            self._send(503, {"error": {"message": "stub: transient failure"}})
            return

        if self.path != "/v1/chat/completions":
            self._send(404, {"error": {"message": f"unknown path {self.path}"}})
            return

        self._send(
            200,
            {
                "id": "stub-1",
                "object": "chat.completion",
                "model": request.get("model", type(self).model_name),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": REPLY},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 40, "total_tokens": 50},
            },
        )


def serve(port: int, fail_first: int = 0, require_token: str = "") -> tuple[ThreadingHTTPServer, threading.Thread]:
    StubHandler.fail_first = fail_first
    StubHandler.require_token = require_token
    StubHandler.attempts = 0
    server = ThreadingHTTPServer(("127.0.0.1", port), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--fail-first", type=int, default=0, help="Return 503 for the first N requests")
    parser.add_argument("--require-token", default="")
    args = parser.parse_args()

    server, _ = serve(args.port, args.fail_first, args.require_token)
    print(f"stub model server on http://127.0.0.1:{args.port}/v1  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
