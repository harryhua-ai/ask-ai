import json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))

def behavior():
    try:
        with open(os.path.join(BASE, "behavior.json")) as f:
            return json.load(f)
    except Exception:
        return {"mode": "ok", "delay_ms": 0, "icon": "bubble-sparkle-fill", "shape": "round", "theme": "dark"}

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/widget/site-config":
            b = behavior()
            if b.get("delay_ms"):
                time.sleep(b["delay_ms"] / 1000.0)
            if b.get("mode") == "fail":
                return self._send(500, {"detail": "i33 forced failure"})
            return self._send(200, {
                "site_id": "i33-site", "display_name": "I33 Site",
                "welcome": "hello", "starters": [], "language": "en",
                "launcher_icon": b["icon"], "launcher_shape": b["shape"],
                "launcher_style": None, "launcher_theme": b["theme"],
            })
        path = os.path.normpath(os.path.join(BASE, u.path.lstrip("/")))
        if not path.startswith(BASE) or not os.path.isfile(path):
            return self._send(404, {"detail": "nf"})
        with open(path, "rb") as f:
            ctype = "text/css" if path.endswith(".css") else "application/javascript" if path.endswith(".js") else "text/html"
            return self._send(200, f.read(), ctype)

    def log_message(self, *a):
        pass

ThreadingHTTPServer(("127.0.0.1", 8907), H).serve_forever()
