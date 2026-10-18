"""`python radar.py serve`: the dashboard with direct saving, on your own machine only.

Starts a small web server on 127.0.0.1 (never reachable from other devices) and opens the
dashboard in your browser. Every click (job status, delete with reason, application status,
details, new application) is written to data/ at once, and preferences.json is rebuilt, so
there is nothing to copy or sync. Stop it with Ctrl+C; the data stays in the files.

Safety: it binds to 127.0.0.1 only, accepts only requests addressed to localhost, and every
write needs a random token that is generated at start and embedded in the page it serves, so
another website open in your browser cannot send it changes. Writes wait while a collection
is running, so the two never overwrite each other.
"""
import datetime
import json
import secrets
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import applications, config, dashboard, feedback
from .collect import load_seen, lock_holder_alive, save_seen

MAX_BODY = 64 * 1024
WRITE_LOCK = threading.Lock()


class Server(ThreadingHTTPServer):
    """Refuses a port that is already taken. Python's default reuse option lets a second
    server share the port on Windows, where a stale or foreign process could then answer."""
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True

    def server_bind(self):
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def handle_write(path, body):
    """Apply one change and return the fresh page data. Raises ApiError on bad input."""
    if lock_holder_alive():
        raise ApiError(409, "a collection is running; try again when it finishes")
    today = datetime.date.today().isoformat()
    with WRITE_LOCK:
        data = load_seen()
        seen = data["seen"]
        rows = applications.load()
        try:
            if path == "/api/job":
                msg = feedback.mark_job(seen, rows, str(body.get("key", "")), str(body.get("status", "")), today)
                if msg.startswith(("NOT FOUND", "SKIPPED")):
                    raise ApiError(400, msg)
            elif path == "/api/job/delete":
                msg = feedback.delete_job(seen, str(body.get("key", "")), str(body.get("reason", ""))[:300], today)
                if msg.startswith("NOT FOUND"):
                    raise ApiError(400, msg)
            elif path == "/api/app":
                ident = str(body.get("id", ""))
                if body.get("fields"):
                    applications.update_fields(rows, ident, dict(body["fields"]), when=today)
                if body.get("status"):
                    row = applications.find(rows, ident)
                    stage = (body.get("fields") or {}).get("stage") if row and body.get("status") != row["status"] else None
                    applications.set_status(rows, ident, str(body["status"]), stage=stage or None, when=today)
            elif path == "/api/app/new":
                company, role = str(body.get("company", "")).strip(), str(body.get("role", "")).strip()
                if not company or not role:
                    raise ApiError(400, "company and role are needed")
                _, created = applications.create(rows, company, role, status=str(body.get("status") or "applied"),
                                                 source=str(body.get("source", "")), notes=str(body.get("notes", "")),
                                                 when=today)
                if not created:
                    raise ApiError(400, "this company + role is already tracked")
            else:
                raise ApiError(404, "unknown endpoint")
        except (KeyError, ValueError) as e:
            raise ApiError(400, str(e).strip("'\""))
        save_seen(data)
        applications.save(rows)
        feedback.build_prefs(seen, rows)
        return dashboard.payload(seen)


def make_handler(token, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _send(self, status, body, ctype="application/json; charset=utf-8"):
            raw = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, status, message):
            self._send(status, json.dumps({"error": message}))

        def _host_ok(self):
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._error(403, "forbidden host")
            if self.path in ("/", "/index.html"):
                return self._send(200, dashboard.render(dashboard.payload(), token), "text/html; charset=utf-8")
            return self._error(404, "not found")

        def do_POST(self):
            if not self._host_ok() or not secrets.compare_digest(self.headers.get("X-Radar-Token", ""), token):
                return self._error(403, "forbidden")
            if "application/json" not in self.headers.get("Content-Type", ""):
                return self._error(415, "send JSON")
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._error(413, "too large")
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._error(400, "invalid JSON")
            try:
                fresh = handle_write(self.path, body)
            except ApiError as e:
                return self._error(e.status, str(e))
            self._send(200, json.dumps(fresh, ensure_ascii=False))

    return Handler


def serve(args):
    config.get()  # fail early with a clear message if there is no profile
    token = secrets.token_urlsafe(24)
    try:
        server = Server(("127.0.0.1", args.port), make_handler(token, args.port))
    except OSError:
        raise SystemExit(f"Port {args.port} is already in use. Is Job Radar already open in another window? "
                         f"Close it, or run: python radar.py serve --port {args.port + 1}")
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Job Radar dashboard: {url}  (saves directly; Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
