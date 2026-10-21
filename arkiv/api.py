from __future__ import annotations

from pathlib import Path

from arkiv.files import clean_category, contained
from arkiv.http_api import pick_folder_native
from arkiv.platform_open import open_path, reveal_path
from arkiv.service import LibraryService


class ArkivApi:
    def __init__(self, service: LibraryService):
        self.service = service
        self.window = None

    def get_state(self) -> dict:
        return self.service.get_state()

    def list_files(self, category: str) -> list[dict]:
        return self.service.list_files(category or "")

    def choose_folder(self) -> dict:
        try:
            selected = pick_folder_native(self.window)
        except Exception as exc:
            return {"ok": False, "error": str(exc) or "The folder picker could not open."}
        if not selected:
            return {"ok": False}
        return self.service.inspect(selected)

    def confirm_library(self, path: str) -> dict:
        placed = self.service.set_root(path or "")
        if not placed.get("ok"):
            return placed
        return self.service.request_scan(manual=True)

    def start_sort(self) -> dict:
        return self.service.request_scan(manual=True)

    def cancel_sort(self) -> dict:
        return self.service.cancel()

    def undo_last(self) -> dict:
        return self.service.undo()

    def set_auto_sort(self, enabled: bool) -> dict:
        return self.service.set_auto_sort(bool(enabled))

    def set_model(self, model: str) -> dict:
        return self.service.set_model(model or "")

    def set_api_key(self, key: str) -> dict:
        return self.service.set_api_key(key or "")

    def test_connection(self) -> dict:
        return self.service.test_connection()

    def open_root(self) -> dict:
        root = self.service.config.root
        if not root or not Path(root).is_dir():
            return {"ok": False, "error": "The library folder is not available."}
        open_path(root)
        return {"ok": True}

    def open_category(self, name: str) -> dict:
        root_text = self.service.config.root
        if not root_text:
            return {"ok": False, "error": "Choose a folder first."}
        root = Path(root_text)
        folder = (root / clean_category(name or "")).resolve()
        if not contained(root, folder):
            return {"ok": False, "error": "That category is outside the library."}
        if not folder.is_dir():
            return {"ok": False, "error": "That category folder is not on disk yet."}
        open_path(folder)
        return {"ok": True}

    def reveal_file(self, path: str) -> dict:
        if not path:
            return {"ok": False, "error": "That file is no longer there."}
        file_path = Path(path)
        root_text = self.service.config.root
        if not file_path.exists():
            return {"ok": False, "error": "That file is no longer there."}
        if root_text and not contained(Path(root_text), file_path):
            return {"ok": False, "error": "That file is outside the library."}
        reveal_path(file_path)
        return {"ok": True}
