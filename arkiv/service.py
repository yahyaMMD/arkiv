from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from arkiv.ai import OpenRouterClassifier
from arkiv.config import Config
from arkiv.db import Database
from arkiv.files import (
    clean_category,
    clean_filename,
    contained,
    describe,
    fallback_category,
    human_size,
    is_parking_category,
    iter_files,
    library_label,
    match_existing_category,
    measure,
    place_file,
    refuse_library,
    restore_file,
    should_skip_name,
    top_folder,
)
from arkiv.paths import APP_DIR

log = logging.getLogger("arkiv")
BUSY = {"counting", "taxonomy", "classifying"}


class LibraryService:
    def __init__(self, config: Config | None = None, db: Database | None = None,
                 classifier=None, start_worker: bool = True):
        self.config = config or Config()
        self.db = db or Database()
        self.classifier = classifier or OpenRouterClassifier(self.config)
        self.remote = classifier is None
        self.allow_watch = start_worker
        self.lock = threading.Lock()
        self.jobs: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._queued: set[str] = set()
        self._busy_keys: set[str] = set()
        self._ignore_until: dict[str, float] = {}
        self.by_key: dict[str, dict] = {}
        self.progress = {"phase": "idle", "current": 0, "total": 0, "file": "", "detail": ""}
        self.last_message = ""
        self.window = None
        self._observer = None
        self._scan_queued = False
        self._watch_batch: str | None = None
        self._pause_until = 0.0
        self._count_cache = {"at": 0.0, "root": "", "count": 0, "nbytes": 0}
        self.reload_catalog()
        if start_worker:
            thread = threading.Thread(target=self._loop, name="arkiv-worker", daemon=True)
            thread.start()
            if self.config.confirmed and self.config.root and Path(self.config.root).is_dir() and self.config.auto_sort:
                self.start_watcher()
                self.request_scan(manual=False)

    @property
    def busy(self) -> bool:
        return self.progress.get("phase") in BUSY

    def reload_catalog(self) -> None:
        catalog: dict[str, dict] = {}
        root = self.config.root
        if root:
            for row in self.db.categories(root):
                if is_parking_category(row["name"]):
                    continue
                catalog[row["name"].casefold()] = {
                    "name": row["name"],
                    "description": row["description"] or "",
                }
        with self.lock:
            self.by_key = catalog

    def real_category_names(self) -> set[str]:
        with self.lock:
            return {item["name"] for item in self.by_key.values()}

    def _skip_dirs(self) -> set[str]:
        return self.real_category_names()

    def _claim_keys(self, path: Path) -> list[str]:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        try:
            size = path.stat().st_size if path.exists() else 0
        except OSError:
            size = 0
        return [key, f"{path.name.casefold()}|{size}", path.name.casefold()]

    def _claim(self, path: Path, *, from_watch: bool) -> list[str] | None:
        keys = self._claim_keys(path)
        now = time.time()
        with self.lock:
            expired = [item for item, until in self._ignore_until.items() if until <= now]
            for item in expired:
                self._ignore_until.pop(item, None)
            if from_watch and any(self._ignore_until.get(key, 0) > now for key in keys):
                return None
            if any(key in self._busy_keys for key in keys):
                return None
            for key in keys:
                self._busy_keys.add(key)
        return keys

    def _release(self, claimed: list[str] | None, *extra: Path, mute_for: float = 2.5) -> None:
        keys = list(claimed or [])
        for item in extra:
            if item is None:
                continue
            keys.extend(self._claim_keys(item))
        until = time.time() + mute_for
        with self.lock:
            for key in keys:
                self._busy_keys.discard(key)
                if mute_for > 0:
                    self._ignore_until[key] = until

    def shutdown(self) -> None:
        self._cancel.set()
        self._stop.set()
        self.stop_watcher()

    def set_root(self, path: str) -> dict:
        if self.busy or self._scan_queued:
            return {"ok": False, "error": "Wait until filing finishes."}
        refusal = refuse_library(Path(path))
        if refusal:
            return {"ok": False, "error": refusal}
        resolved = str(Path(path).expanduser().resolve())
        self.stop_watcher()
        self.config.update(root=resolved, confirmed=True)
        self.reload_catalog()
        self._invalidate_count()
        self.last_message = ""
        if self.allow_watch and self.config.auto_sort:
            self.start_watcher()
        return {"ok": True, "path": resolved}

    def inspect(self, path: str) -> dict:
        refusal = refuse_library(Path(path))
        if refusal:
            return {"ok": False, "error": refusal}
        root = Path(path).expanduser().resolve()
        names: set[str] = set()
        if self.config.root and str(root) == str(Path(self.config.root).resolve()):
            names = self._skip_dirs()
        count, nbytes = measure(iter_files(root, names))
        return {
            "ok": True,
            "path": str(root),
            "name": root.name,
            "count": count,
            "bytes": nbytes,
            "label": library_label(count, nbytes),
        }

    def request_scan(self, manual: bool = True) -> dict:
        if not self.config.root:
            return {"ok": False, "error": "Choose a folder first."}
        if self.remote and not self.config.has_key:
            return {"ok": False, "error": "Add an OpenRouter key in Settings."}
        with self.lock:
            if self.busy or self._scan_queued:
                return {"ok": False, "error": "Arkiv is already filing."}
            self._scan_queued = True
        self.jobs.put(("scan", bool(manual)))
        return {"ok": True}

    def cancel(self) -> dict:
        self._cancel.set()
        return {"ok": True}

    def set_auto_sort(self, enabled: bool) -> dict:
        self.config.update(auto_sort=bool(enabled))
        if self.config.auto_sort and self.config.confirmed and self.config.root and self.allow_watch:
            self.start_watcher()
            if not self.busy and not self._scan_queued:
                self.request_scan(manual=False)
        else:
            self.stop_watcher()
        return {"ok": True, "auto_sort": self.config.auto_sort}

    def set_model(self, model: str) -> dict:
        cleaned = (model or "").strip()
        if not cleaned or len(cleaned) > 120 or any(char.isspace() for char in cleaned):
            return {"ok": False, "error": "Enter a model id such as google/gemini-2.5-flash."}
        self.config.update(model=cleaned)
        return {"ok": True, "model": cleaned}

    def set_api_key(self, key: str) -> dict:
        cleaned = (key or "").strip()
        if not cleaned:
            return {"ok": True, "key_hint": self.config.key_hint}
        if len(cleaned) < 20:
            return {"ok": False, "error": "That key looks too short."}
        self.config.update(api_key=cleaned)
        self._pause_until = 0
        return {"ok": True, "key_hint": self.config.key_hint}

    def test_connection(self) -> dict:
        try:
            self.classifier.ping()
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": f"Connected with {self.config.model}."}

    def undo(self) -> dict:
        if self.busy or self._scan_queued:
            return {"ok": False, "error": "Wait until filing finishes."}
        root = self.config.root
        if not root:
            return {"ok": False, "error": "Choose a folder first."}
        moves = self.db.last_batch(root)
        if not moves:
            return {"ok": False, "error": "There is no filing to undo."}
        restored = 0
        library = Path(root)
        for move in moves:
            src = Path(move["src"])
            dest = Path(move["dest"])
            try:
                back = restore_file(library, src, dest)
            except OSError as exc:
                log.info("Undo failed for %s: %s", dest.name, exc)
                self.db.mark_move_undone(move["id"])
                continue
            self.db.mark_move_undone(move["id"])
            if back is not None:
                self.db.mark_moved_back(root, move["dest"], str(back.resolve()))
                restored += 1
        noun = "file" if restored == 1 else "files"
        self.last_message = f"Moved {restored} {noun} back. They stay put until you classify again."
        self._invalidate_count()
        return {"ok": True, "restored": restored, "message": self.last_message}

    def get_state(self) -> dict:
        root = self.config.root
        sorting = self.busy
        if sorting:
            unsorted_label = "Filing now"
            unsorted = max(int(self.progress.get("total") or 0) - int(self.progress.get("current") or 0), 0)
        else:
            unsorted, nbytes = self.unsorted_stats()
            unsorted_label = library_label(unsorted, nbytes)
        if root:
            self.db.clear_noise(root)
        categories = [
            row for row in (self.db.categories(root) if root else [])
            if not is_parking_category(row["name"])
        ]
        recent = [
            row for row in (self.db.recent(root) if root else [])
            if not (
                row.get("status") == "error"
                and ("No such file" in (row.get("error") or "") or "Errno 2" in (row.get("error") or ""))
            )
            and not is_parking_category(row.get("category") or "")
        ]
        return {
            "root": root,
            "root_name": Path(root).name if root else "",
            "model": self.config.model,
            "auto_sort": self.config.auto_sort,
            "watching": self._observer is not None,
            "confirmed": self.config.confirmed,
            "has_key": self.config.has_key,
            "key_hint": self.config.key_hint,
            "unsorted": unsorted,
            "unsorted_label": unsorted_label,
            "sorting": sorting,
            "progress": dict(self.progress),
            "message": self.last_message,
            "categories": categories,
            "recent": recent,
            "stats": {
                "files": sum(int(row.get("count") or 0) for row in categories),
                "categories": len(categories),
            },
        }

    def list_files(self, category: str) -> list[dict]:
        root = self.config.root
        if not root or not category:
            return self.db.recent(root) if root else []
        return self.db.files_in(root, category)

    def start_watcher(self) -> None:
        if not self.allow_watch or self._observer is not None:
            return
        root = self.config.root
        if not root or not Path(root).is_dir():
            return
        observer = Observer()
        observer.schedule(_WatchHandler(self), root, recursive=True)
        observer.start()
        self._observer = observer
        log.info("Watching %s", root)

    def stop_watcher(self) -> None:
        observer = self._observer
        self._observer = None
        if observer is None:
            return
        observer.stop()
        observer.join(timeout=2)

    def enqueue(self, path_str: str) -> None:
        if not self.config.auto_sort or not self.config.root:
            return
        if self.remote and not self.config.has_key:
            return
        if time.time() < self._pause_until:
            return
        try:
            path = Path(path_str).resolve()
        except OSError:
            return
        if _in_app(path):
            return
        root = Path(self.config.root)
        try:
            if not contained(root, path):
                return
            top = top_folder(root, path)
        except (OSError, ValueError):
            return
        if top and not is_parking_category(top) and top.casefold() in {name.casefold() for name in self.real_category_names()}:
            return
        key = str(path)
        now = time.time()
        with self.lock:
            if key in self._queued or key in self._busy_keys:
                return
            if self._ignore_until.get(key, 0) > now:
                return
            if key in self.db.undone_paths(self.config.root):
                return
            self._queued.add(key)
        self.jobs.put(("file", key))

    def unsorted_stats(self) -> tuple[int, int]:
        root = self.config.root
        if not root or not Path(root).is_dir():
            return 0, 0
        now = time.time()
        cache = self._count_cache
        if cache["root"] == root and now - cache["at"] < 4:
            return int(cache["count"]), int(cache["nbytes"])
        names = self._skip_dirs()
        count, nbytes = measure(iter_files(Path(root), names))
        self._count_cache = {"at": now, "root": root, "count": count, "nbytes": nbytes}
        return count, nbytes

    def _invalidate_count(self) -> None:
        self._count_cache["at"] = 0.0

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.jobs.get(timeout=0.4)
            except queue.Empty:
                continue
            try:
                kind = job[0]
                if kind == "scan":
                    self._scan(manual=bool(job[1]))
                elif kind == "file":
                    try:
                        self._classify_path(job[1], from_watch=True, batch_id=self._watch_batch_id())
                    finally:
                        with self.lock:
                            self._queued.discard(job[1])
            except Exception as exc:
                log.exception("Arkiv job failed")
                self.last_message = str(exc)
                self.progress["phase"] = "idle"
                self._scan_queued = False
            finally:
                self.jobs.task_done()

    def _watch_batch_id(self) -> str:
        if not self._watch_batch:
            self._watch_batch = uuid.uuid4().hex
        return self._watch_batch

    def _scan(self, manual: bool) -> None:
        self._cancel.clear()
        self._watch_batch = None
        self.progress.update(phase="counting", current=0, total=0, file="", detail="Counting files")
        filed = 0
        try:
            root_text = self.config.root
            if not root_text or not Path(root_text).is_dir():
                self.last_message = "The library folder is not available."
                return
            root = Path(root_text)
            self.reload_catalog()
            names = self._skip_dirs()
            everything = iter_files(root, names, APP_DIR)
            undone = self.db.undone_paths(root_text)
            pending = [path for path in everything if str(path.resolve()) not in undone]
            files = everything if manual else pending
            if self._cancel.is_set():
                self.last_message = "Stopped."
                return
            if not files:
                if everything and not manual:
                    self.last_message = "Restored files stay put until you classify again."
                else:
                    self.last_message = "Nothing new to file."
                return
            self.progress.update(phase="taxonomy", current=0, total=len(files), file="", detail="Choosing categories")
            try:
                self.classifier.ping()
                if not _has_real_categories(self._known_categories()):
                    proposals = self.classifier.propose(self._briefs(root, files), self._known_categories())
                    for item in proposals:
                        self.ensure_category(item["name"], item["description"])
            except Exception as exc:
                self.last_message = str(exc)
                return
            batch_id = uuid.uuid4().hex
            for index, path in enumerate(files, start=1):
                if self._cancel.is_set():
                    noun = "file" if filed == 1 else "files"
                    self.last_message = f"Stopped after filing {filed} {noun}."
                    return
                self.progress.update(
                    phase="classifying",
                    current=index,
                    total=len(files),
                    file=path.name,
                    detail="Reading and choosing a category",
                )
                if self._classify_path(str(path), from_watch=False, batch_id=batch_id):
                    filed += 1
            if filed:
                noun = "file" if filed == 1 else "files"
                categories = self.db.categories(root_text)
                kind = "category" if len(categories) == 1 else "categories"
                self.last_message = f"Filed {filed} {noun} into {len(categories)} {kind}."
            elif not self.last_message:
                self.last_message = "No files were moved."
        finally:
            self._scan_queued = False
            self.progress["phase"] = "idle"
            self.progress["file"] = ""
            self._cancel.clear()
            self._invalidate_count()

    def _briefs(self, root: Path, files: list[Path]) -> list[str]:
        lines: list[str] = []
        for path in _sample(files, 120):
            try:
                desc = describe(path, root, snippet=True)
            except OSError:
                continue
            snippet = (desc.get("text") or "").replace("\n", " ")[:140]
            lines.append(
                f"{desc['relative']} | {desc['kind']} | {human_size(desc['size'])} | {snippet}"
            )
        return lines

    def _known_categories(self) -> list[dict]:
        with self.lock:
            items = [item for item in self.by_key.values() if not is_parking_category(item["name"])]
        items.sort(key=lambda item: item["name"].casefold())
        return items

    def ensure_category(self, name: str, description: str = "") -> str:
        cleaned = clean_category(name)
        if is_parking_category(cleaned):
            cleaned = "Documents"
        with self.lock:
            found = self.by_key.get(cleaned.casefold())
            if found:
                return found["name"]
            self.by_key[cleaned.casefold()] = {"name": cleaned, "description": description or ""}
        self.db.upsert_category(self.config.root, cleaned, description or "")
        return cleaned

    def match_category(self, name: str, confidence: float, desc: dict | None = None) -> str:
        hint = " ".join(
            [
                str(name or ""),
                str((desc or {}).get("name") or ""),
                str((desc or {}).get("relative") or ""),
            ]
        )
        matched = match_existing_category(hint, self._known_categories())
        if matched:
            return matched
        cleaned = clean_category(name)
        with self.lock:
            found = self.by_key.get(cleaned.casefold())
            known = len(self.by_key)
        if found and not is_parking_category(found["name"]):
            return found["name"]
        if is_parking_category(cleaned) or not cleaned:
            return fallback_category(str((desc or {}).get("kind") or ""), str((desc or {}).get("extension") or ""))
        if known < 40 or confidence >= 0.35:
            return cleaned
        return fallback_category(str((desc or {}).get("kind") or ""), str((desc or {}).get("extension") or ""))

    def _classify_path(self, path_str: str, *, from_watch: bool, batch_id: str | None) -> bool:
        path = Path(path_str)
        claimed: list[str] | None = None
        destination: Path | None = None
        try:
            if _in_app(path):
                return False
            if not path.exists() or path.is_symlink() or not path.is_file() or should_skip_name(path):
                return False
            root_text = self.config.root
            if not root_text:
                return False
            root = Path(root_text)
            if not contained(root, path):
                return False
            resolved = path.resolve()
            if from_watch and time.time() < self._pause_until:
                return False
            top = top_folder(root, resolved)
            if from_watch and top and not is_parking_category(top) and top.casefold() in {name.casefold() for name in self.real_category_names()}:
                return False
            if from_watch and str(resolved) in self.db.undone_paths(root_text):
                return False
            if from_watch and not _wait_until_settled(path):
                return False
            if not path.exists():
                return False
            claimed = self._claim(path, from_watch=from_watch)
            if claimed is None:
                return False
            self.progress["file"] = path.name
            self.progress["detail"] = "Reading, renaming, and filing"
            if from_watch:
                self.progress.update(phase="classifying", current=1, total=1, file=path.name)
            try:
                desc = describe(path, root)
                result = self.classifier.classify(desc, self._known_categories())
            except Exception as exc:
                message = str(exc)
                if "API key" in message or "rejected" in message:
                    self._pause_until = time.time() + 120
                # Vanished files from a race are not user-facing alerts.
                if "No such file" in message or "Errno 2" in message:
                    log.info("Skipped vanished file %s", path.name)
                    return False
                self.last_message = message
                self._record(root_text, resolved, resolved, path.name, "", 0, "", "error", message)
                log.info("Could not classify %s: %s", path.name, message)
                return False
            if not path.exists():
                log.info("Skipped vanished file after read %s", path.name)
                return False
            category = self.match_category(result["category"], result["confidence"], desc)
            category = self.ensure_category(category, result["summary"])
            new_name = clean_filename(result.get("filename") or path.name, path.suffix) or path.name
            before = str(path.resolve())
            try:
                destination = place_file(root, category, path, new_name=new_name)
            except FileNotFoundError:
                log.info("Skipped vanished file during move %s", path.name)
                return False
            except (OSError, ValueError) as exc:
                if "No such file" in str(exc) or getattr(exc, "errno", None) == 2:
                    log.info("Skipped vanished file during move %s", path.name)
                    return False
                self.last_message = f"Could not move {path.name}. {exc}"
                self._record(root_text, resolved, resolved, path.name, category, result["confidence"], result["summary"], "error", str(exc))
                return False
            current = str(destination.resolve())
            if current != before and batch_id:
                self.db.record_move(root_text, batch_id, before, current)
            self._record(
                root_text,
                Path(before),
                destination.resolve(),
                destination.name,
                category,
                result["confidence"],
                result["summary"],
                "filed",
                "",
            )
            renamed = destination.name != Path(before).name
            if renamed:
                self.last_message = f"Renamed to {destination.name} and filed into {category}."
            else:
                self.last_message = f"Filed {destination.name} into {category}."
            self.progress["detail"] = f"{category} · {destination.name}"
            self._invalidate_count()
            log.info("Filed %s into %s", destination.name, category)
            return True
        finally:
            self._release(claimed, destination)
            if from_watch and self.progress.get("phase") == "classifying" and self.progress.get("total") == 1:
                self.progress["phase"] = "idle"
                self.progress["file"] = ""

    def _record(self, root: str, original: Path, current: Path, name: str, category: str,
                confidence: float, summary: str, status: str, error: str) -> None:
        self.db.upsert_file(
            {
                "root": root,
                "original_path": str(original),
                "current_path": str(current),
                "name": name,
                "category": category,
                "confidence": confidence,
                "summary": summary,
                "status": status,
                "error": error,
            }
        )


class _WatchHandler(FileSystemEventHandler):
    def __init__(self, service: LibraryService):
        super().__init__()
        self.service = service

    def on_created(self, event):
        if event.is_directory:
            return
        self.service.enqueue(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        self.service.enqueue(event.dest_path)


def _in_app(path: Path) -> bool:
    try:
        return contained(APP_DIR, path)
    except OSError:
        return False


def _has_real_categories(categories: list[dict]) -> bool:
    return any(not is_parking_category(item.get("name", "")) for item in categories)


def _sample(paths: list[Path], limit: int) -> list[Path]:
    if len(paths) <= limit:
        return list(paths)
    groups: dict[str, list[Path]] = {}
    for path in paths:
        groups.setdefault(path.suffix.lower() or "none", []).append(path)
    picked: list[Path] = []
    keys = list(groups)
    index = 0
    while len(picked) < limit and any(groups.values()):
        bucket = groups[keys[index % len(keys)]]
        if bucket:
            picked.append(bucket.pop(0))
        index += 1
        if index > limit * (len(keys) + 2):
            break
    return picked


def _wait_until_settled(path: Path, timeout: float = 20) -> bool:
    last = None
    stable = 0
    started = time.time()
    while time.time() - started < timeout:
        if not path.exists():
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last:
            stable += 1
            if stable >= 2:
                return True
        else:
            stable = 0
            last = size
        time.sleep(0.35)
    return path.exists()
