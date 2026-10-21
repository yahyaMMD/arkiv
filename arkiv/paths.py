from __future__ import annotations

import sys
from pathlib import Path


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


APP_DIR = _app_dir()
BUNDLE_DIR = _bundle_dir()
UI_DIR = BUNDLE_DIR / "ui"
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "arkiv.db"
LOG_PATH = DATA_DIR / "arkiv.log"
