from builders import NOW

from immich_user_notify.store import Store


def test_schema_idempotent(db_path):
    Store(db_path).close()
    Store(db_path).close()  # re-migrate, no error


def test_unknown_album_state_none(store):
    assert store.get_album_state("nope") is None


def test_upsert_and_get_album_state(store):
    store.upsert_album_meta("a1", name="Trip", asset_count=3, updated_at=NOW, baseline_done=True)
    st = store.get_album_state("a1")
    assert st is not None
    assert st.name == "Trip"
    assert st.asset_count == 3
    assert st.baseline_done is True
    assert st.updated_at == NOW


def test_assets_roundtrip_and_idempotent(store):
    store.upsert_album_meta("a1", name="T", asset_count=0, updated_at=NOW, baseline_done=True)
    store.add_known_assets("a1", ["x", "y"])
    store.add_known_assets("a1", ["y", "z"])  # duplicate y ignored
    assert store.get_known_asset_ids("a1") == {"x", "y", "z"}
    store.remove_known_assets("a1", ["x"])
    assert store.get_known_asset_ids("a1") == {"y", "z"}


def test_members_roundtrip(store):
    store.upsert_album_meta("a1", name="T", asset_count=0, updated_at=NOW, baseline_done=True)
    store.add_known_members("a1", ["u1", "u2"])
    assert store.get_known_member_ids("a1") == {"u1", "u2"}
    store.remove_known_members("a1", ["u1"])
    assert store.get_known_member_ids("a1") == {"u2"}


def test_album_isolation(store):
    store.upsert_album_meta("a1", name="T", asset_count=0, updated_at=NOW, baseline_done=True)
    store.upsert_album_meta("a2", name="U", asset_count=0, updated_at=NOW, baseline_done=True)
    store.add_known_assets("a1", ["x"])
    store.add_known_assets("a2", ["y"])
    assert store.get_known_asset_ids("a1") == {"x"}
    assert store.get_known_asset_ids("a2") == {"y"}


def test_persistence_across_reopen(db_path):
    s = Store(db_path)
    s.upsert_album_meta("a1", name="T", asset_count=1, updated_at=NOW, baseline_done=True)
    s.add_known_assets("a1", ["x"])
    s.close()
    s2 = Store(db_path)
    assert s2.get_known_asset_ids("a1") == {"x"}
    assert s2.get_album_state("a1").asset_count == 1
    s2.close()


def test_run_count(store):
    assert store.get_run_count() == 0
    assert store.increment_run_count() == 1
    assert store.increment_run_count() == 2
    assert store.get_run_count() == 2
