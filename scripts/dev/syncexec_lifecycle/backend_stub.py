"""触发面替身(stdlib):等价 backend 容器职责 —— 只接收触发并写持久交接。

GET  /health   → 200 {"status":"ok"}
POST /trigger  → 202 {"status":"accepted","id":N};交接 = 持久写入
                 /plane/requests/req-<id>.json(生产对应 sync_requests 行)
"""

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REQ = Path("/plane/requests")
REQ.mkdir(parents=True, exist_ok=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/trigger":
            rid = int(time.time() * 1000)
            (REQ / f"req-{rid}.json").write_text(
                json.dumps({"id": rid, "source_id": "demo"})
            )
            body = json.dumps({"status": "accepted", "id": rid}).encode()
            self.send_response(202)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
