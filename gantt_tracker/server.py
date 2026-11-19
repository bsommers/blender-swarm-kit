#!/usr/bin/env python3
"""
Zero-dependency HTTP server for the Collapsible Live Gantt Mission Control Tracker.

Usage:
  python3 -m gantt_tracker.server --root /path/to/project --port 8765
"""

from __future__ import annotations

import argparse
import http.server
import json
import mimetypes
import os
import socketserver
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_ALLOWED_PREFIXES = ("/work/", "/tracker/", "/output/", "/models/", "/out/", "/dist/")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(
    root: Path,
    state_path: Path,
    ui_path: Path,
    allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_PREFIXES,
):
    root_resolved = root.resolve()

    class TrackerHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send_bytes(self, data: bytes, content_type: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            if path in ("/", "/index.html"):
                return self._send_bytes(ui_path.read_bytes(), "text/html; charset=utf-8")

            if path == "/healthz":
                return self._send_bytes(b"ok", "text/plain; charset=utf-8")

            if path == "/api/state":
                try:
                    raw = state_path.read_bytes()
                except Exception as exc:
                    raw = json.dumps({"error": str(exc)}).encode("utf-8")
                return self._send_bytes(raw, "application/json; charset=utf-8")

            if any(path.startswith(prefix) for prefix in allowed_prefixes):
                rel = path.lstrip("/")
                # Resolve against the allowed base directory so symlinks inside allowed dirs still stay confined
                prefix_dir = rel.split("/", 1)[0]
                allowed_base = (root_resolved / prefix_dir).resolve()
                target = (root_resolved / rel).resolve()
                try:
                    target.relative_to(allowed_base)
                except ValueError:
                    return self._send_bytes(b"Forbidden", "text/plain", 403)
                if not target.is_file():
                    return self._send_bytes(b"Not found", "text/plain", 404)
                ctype, _ = mimetypes.guess_type(str(target))
                if not ctype:
                    if target.suffix.lower() in (".obj", ".mtl", ".jsonl"):
                        ctype = "text/plain; charset=utf-8"
                    else:
                        ctype = "application/octet-stream"
                return self._send_bytes(target.read_bytes(), ctype)

            return self._send_bytes(b"Not found", "text/plain", 404)

    return TrackerHandler


def build_server(
    root: str | Path | None = None,
    state_path: str | Path | None = None,
    ui_path: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_PREFIXES,
) -> ThreadingHTTPServer:
    root_p = Path(root or os.environ.get("GANTT_TRACKER_ROOT") or os.getcwd()).expanduser().resolve()
    state_p = (
        Path(state_path).expanduser().resolve()
        if state_path
        else Path(os.environ.get("GANTT_TRACKER_STATE") or (root_p / "work" / "tracker_state.json")).expanduser().resolve()
    )
    ui_p = Path(ui_path).expanduser().resolve() if ui_path else (Path(__file__).resolve().parent / "index.html")
    handler = make_handler(root_p, state_p, ui_p, allowed_prefixes=allowed_prefixes)
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Serve the Collapsible Live Gantt Mission Control Tracker.")
    p.add_argument("--root", default=os.environ.get("GANTT_TRACKER_ROOT") or os.getcwd())
    p.add_argument("--state", default=os.environ.get("GANTT_TRACKER_STATE"))
    p.add_argument("--ui", default=None, help="Optional custom index.html path")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args(argv)

    server = build_server(root=args.root, state_path=args.state, ui_path=args.ui, host=args.host, port=args.port)
    actual_port = server.server_address[1]
    print(f"Live Gantt Tracker running at http://{args.host}:{actual_port} (root={Path(args.root).resolve()})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
