"""SQLite state store. Holds, per album, the member IDs and the per-contributor asset
counts seen on the last run, plus a tiny meta row. The DB mirrors the album's *current*
state (a contributor whose assets are all removed loses their row).

No asset IDs and no asset names are stored -- only album ids, user ids and counts.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator, Mapping

from .timeutil import parse_immich_dt, to_iso_utc

log = logging.getLogger(__name__)

# 1 = per-asset-id tracking (Immich 2.x). 2 = per-contributor counts (Immich 3.x).
_SCHEMA_VERSION = "2"


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
            # Read the version *before* anything writes it.
            row = c.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            from_version = row["value"] if row else None

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
                "CREATE TABLE IF NOT EXISTS album_contributor ("
                " album_id TEXT NOT NULL REFERENCES album(album_id) ON DELETE CASCADE,"
                " user_id TEXT NOT NULL,"
                " asset_count INTEGER NOT NULL,"
                " PRIMARY KEY (album_id, user_id))"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS album_member ("
                " album_id TEXT NOT NULL REFERENCES album(album_id) ON DELETE CASCADE,"
                " user_id TEXT NOT NULL,"
                " PRIMARY KEY (album_id, user_id))"
            )

            if from_version == "1":
                # Immich 3.0 stopped returning album assets, so the asset-id snapshots are
                # unusable. Drop them and forget every album, then clear bootstrap_at so the
                # next run re-establishes it: with no album rows and a fresh bootstrap every
                # album is "pre-existing" and gets baselined silently, exactly like a first
                # install against an existing library. No notifications for that one run.
                c.execute("DROP TABLE IF EXISTS album_asset")
                c.execute("DELETE FROM album")  # cascades album_member/album_contributor
                c.execute("DELETE FROM schema_meta WHERE key = 'bootstrap_at'")
                log.warning(
                    "migrated state DB from schema 1 to %s (Immich 3.0 API): all albums will"
                    " be re-baselined silently on this run; notifications resume next run",
                    _SCHEMA_VERSION,
                )

            c.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
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

    # --- contributor counts -----------------------------------------------

    def get_contributor_counts(self, album_id: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT user_id, asset_count FROM album_contributor WHERE album_id = ?",
            (album_id,),
        ).fetchall()
        return {r["user_id"]: r["asset_count"] for r in rows}

    def replace_contributor_counts(self, album_id: str, counts: Mapping[str, int]) -> None:
        """Replace the album's whole map. A contributor missing from `counts` is deleted:
        leaving a stale count behind would swallow that user's next upload."""
        self._conn.execute("DELETE FROM album_contributor WHERE album_id = ?", (album_id,))
        self._conn.executemany(
            "INSERT INTO album_contributor(album_id, user_id, asset_count) VALUES(?, ?, ?)",
            [(album_id, uid, n) for uid, n in counts.items()],
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

    def get_or_set_bootstrap_at(self, now: datetime) -> datetime:
        """Return the one-time bootstrap timestamp (set on the very first run).

        Albums that already existed at this moment are treated as pre-existing and
        baselined silently; albums created after it are 'new' and notify their members.
        """
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'bootstrap_at'"
        ).fetchone()
        if row is not None:
            return parse_immich_dt(row["value"])
        self._conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('bootstrap_at', ?)"
            " ON CONFLICT(key) DO NOTHING",
            (to_iso_utc(now),),
        )
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'bootstrap_at'"
        ).fetchone()
        return parse_immich_dt(row["value"])

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
