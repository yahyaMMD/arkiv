from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("arkiv")


def pick_folder_windows() -> str | None:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$b = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$b.Description = 'Choose the folder Arkiv should organize'; "
        "$b.ShowNewFolderButton = $true; "
        "if ($b.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
        "{ [Console]::Out.Write($b.SelectedPath) }"
    )
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except Exception as exc:
        log.exception("Folder picker failed")
        raise RuntimeError(f"Folder picker failed: {exc}") from exc
    path = (completed.stdout or "").strip()
    return path or None


def pick_folder_native(window) -> str | None:
    if window is not None:
        try:
            import webview

            dialog = getattr(webview, "FileDialog", None)
            kind = getattr(dialog, "FOLDER", None) if dialog else None
            if kind is None:
                kind = getattr(webview, "FOLDER_DIALOG")
            selected = window.create_file_dialog(kind)
            if selected:
                return selected[0]
            return None
        except Exception:
            log.exception("webview folder dialog failed")
    if sys.platform.startswith("win"):
        return pick_folder_windows()
    if sys.platform == "darwin":
        script = (
            'POSIX path of (choose folder with prompt "Choose the folder Arkiv should organize")'
        )
        completed = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        path = (completed.stdout or "").strip()
        return path or None
    return None


class ArkivRequestHandler(SimpleHTTPRequestHandler):
    api = None
    ui_dir: Path = Path(".")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.ui_dir), **kwargs)

    def log_message(self, format, *args):
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._dispatch("GET", parsed)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._dispatch("POST", parsed)
            return
        self.send_error(404)

    def _dispatch(self, method: str, parsed) -> None:
        api = self.api
        if api is None:
            self._json({"ok": False, "error": "API not ready"}, 503)
            return
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if method == "GET" and path == "/api/state":
                self._json(api.get_state())
                return
            if method == "GET" and path == "/api/files":
                category = (query.get("category") or [""])[0]
                self._json(api.list_files(category))
                return
            if method == "GET" and path == "/api/ping":
                self._json({"ok": True})
                return
            body = self._read_json() if method == "POST" else {}
            routes: dict[str, Callable[[], Any]] = {
                "/api/choose_folder": lambda: api.choose_folder(),
                "/api/confirm_library": lambda: api.confirm_library(str(body.get("path") or "")),
                "/api/start_sort": lambda: api.start_sort(),
                "/api/cancel_sort": lambda: api.cancel_sort(),
                "/api/undo_last": lambda: api.undo_last(),
                "/api/set_auto_sort": lambda: api.set_auto_sort(bool(body.get("enabled"))),
                "/api/set_model": lambda: api.set_model(str(body.get("model") or "")),
                "/api/set_api_key": lambda: api.set_api_key(str(body.get("key") or "")),
                "/api/test_connection": lambda: api.test_connection(),
                "/api/open_root": lambda: api.open_root(),
                "/api/open_category": lambda: api.open_category(str(body.get("name") or "")),
                "/api/reveal_file": lambda: api.reveal_file(str(body.get("path") or "")),
            }
            if method == "POST" and path in routes:
                self._json(routes[path]())
                return
            self._json({"ok": False, "error": f"Unknown API route: {path}"}, 404)
        except Exception as exc:
            log.exception("API error on %s", path)
            self._json({"ok": False, "error": str(exc)}, 500)


def start_server(api, ui_dir: Path) -> tuple[ThreadingHTTPServer, int]:
    ArkivRequestHandler.api = api
    ArkivRequestHandler.ui_dir = ui_dir
    server = ThreadingHTTPServer(("127.0.0.1", 0), ArkivRequestHandler)
    thread = threading.Thread(target=server.serve_forever, name="arkiv-http", daemon=True)
    thread.start()
    host, port = server.server_address
    log.info("Arkiv HTTP API on http://%s:%s", host, port)
    return server, int(port)
