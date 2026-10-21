from __future__ import annotations

import tempfile
from pathlib import Path

from arkiv.config import Config
from arkiv.db import Database
from arkiv.files import (
    clean_category,
    clean_filename,
    fallback_category,
    iter_files,
    match_existing_category,
    refuse_library,
)
from arkiv.service import LibraryService


class FakeClassifier:
    def __init__(self):
        self.seen: list[str] = []

    def ping(self) -> None:
        return None

    def propose(self, lines, existing):
        return [
            {"name": "Notes", "description": "Written notes"},
            {"name": "Code", "description": "Source code"},
        ]

    def classify(self, desc, categories):
        self.seen.append(desc["name"])
        if desc["name"] == "bad.txt":
            raise RuntimeError("model failed")
        if desc["extension"] == ".py":
            return {
                "category": "Code",
                "filename": "Main Script.py",
                "confidence": 0.91,
                "summary": "A Python source file.",
            }
        return {
            "category": "Notes",
            "filename": "Trip Packing List.txt",
            "confidence": 0.9,
            "summary": "A written note.",
        }


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_names_and_safety() -> None:
    expect(clean_category("../Invoices/2024") == "Invoices 2024", "category names stay inside one folder")
    expect(clean_category("") == "Documents", "blank categories become Documents")
    expect(clean_category("Needs Review") == "Documents", "Needs Review is not a normal category")
    expect(clean_filename("March Rent Invoice", ".pdf") == "March Rent Invoice.pdf", "filenames keep extension")
    expect(clean_filename("../secret:name", ".txt") == "secret-name.txt", "filenames are sanitized")
    expect(fallback_category("image") == "Photos", "images fall back to Photos")
    expect(
        match_existing_category(
            "Daily Report October 19 2026.jpg",
            [{"name": "Daily Report", "description": ""}],
        )
        == "Daily Report",
        "filename matches existing category",
    )
    expect(refuse_library(Path.home()) is not None, "home folder is refused")
    expect(refuse_library(Path("/")) is not None, "disk root is refused")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "papers"
        folder.mkdir()
        expect(refuse_library(folder) is None, "a normal folder is allowed")
        app = folder / "App"
        (app / "secret.txt").parent.mkdir()
        (app / "secret.txt").write_text("secret", encoding="utf-8")
        (folder / "Notes").mkdir()
        (folder / "Notes" / "old.txt").write_text("old", encoding="utf-8")
        (folder / "loose.txt").write_text("loose", encoding="utf-8")
        (folder / ".hidden").write_text("nope", encoding="utf-8")
        found = {path.name for path in iter_files(folder, {"Notes"}, app)}
        expect(found == {"loose.txt"}, f"scan skipped the wrong files: {found}")


def test_sort_undo_and_watch_rules() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "library"
        (root / "src").mkdir(parents=True)
        (root / "note.txt").write_text("Packing list for the trip", encoding="utf-8")
        (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (root / "bad.txt").write_text("unreadable", encoding="utf-8")
        config = Config(Path(tmp) / "config.json")
        config.update(auto_sort=False, api_key="x" * 24, model="fake")
        database = Database(Path(tmp) / "arkiv.db")
        fake = FakeClassifier()
        service = LibraryService(config=config, db=database, classifier=fake, start_worker=False)
        placed = service.set_root(str(root))
        expect(placed["ok"], placed.get("error", "set_root failed"))
        service._scan(manual=True)
        expect((root / "Notes" / "Trip Packing List.txt").is_file(), "note was renamed and filed")
        expect((root / "Code" / "Main Script.py").is_file(), "code was renamed and filed")
        expect((root / "bad.txt").is_file(), "failed file stayed in place")
        expect(not (root / "src" / "main.py").exists(), "source file moved")
        state = service.get_state()
        expect(state["stats"]["files"] == 2, f"filed count {state['stats']['files']}")
        service._scan(manual=False)
        expect((root / "bad.txt").is_file(), "a second pass did not invent a folder for the failed file")
        undone = service.undo()
        expect(undone["ok"], undone.get("error", "undo failed"))
        expect((root / "note.txt").is_file(), "note restored to original path")
        expect((root / "src" / "main.py").is_file(), "code restored to original path")
        service._scan(manual=False)
        expect((root / "note.txt").is_file(), "automatic pass left restored files alone")
        expect(not (root / "Notes" / "Trip Packing List.txt").exists(), "restored note was not filed again")
        service._scan(manual=True)
        expect((root / "Notes" / "Trip Packing List.txt").is_file(), "manual pass files restored files again")
        parking = root / "Needs Review"
        parking.mkdir(exist_ok=True)
        (parking / "loose-note.txt").write_text("Packing list for the trip", encoding="utf-8")
        service._scan(manual=True)
        notes = list((root / "Notes").glob("Trip Packing List*.txt"))
        expect(len(notes) >= 2, "parking files are reclassified into Notes")
        expect(not (parking / "loose-note.txt").exists(), "parking file left Needs Review")


def main() -> None:
    test_names_and_safety()
    test_sort_undo_and_watch_rules()
    print("Arkiv self-test passed")


if __name__ == "__main__":
    main()
