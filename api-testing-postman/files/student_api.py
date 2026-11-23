#!/usr/bin/env python3
"""
CRUD Testing Exercise: Student Enrollment API
=========================================

Practice server for the Postman CRUD-testing exercise.
Standard-library Python 3.7+ only - nothing to install.

    python student_api.py            (Windows: py student_api.py)

Two builds of the same API start side by side:

    Build 1.0  ->  http://localhost:3000   (released build)
    Build 1.1  ->  http://localhost:3001   (release candidate)

Each build keeps its own in-memory data. Restarting the script, or sending
POST /reset, restores the starting data:

    {"id": 1001, "name": "Alice", "age": 20}
    {"id": 1002, "name": "Bob",   "age": 22}
    {"id": 1003, "name": "Chen",  "age": 19}

Endpoints
    POST   /students          create   -> 201 + student
    GET    /students/{id}     read     -> 200 + student
    PUT    /students/{id}     update   -> 200 + student
    DELETE /students/{id}     delete   -> 200 + message
    GET    /students          list all students (helper)
    POST   /reset             restore starting data (test fixture hook)

Rules
    id    integer 1-9999
    name  string, 1-40 characters
    age   integer 16-120
    Body must be valid JSON              -> otherwise 400
    Field missing / wrong type / range   -> 400
    POST with an id that already exists  -> 409
    Student does not exist (GET/PUT/DELETE) -> 404
    PUT body: "name" and "age" required; "id" optional but must match the URL

This is a black-box exercise: test the API through Postman only.

Options:  --port N   first port (default 3000); build 1.1 uses N+1
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEED = [
    {"id": 1001, "name": "Alice", "age": 20},
    {"id": 1002, "name": "Bob", "age": 22},
    {"id": 1003, "name": "Chen", "age": 19},
]


class ApiError(Exception):
    """Application error carrying the HTTP status and message to send to the client."""

    def __init__(self, status, message):
        """Store the HTTP status code and a JSON-ready error message."""
        super().__init__(message)
        self.status = status
        self.message = message


def _is_int(v):
    """Return True only for a real integer, excluding Python's bool values."""
    return isinstance(v, int) and not isinstance(v, bool)


class StudentStore:
    """In-memory data and CRUD operations for one build of the API.

    Each build has its own store and can deliberately implement slightly
    different validation or response behavior for the comparison exercise.
    """

    def __init__(self, build):
        """Initialize the build identifier, thread lock, and starting data."""
        self.build = build
        self.rc = build == "1.1"
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        """Replace all rows with fresh copies of the seed student records."""
        self.rows = {s["id"]: dict(s) for s in SEED}
        return len(self.rows)

    # ---- validation --------------------------------------------------
    def check_id(self, v):
        """Raise ApiError unless v is an integer in the allowed ID range."""
        if not _is_int(v) or not 1 <= v <= 9999:
            raise ApiError(400, "id must be an integer from 1 to 9999")

    def check_name(self, v, creating):
        """Validate a name's type and length for the current build and operation."""
        if not isinstance(v, str) or len(v) < 1:
            raise ApiError(400, "name must be a string of 1 to 40 characters")
        limit = 40 if (creating or not self.rc) else 255
        if len(v) > limit:
            raise ApiError(400, "name must be a string of 1 to 40 characters")

    def check_age(self, v, creating):
        """Validate age; build 1.1 intentionally differs when creating data."""
        top = 119 if (creating and self.rc) else 120
        if not _is_int(v) or not 16 <= v <= top:
            raise ApiError(400, "age must be an integer from 16 to 120")

    # ---- view --------------------------------------------------------
    def view(self, row):
        """Return a response copy of a row, applying build-specific formatting."""
        out = dict(row)
        if self.rc:
            out["age"] = str(out["age"])
        return out

    # ---- CRUD --------------------------------------------------------
    def create(self, body):
        """Validate and add a new student, or report a conflict/API error."""
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        for f in ("id", "name", "age"):
            if f not in body:
                raise ApiError(400, f"missing field: {f}")
        self.check_id(body["id"])
        self.check_name(body["name"], creating=True)
        self.check_age(body["age"], creating=True)
        with self.lock:
            if body["id"] in self.rows and not self.rc:
                raise ApiError(409, f"student {body['id']} already exists")
            row = {"id": body["id"], "name": body["name"], "age": body["age"]}
            self.rows[row["id"]] = row
            return dict(row)

    def read(self, sid):
        """Return one student by ID, or the build-specific missing-record result."""
        with self.lock:
            row = self.rows.get(sid)
        if row is None:
            if self.rc:
                return {}
            raise ApiError(404, f"student {sid} not found")
        return self.view(row)

    def list_all(self):
        """Return all students sorted by ID as independent dictionary copies."""
        with self.lock:
            return [dict(r) for r in sorted(self.rows.values(), key=lambda r: r["id"])]

    def update(self, sid, body):
        """Replace an existing student's name and age after validating the body."""
        with self.lock:
            if sid not in self.rows:
                raise ApiError(404, f"student {sid} not found")
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        for f in ("name", "age"):
            if f not in body:
                raise ApiError(400, f"missing field: {f}")
        if "id" in body and body["id"] != sid:
            raise ApiError(400, "id in body must match id in URL")
        self.check_name(body["name"], creating=False)
        self.check_age(body["age"], creating=False)
        with self.lock:
            row = {"id": sid, "name": body["name"], "age": body["age"]}
            self.rows[sid] = row
            return dict(row)

    def delete(self, sid):
        """Delete a student in build 1.0, or return a success-like result in build 1.1."""
        with self.lock:
            if sid not in self.rows:
                raise ApiError(404, f"student {sid} not found")
            if not self.rc:
                del self.rows[sid]
        return {"message": f"student {sid} deleted"}


def make_handler(store):
    """Create an HTTP request handler class bound to a particular StudentStore."""
    class Handler(BaseHTTPRequestHandler):
        """Handle HTTP routes and convert store/API errors into JSON responses."""
        server_version = f"StudentAPI/{store.build}"

        def log_message(self, fmt, *args):
            """Print a concise request log entry for the lab terminal."""
            print(f"[build {store.build}] {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

        def _send(self, status, payload):
            """Serialize payload as JSON and write an HTTP response."""
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            """Read and decode the request body, raising ApiError for invalid JSON."""
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ApiError(400, "request body is not valid JSON")

        def _route(self):
            """Parse the URL path into a root, reset, collection, or item route."""
            parts = [p for p in self.path.split("?")[0].split("/") if p]
            if parts == ["reset"]:
                return "reset", None
            if parts == ["students"]:
                return "collection", None
            if len(parts) == 2 and parts[0] == "students":
                try:
                    return "item", int(parts[1])
                except ValueError:
                    raise ApiError(400, "id in URL must be an integer")
            if not parts:
                return "root", None
            raise ApiError(404, "no such endpoint")

        def _handle(self, method):
            """Route a request method to the matching store operation and send JSON."""
            try:
                kind, sid = self._route()
                if kind == "root" and method == "GET":
                    return self._send(200, {
                        "service": "Student Enrollment API",
                        "build": store.build,
                        "endpoints": ["POST /students", "GET /students/{id}",
                                      "PUT /students/{id}", "DELETE /students/{id}",
                                      "GET /students", "POST /reset"],
                    })
                if kind == "reset" and method == "POST":
                    return self._send(200, {"message": "data reset", "count": store.reset()})
                if kind == "collection" and method == "POST":
                    return self._send(201, store.create(self._body()))
                if kind == "collection" and method == "GET":
                    return self._send(200, store.list_all())
                if kind == "item" and method == "GET":
                    return self._send(200, store.read(sid))
                if kind == "item" and method == "PUT":
                    with store.lock:
                        exists = sid in store.rows
                    if not exists:
                        raise ApiError(404, f"student {sid} not found")
                    return self._send(200, store.update(sid, self._body()))
                if kind == "item" and method == "DELETE":
                    return self._send(200, store.delete(sid))
                raise ApiError(405, f"{method} not allowed here")
            except ApiError as e:
                self._send(e.status, {"error": e.message})
            except Exception as e:  # Keep the lab server running even after unexpected errors.
                self._send(500, {"error": f"internal error: {e}"})

        def do_GET(self):
            """Dispatch an HTTP GET request."""
            self._handle("GET")

        def do_POST(self):
            """Dispatch an HTTP POST request."""
            self._handle("POST")

        def do_PUT(self):
            """Dispatch an HTTP PUT request."""
            self._handle("PUT")

        def do_DELETE(self):
            """Dispatch an HTTP DELETE request."""
            self._handle("DELETE")

        def do_PATCH(self):
            """Dispatch a PATCH request so it receives the standard 405 response."""
            self._handle("PATCH")

    return Handler


def main():
    """Parse the starting port, launch both API builds, and wait for shutdown."""
    ap = argparse.ArgumentParser(description="Student Enrollment API (CRUD testing lab)")
    ap.add_argument("--port", type=int, default=3000, help="port for build 1.0; build 1.1 uses port+1")
    args = ap.parse_args()

    # Start each build on a separate port with an independent StudentStore.
    servers = []
    for offset, build in ((0, "1.0"), (1, "1.1")):
        srv = ThreadingHTTPServer(("127.0.0.1", args.port + offset), make_handler(StudentStore(build)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)

    print("Student Enrollment API is running")
    print(f"  Build 1.0 (released)          http://localhost:{args.port}")
    print(f"  Build 1.1 (release candidate) http://localhost:{args.port + 1}")
    print("Press Ctrl+C to stop.\n")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopping...")
        for s in servers:
            s.shutdown()


if __name__ == "__main__":
    main()
