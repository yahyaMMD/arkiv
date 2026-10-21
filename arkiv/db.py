from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from arkiv.paths import DB_PATH


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    root TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (root, name)
                );

                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    root TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    current_path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS moves (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    root TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    src TEXT NOT NULL,
                    dest TEXT NOT NULL,
                    undone INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_files_root
                    ON files(root, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_files_original
                    ON files(root, original_path);
                CREATE INDEX IF NOT EXISTS idx_moves_root
                    ON moves(root, undone, id);
                """
            )
            conn.commit()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def upsert_category(self, root: str, name: str, description: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO categories (root, name, description, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(root, name) DO UPDATE SET
                    description = CASE
                        WHEN excluded.description != '' THEN excluded.description
                        ELSE categories.description
                    END
                """,
                (root, name, description or "", now()),
            )
            conn.commit()

    def categories(self, root: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.name, c.description, COUNT(f.id) AS count
                FROM categories c
                LEFT JOIN files f
                    ON f.root = c.root
                    AND f.category = c.name
                    AND f.status = 'filed'
                WHERE c.root = ?
                GROUP BY c.name
                ORDER BY count DESC, c.name COLLATE NOCASE
                """,
                (root,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_file(self, row: dict) -> None:
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM files WHERE root = ? AND original_path = ?",
                (row["root"], row["original_path"]),
            ).fetchone()
            values = (
                row["current_path"],
                row["name"],
                row["category"],
                float(row.get("confidence") or 0),
                row.get("summary") or "",
                row["status"],
                row.get("error") or "",
                now(),
                row["root"],
                row["original_path"],
            )
            if existing:
                conn.execute(
                    """
                    UPDATE files SET
                        current_path = ?, name = ?, category = ?, confidence = ?,
                        summary = ?, status = ?, error = ?, updated_at = ?
                    WHERE root = ? AND original_path = ?
                    """,
                    values,
                )
            else:
                conn.execute(
                    """
                    INSERT INTO files (
                        current_path, name, category, confidence, summary,
                        status, error, updated_at, root, original_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            conn.commit()

    def mark_moved_back(self, root: str, dest: str, restored: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE files
                SET current_path = ?, status = 'undone', updated_at = ?
                WHERE root = ? AND current_path = ? AND status = 'filed'
                """,
                (restored, now(), root, dest),
            )
            conn.commit()

    def recent(self, root: str, limit: int = 30) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT name, category, summary, confidence, current_path,
                       original_path, status, error, updated_at
                FROM files
                WHERE root = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (root, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def files_in(self, root: str, category: str, limit: int = 400) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT name, category, summary, confidence, current_path,
                       original_path, status, error, updated_at
                FROM files
                WHERE root = ? AND category = ? AND status = 'filed'
                ORDER BY name COLLATE NOCASE
                LIMIT ?
                """,
                (root, category, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def filed_count(self, root: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM files WHERE root = ? AND status = 'filed'",
                (root,),
            ).fetchone()
        return int(row["n"] if row else 0)

    def record_move(self, root: str, batch_id: str, src: str, dest: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO moves (root, batch_id, src, dest, undone, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (root, batch_id, src, dest, now()),
            )
            conn.commit()

    def mark_move_undone(self, move_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE moves SET undone = 1 WHERE id = ?", (move_id,))
            conn.commit()

    def category_names(self, root: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name FROM categories WHERE root = ?",
                (root,),
            ).fetchall()
        return [row["name"] for row in rows]

    def delete_category(self, root: str, name: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM categories WHERE root = ? AND name = ?",
                (root, name),
            )
            conn.commit()

    def clear_noise(self, root: str) -> None:
        """Drop stale alerts and the temporary Needs Review parking category."""
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM files
                WHERE root = ?
                  AND status = 'error'
                  AND (
                    error LIKE '%No such file%'
                    OR error LIKE '%Errno 2%'
                  )
                """,
                (root,),
            )
            conn.execute(
                """
                DELETE FROM categories
                WHERE root = ?
                  AND lower(name) IN ('needs review', 'review', 'unsorted', 'misc', 'other', 'unknown')
                """,
                (root,),
            )
            conn.commit()

    def undone_paths(self, root: str) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT current_path FROM files WHERE root = ? AND status = 'undone'",
                (root,),
            ).fetchall()
        return {row["current_path"] for row in rows}

    def last_batch(self, root: str) -> list[dict]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT batch_id FROM moves
                WHERE root = ? AND undone = 0
                ORDER BY id DESC LIMIT 1
                """,
                (root,),
            ).fetchone()
            if not row:
                return []
            moves = conn.execute(
                """
                SELECT id, src, dest FROM moves
                WHERE root = ? AND batch_id = ? AND undone = 0
                ORDER BY id DESC
                """,
                (root, row["batch_id"]),
            ).fetchall()
        return [dict(item) for item in moves]
