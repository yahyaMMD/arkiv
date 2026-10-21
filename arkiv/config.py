from __future__ import annotations

import json
import os
from pathlib import Path

from arkiv.paths import CONFIG_PATH, DATA_DIR

DEFAULT_MODEL = "google/gemini-2.5-flash"


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or CONFIG_PATH
        self.data = {
            "root": "",
            "model": DEFAULT_MODEL,
            "auto_sort": True,
            "confirmed": False,
            "api_key": "",
        }
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(stored, dict):
            self.data.update(stored)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @property
    def root(self) -> str:
        return str(self.data.get("root") or "")

    @property
    def model(self) -> str:
        return str(self.data.get("model") or DEFAULT_MODEL)

    @property
    def auto_sort(self) -> bool:
        return bool(self.data.get("auto_sort", True))

    @property
    def confirmed(self) -> bool:
        return bool(self.data.get("confirmed"))

    @property
    def api_key(self) -> str:
        return str(self.data.get("api_key") or "")

    @property
    def has_key(self) -> bool:
        return len(self.api_key) >= 20

    @property
    def key_hint(self) -> str:
        key = self.api_key
        if len(key) < 4:
            return ""
        return "••••" + key[-4:]

    def update(self, **changes: object) -> None:
        self.data.update(changes)
        self.save()


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
