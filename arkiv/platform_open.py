from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_path(path: str | Path) -> None:
    target = str(path)
    if sys.platform == "darwin":
        subprocess.run(["open", target], check=False)
    elif sys.platform.startswith("win"):
        os.startfile(target)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", target], check=False)


def reveal_path(path: str | Path) -> None:
    target = Path(path)
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(target)], check=False)
    elif sys.platform.startswith("win"):
        subprocess.run(["explorer", "/select,", str(target)], check=False)
    else:
        open_path(target.parent if target.is_file() else target)
