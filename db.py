"""Local SQLite helper for user accounts and basic statistics.
The database file is stored next to the script as `users.db`.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Tuple

DB_FILE = Path(__file__).with_suffix(".db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    games INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0
);
"""


class LocalDB:
    def __init__(self, db_path: str | os.PathLike | None = None):
        self.db_path = Path(db_path) if db_path else DB_FILE
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(_SCHEMA)
        self.conn.commit()

    # --------------------------------------------------- #
    def _hash(self, plain: str) -> str:
        return hashlib.sha256(plain.encode()).hexdigest()

    # --------------------------------------------------- #
    def add_user(self, username: str, password_plain: str) -> None:
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, self._hash(password_plain)),
                )
        except sqlite3.IntegrityError:
            raise ValueError("Username already exists")

    def verify_user(self, username: str, password_plain: str) -> bool:
        cur = self.conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        )
        row = cur.fetchone()
        if not row:
            return False
        return row[0] == self._hash(password_plain)

    # --------------------------------------------------- #
    def record_game(self, username: str, win: bool) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE users SET games = games + 1, wins = wins + ?, losses = losses + ? WHERE username = ?",
                (1 if win else 0, 0 if win else 1, username,),
            )

    def get_stats(self, username: str) -> Tuple[int, int, int]:
        cur = self.conn.execute(
            "SELECT games, wins, losses FROM users WHERE username = ?", (username,)
        )
        row = cur.fetchone()
        if row:
            return int(row[0]), int(row[1]), int(row[2])
        return (0, 0, 0) 