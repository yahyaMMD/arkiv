from __future__ import annotations

import logging
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _repair_stdio() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        folder = Path(sys.executable).resolve().parent / "data" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent / "data"
        folder.mkdir(parents=True, exist_ok=True)
        sys.stderr = open(folder / "launch.log", "a", encoding="utf-8")


_repair_stdio()

import webview

from arkiv.api import ArkivApi
from arkiv.paths import DATA_DIR, LOG_PATH, UI_DIR
from arkiv.service import LibraryService


class QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def log_message(self, format, *args):
        return


def serve_ui() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    threading.Thread(target=server.serve_forever, name="arkiv-ui", daemon=True).start()
    return server


def configure_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def bring_forward() -> None:
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        return


def main() -> None:
    configure_logging()
    service = LibraryService()
    api = ArkivApi(service)
    server = serve_ui()
    host, port = server.server_address
    window = webview.create_window(
        "Arkiv",
        url=f"http://{host}:{port}/index.html",
        js_api=api,
        width=1280,
        height=860,
        min_size=(1100, 720),
        background_color="#14110e",
        text_select=True,
    )
    api.window = window
    service.window = window

    def closing():
        service.shutdown()

    window.events.closing += closing
    # Edge WebView2 on Windows; Cocoa WebKit on macOS.
    gui = "edgechromium" if sys.platform.startswith("win") else None
    if gui:
        webview.start(bring_forward, gui=gui)
    else:
        webview.start(bring_forward)


if __name__ == "__main__":
    main()
