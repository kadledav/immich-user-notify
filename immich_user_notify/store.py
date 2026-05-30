"""SQLite state store. Holds, per album, the set of seen asset IDs and member IDs
plus a tiny meta row. The DB mirrors the album's *current* contents (a removed asset
is deleted from the DB, so re-adding it later counts as new again).

Only IDs are stored -- never asset names. The owner of a *new* asset is read live
from the album detail, so owner_id is not persisted.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator

from .timeutil import parse_immich_dt, to_iso_utc

_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class AlbumState:
    album_id: str
    name: str
    asset_count: int
    updated_at: datetime
    baseline_done: bool
    member_count: int = 0


class Store:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(db_path))
            os.makedirs(parent, exist_ok=True)
        # isolation_level=None -> autocommit mode; we manage transactions explicitly.
        self._conn = sqlite3.connect(db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    def _configure(self) -> None:
        cur = self._conn
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")

    def _migrate(self) -> None:
        with self.transaction():
            c = self._conn
            c.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta ("
                " key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS album ("
                " album_id TEXT PRIMARY KEY,"
                " name TEXT NOT NULL,"
                " asset_count INTEGER NOT NULL DEFAULT 0,"
                " member_count INTEGER NOT NULL DEFAULT 0,"
                " updated_at TEXT NOT NULL,"
                " baseline_done INTEGER NOT NULL DEFAULT 0)"
            )
            # Add member_count to album tables created before it existed.
            album_cols = {r["name"] for r in c.execute("PRAGMA table_info(album)").fetchall()}
            if "member_count" not in album_cols:
                c.execute("ALTER TABLE album ADD COLUMN member_count INTEGER NOT NULL DEFAULT 0")
            c.execute(
                "CREATE TABLE IF NOT EXISTS album_asset ("
                " album_id TEXT NOT NULL REFERENCES album(album_id) ON DELETE CASCADE,"
                " asset_id TEXT NOT NULL,"
                " PRIMARY KEY (album_id, asset_id))"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_album_asset_album ON album_asset(album_id)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS album_member ("
                " album_id TEXT NOT NULL REFERENCES album(album_id) ON DELETE CASCADE,"
                " user_id TEXT NOT NULL,"
                " PRIMARY KEY (album_id, user_id))"
            )
            c.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)"
                " ON CONFLICT(key) DO NOTHING",
                (_SCHEMA_VERSION,),
            )

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    # --- album meta -------------------------------------------------------

    def get_album_state(self, album_id: str) -> AlbumState | None:
        row = self._conn.execute(
            "SELECT album_id, name, asset_count, member_count, updated_at, baseline_done"
            " FROM album WHERE album_id = ?",
            (album_id,),
        ).fetchone()
        if row is None:
            return None
        return AlbumState(
            album_id=row["album_id"],
            name=row["name"],
            asset_count=row["asset_count"],
            member_count=row["member_count"],
            updated_at=parse_immich_dt(row["updated_at"]),
            baseline_done=bool(row["baseline_done"]),
        )

    def upsert_album_meta(
        self,
        album_id: str,
        *,
        name: str,
        asset_count: int,
        updated_at: datetime,
        baseline_done: bool,
        member_count: int = 0,
    ) -> None:
        self._conn.execute(
            "INSERT INTO album(album_id, name, asset_count, member_count, updated_at, baseline_done)"
            " VALUES(?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(album_id) DO UPDATE SET"
            "   name=excluded.name,"
            "   asset_count=excluded.asset_count,"
            "   member_count=excluded.member_count,"
            "   updated_at=excluded.updated_at,"
            "   baseline_done=excluded.baseline_done",
            (
                album_id,
                name,
                asset_count,
                member_count,
                to_iso_utc(updated_at),
                1 if baseline_done else 0,
            ),
        )

    # --- assets -----------------------------------------------------------

    def get_known_asset_ids(self, album_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT asset_id FROM album_asset WHERE album_id = ?", (album_id,)
        ).fetchall()
        return {r["asset_id"] for r in rows}

    def add_known_assets(self, album_id: str, asset_ids: Iterable[str]) -> None:
        self._conn.executemany(
            "INSERT INTO album_asset(album_id, asset_id) VALUES(?, ?)"
            " ON CONFLICT(album_id, asset_id) DO NOTHING",
            [(album_id, aid) for aid in asset_ids],
        )

    def remove_known_assets(self, album_id: str, asset_ids: Iterable[str]) -> None:
        self._conn.executemany(
            "DELETE FROM album_asset WHERE album_id = ? AND asset_id = ?",
            [(album_id, aid) for aid in asset_ids],
        )

    # --- members ----------------------------------------------------------

    def get_known_member_ids(self, album_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT user_id FROM album_member WHERE album_id = ?", (album_id,)
        ).fetchall()
        return {r["user_id"] for r in rows}

    def add_known_members(self, album_id: str, user_ids: Iterable[str]) -> None:
        self._conn.executemany(
            "INSERT INTO album_member(album_id, user_id) VALUES(?, ?)"
            " ON CONFLICT(album_id, user_id) DO NOTHING",
            [(album_id, uid) for uid in user_ids],
        )

    def remove_known_members(self, album_id: str, user_ids: Iterable[str]) -> None:
        self._conn.executemany(
            "DELETE FROM album_member WHERE album_id = ? AND user_id = ?",
            [(album_id, uid) for uid in user_ids],
        )

    # --- run counter ------------------------------------------------------

    def get_run_count(self) -> int:
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'run_count'"
        ).fetchone()
        return int(row["value"]) if row else 0

    def increment_run_count(self) -> int:
        self._conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('run_count', '1')"
            " ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1"
        )
        return self.get_run_count()
