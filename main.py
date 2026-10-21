from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Force the real app folder onto sys.path before any arkiv import.
# Windows embeddable Python ignores PYTHONPATH when a ._pth file exists.
_APP_ROOT = Path(__file__).resolve().parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))
os.chdir(_APP_ROOT)


def _repair_stdio() -> None:
    folder = _APP_ROOT / "data"
    folder.mkdir(parents=True, exist_ok=True)
    log_file = folder / "launch.log"
    if sys.stdout is None:
        sys.stdout = open(log_file, "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(log_file, "a", encoding="utf-8")


_repair_stdio()


def _show_error(message: str) -> None:
    text = str(message)[:1800]
    try:
        (_APP_ROOT / "data").mkdir(parents=True, exist_ok=True)
        with open(_APP_ROOT / "data" / "launch.log", "a", encoding="utf-8") as handle:
            handle.write("\n" + text + "\n")
    except OSError:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, "Arkiv", 0x10)
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


try:
    import logging

    import webview

    from arkiv.api import ArkivApi
    from arkiv.http_api import start_server
    from arkiv.paths import APP_DIR, DATA_DIR, LOG_PATH, UI_DIR
    from arkiv.service import LibraryService
except Exception as exc:
    _show_error(
        "Arkiv could not load its libraries.\n\n"
        f"{exc}\n\n"
        f"app={_APP_ROOT}\n"
        f"arkiv exists={(_APP_ROOT / 'arkiv').is_dir()}\n"
        f"ui exists={(_APP_ROOT / 'ui').is_dir()}\n"
    )
    raise SystemExit(1)


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


def _start_gui(callback) -> None:
    if not sys.platform.startswith("win"):
        webview.start(callback)
        return
    last_error = None
    for gui in ("edgechromium", "mshtml"):
        try:
            webview.start(callback, gui=gui)
            return
        except Exception as exc:
            last_error = exc
            logging.exception("GUI backend %s failed", gui)
    raise RuntimeError(
        "Could not open the Arkiv window.\n"
        "Install Microsoft Edge WebView2 Runtime from Microsoft, then reopen Arkiv.\n"
        f"Details: {last_error}"
    )


def main() -> None:
    configure_logging()
    logging.info("APP_DIR=%s UI_DIR=%s", APP_DIR, UI_DIR)
    if not UI_DIR.is_dir():
        raise FileNotFoundError(
            f"UI folder missing.\nExpected: {UI_DIR}\nApp root: {APP_DIR}\n"
            f"Files here: {list(APP_DIR.iterdir())[:20]}"
        )
    if not (APP_DIR / "arkiv" / "__init__.py").is_file() and not (
        APP_DIR / "python" / "Lib" / "site-packages" / "arkiv" / "__init__.py"
    ).is_file():
        raise FileNotFoundError(f"arkiv package missing under {APP_DIR}")
    service = LibraryService()
    api = ArkivApi(service)
    # HTTP UI + API — the UI never depends on pywebview.api (broken on many Windows Edge builds).
    server, port = start_server(api, UI_DIR)
    window = webview.create_window(
        "Arkiv",
        url=f"http://127.0.0.1:{port}/index.html",
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
        try:
            server.shutdown()
        except Exception:
            pass

    window.events.closing += closing
    _start_gui(bring_forward)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        _show_error("Arkiv failed to start:\n\n" + traceback.format_exc())
        raise SystemExit(1)
