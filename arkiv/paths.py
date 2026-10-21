from __future__ import annotations

import sys
from pathlib import Path


def _looks_like_app_root(path: Path) -> bool:
    return (path / "ui").is_dir() and (
        (path / "main.py").is_file()
        or (path / "Arkiv.exe").is_file()
        or (path / "Arkiv.bat").is_file()
    )


def _app_dir() -> Path:
    """Folder that contains main.py, ui/, and data/ — never site-packages."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    candidates: list[Path] = []

    main = getattr(sys.modules.get("__main__"), "__file__", None)
    if main:
        candidates.append(Path(main).resolve().parent)

    candidates.append(Path.cwd().resolve())

    here = Path(__file__).resolve()
    candidates.extend(here.parents)

    for candidate in candidates:
        try:
            if _looks_like_app_root(candidate):
                return candidate
        except OSError:
            continue

    # Last resort: two levels above this file (source checkout layout).
    return here.parents[1]


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bundled = Path(meipass)
            if (bundled / "ui").is_dir():
                return bundled
        return Path(sys.executable).resolve().parent
    return _app_dir()


APP_DIR = _app_dir()
BUNDLE_DIR = _bundle_dir()
UI_DIR = BUNDLE_DIR / "ui"
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "arkiv.db"
LOG_PATH = DATA_DIR / "arkiv.log"
