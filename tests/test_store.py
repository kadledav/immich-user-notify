import sqlite3

from builders import NOW

from immich_user_notify.store import Store
from immich_user_notify.timeutil import to_iso_utc


def test_schema_idempotent(db_path):
    Store(db_path).close()
    Store(db_path).close()  # re-migrate, no error


def test_unknown_album_state_none(store):
    assert store.get_album_state("nope") is None


def test_upsert_and_get_album_state(store):
    store.upsert_album_meta(
        "a1", name="Trip", asset_count=3, member_count=2, updated_at=NOW, baseline_done=True
    )
    st = store.get_album_state("a1")
    assert st is not None
    assert st.name == "Trip"
    assert st.asset_count == 3
    assert st.member_count == 2
    assert st.baseline_done is True
    assert st.updated_at == NOW


def test_contributor_counts_roundtrip_and_replace(store):
    store.upsert_album_meta("a1", name="T", asset_count=0, updated_at=NOW, baseline_done=True)
    assert store.get_contributor_counts("a1") == {}
    store.replace_contributor_counts("a1", {"u1": 2, "u2": 5})
    assert store.get_contributor_counts("a1") == {"u1": 2, "u2": 5}
    # Replacement is total: u2 disappears, u1 drops. A stale count would swallow the
    # affected user's next upload.
    store.replace_contributor_counts("a1", {"u1": 1})
    assert store.get_contributor_counts("a1") == {"u1": 1}
    store.replace_contributor_counts("a1", {})
    assert store.get_contributor_counts("a1") == {}


def test_members_roundtrip(store):
    store.upsert_album_meta("a1", name="T", asset_count=0, updated_at=NOW, baseline_done=True)
    store.add_known_members("a1", ["u1", "u2"])
    assert store.get_known_member_ids("a1") == {"u1", "u2"}
    store.remove_known_members("a1", ["u1"])
    assert store.get_known_member_ids("a1") == {"u2"}


def test_album_isolation(store):
    store.upsert_album_meta("a1", name="T", asset_count=0, updated_at=NOW, baseline_done=True)
    store.upsert_album_meta("a2", name="U", asset_count=0, updated_at=NOW, baseline_done=True)
    store.replace_contributor_counts("a1", {"x": 1})
    store.replace_contributor_counts("a2", {"y": 2})
    assert store.get_contributor_counts("a1") == {"x": 1}
    assert store.get_contributor_counts("a2") == {"y": 2}


def test_persistence_across_reopen(db_path):
    s = Store(db_path)
    s.upsert_album_meta(
        "a1", name="T", asset_count=1, member_count=3, updated_at=NOW, baseline_done=True
    )
    s.replace_contributor_counts("a1", {"x": 1})
    s.close()
    s2 = Store(db_path)
    assert s2.get_contributor_counts("a1") == {"x": 1}
    assert s2.get_album_state("a1").asset_count == 1
    assert s2.get_album_state("a1").member_count == 3
    s2.close()


def test_run_count(store):
    assert store.get_run_count() == 0
    assert store.increment_run_count() == 1
    assert store.increment_run_count() == 2
    assert store.get_run_count() == 2


# --- schema 1 -> 2 migration (Immich 2.x -> 3.x) -----------------------------


def _write_v1_db(path: str) -> None:
    """A DB exactly as the Immich 2.x version of the app left it."""
    c = sqlite3.connect(path, isolation_level=None)
    c.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    c.execute("INSERT INTO schema_meta VALUES('schema_version', '1')")
    c.execute("INSERT INTO schema_meta VALUES('bootstrap_at', ?)", (to_iso_utc(NOW),))
    c.execute("INSERT INTO schema_meta VALUES('run_count', '17')")
    c.execute(
        "CREATE TABLE album (album_id TEXT PRIMARY KEY, name TEXT NOT NULL,"
        " asset_count INTEGER NOT NULL DEFAULT 0, member_count INTEGER NOT NULL DEFAULT 0,"
        " updated_at TEXT NOT NULL, baseline_done INTEGER NOT NULL DEFAULT 0)"
    )
    c.execute(
        "CREATE TABLE album_asset (album_id TEXT NOT NULL REFERENCES album(album_id)"
        " ON DELETE CASCADE, asset_id TEXT NOT NULL, PRIMARY KEY (album_id, asset_id))"
    )
    c.execute(
        "CREATE TABLE album_member (album_id TEXT NOT NULL REFERENCES album(album_id)"
        " ON DELETE CASCADE, user_id TEXT NOT NULL, PRIMARY KEY (album_id, user_id))"
    )
    c.execute(
        "INSERT INTO album VALUES('a1', 'Trip', 2, 2, ?, 1)", (to_iso_utc(NOW),)
    )
    c.execute("INSERT INTO album_asset VALUES('a1', 'asset-1')")
    c.execute("INSERT INTO album_member VALUES('a1', 'u1')")
    c.close()


def _tables(path: str) -> set[str]:
    c = sqlite3.connect(path)
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


def _meta(path: str, key: str):
    c = sqlite3.connect(path)
    try:
        row = c.execute("SELECT value FROM schema_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        c.close()


def test_migrates_v1_db_to_v2(db_path):
    _write_v1_db(db_path)
    s = Store(db_path)
    # Every album is forgotten and bootstrap_at is cleared, so the next run re-baselines
    # everything silently instead of flooding users.
    assert s.get_album_state("a1") is None
    assert s.get_known_member_ids("a1") == set()
    assert s.get_contributor_counts("a1") == {}
    s.close()

    assert "album_asset" not in _tables(db_path)
    assert "album_contributor" in _tables(db_path)
    assert _meta(db_path, "schema_version") == "2"
    assert _meta(db_path, "bootstrap_at") is None
    assert _meta(db_path, "run_count") == "17"  # untouched


def test_migration_runs_once(db_path):
    _write_v1_db(db_path)
    Store(db_path).close()

    s = Store(db_path)
    s.upsert_album_meta("a1", name="T", asset_count=1, updated_at=NOW, baseline_done=True)
    s.replace_contributor_counts("a1", {"u1": 1})
    s.close()

    # Reopening must not wipe the freshly written state again.
    s2 = Store(db_path)
    assert s2.get_album_state("a1") is not None
    assert s2.get_contributor_counts("a1") == {"u1": 1}
    s2.close()


def test_fresh_db_is_schema_2(db_path):
    Store(db_path).close()
    assert _meta(db_path, "schema_version") == "2"
    assert "album_asset" not in _tables(db_path)
