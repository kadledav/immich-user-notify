import json
import logging
from datetime import timedelta

import responses
from builders import NOW, album_detail, album_summary, user

from immich_user_notify.app import App
from immich_user_notify.config import Config
from immich_user_notify.store import Store


def _posts(rsps):
    return [c.request for c in rsps.calls if c.request.method == "POST"]


def _albums(base):
    return f"{base}/api/albums"


def _album(base, album_id="album-1"):
    return f"{base}/api/albums/{album_id}"


def _body(req):
    return json.loads(req.body)


def _topic(req):
    return _body(req)["topic"]


def test_full_cycle_exact_posts(
    mocked_responses, immich, ntfy, store, translator, clock, immich_base, ntfy_base, db_path
):
    owner = user("owner", "owner@example.com", "Owner")
    carol = user("carol", "carol@example.com", "Carol")
    bob = user("userb", "userb@example.com", "Bob")
    members = [carol, bob]

    config = Config(
        immich_token="test-token",
        immich_private_url=immich_base,
        immich_public_url="https://photos.example.com",
        ntfy_internal_url=ntfy_base,
        ntfy_publisher_username="pub",
        ntfy_publisher_password="secret",
        interval_minutes=15,
        db_path=db_path,
        default_language="en",
        user_languages={"owner@example.com": "cs"},
    )
    app = App(config, immich, ntfy, store, translator, clock=clock)

    t0 = NOW - timedelta(hours=2)

    # --- Cycle 1: pre-existing album (created before bootstrap) -> silent baseline ---
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=1, updated_at=t0, members=members)])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=members, counts={"owner": 1}, updated_at=t0))
    app.run_once()
    assert _posts(mocked_responses) == []
    assert store.get_contributor_counts("album-1") == {"owner": 1}

    # --- Cycle 2: Bob adds a photo -> notifies everyone but Bob ---
    mocked_responses.reset()
    t1 = NOW - timedelta(minutes=5)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=members)])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=members, counts={"owner": 1, "userb": 1}, updated_at=t1))
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()

    by_topic = {_topic(p): p for p in _posts(mocked_responses)}
    assert set(by_topic) == {"immich-owner", "immich-carol"}  # userb (contributor) excluded
    assert _body(by_topic["immich-owner"])["title"] == "Nové fotky"
    assert _body(by_topic["immich-owner"])["message"] == "Bob přidal(a) nové fotky do alba „Trip“."
    assert _body(by_topic["immich-carol"])["title"] == "New photos"
    assert _body(by_topic["immich-carol"])["message"] == 'Bob added new photos to "Trip".'
    assert _body(by_topic["immich-carol"])["click"] == "https://photos.example.com/albums/album-1"
    assert by_topic["immich-owner"].headers["Authorization"].startswith("Basic ")

    # --- Cycle 3: a new member (dave). Only the member_count gate fires; only dave notified. ---
    mocked_responses.reset()
    dave = user("dave", "dave@example.com", "Dave")
    members3 = [carol, bob, dave]
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=members3)])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=members3, counts={"owner": 1, "userb": 1}, updated_at=t1))
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()

    posts = _posts(mocked_responses)
    assert {_topic(p) for p in posts} == {"immich-dave"}
    assert _body(posts[0])["title"] == "Album shared with you"
    assert _body(posts[0])["message"] == 'You have been added to "Trip".'

    # --- Cycle 4: identical -> cheap skip, no posts, no detail fetch ---
    mocked_responses.reset()
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=members3)])
    app.run_once()
    assert _posts(mocked_responses) == []
    assert all("/albums/album-1" not in c.request.url for c in mocked_responses.calls)


def _baseline(app, mr, immich_base, owner, members, counts, updated_at):
    mr.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=sum(counts.values()), updated_at=updated_at, members=members)])
    mr.get(_album(immich_base), json=album_detail(owner=owner, members=members, counts=counts, updated_at=updated_at))
    app.run_once()
    mr.reset()


def test_immich_list_error_aborts_with_no_posts_or_state(app, store, mocked_responses, immich_base):
    mocked_responses.get(f"{immich_base}/api/albums", status=500, json={})
    stats = app.run_once()
    assert _posts(mocked_responses) == []
    assert stats.errors == 1
    assert store.get_album_state("album-1") is None


def test_no_albums(app, mocked_responses, immich_base):
    mocked_responses.get(f"{immich_base}/api/albums", json=[])
    stats = app.run_once()
    assert _posts(mocked_responses) == []
    assert stats.albums_seen == 0


def test_added_photo_notifies_and_is_recorded(app, store, mocked_responses, immich_base, ntfy_base):
    owner = user("owner", "owner@example.com", "Owner")
    member = user("m", "m@example.com", "M")
    t0 = NOW - timedelta(hours=3)
    _baseline(app, mocked_responses, immich_base, owner, [member], {"owner": 1}, t0)

    t1 = NOW - timedelta(minutes=1)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=[member])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[member], counts={"owner": 2}, updated_at=t1))
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()

    posts = _posts(mocked_responses)
    assert {_topic(p) for p in posts} == {"immich-m"}   # owner is sole contributor -> excluded
    assert _body(posts[0])["title"] == "New photos"
    assert store.get_contributor_counts("album-1") == {"owner": 2}


def test_asset_count_unchanged_but_updated_at_bumped_still_notifies(
    app, store, mocked_responses, immich_base, ntfy_base
):
    # One photo removed, another added by someone else: assetCount is identical, so only
    # updatedAt opens the gate -- and the per-contributor deltas find the real change.
    owner = user("owner", "owner@example.com", "Owner")
    bob = user("bob", "bob@example.com", "Bob")
    t0 = NOW - timedelta(hours=3)
    _baseline(app, mocked_responses, immich_base, owner, [bob], {"owner": 2}, t0)

    t1 = NOW - timedelta(minutes=1)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=[bob])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[bob], counts={"owner": 1, "bob": 1}, updated_at=t1))
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()

    assert {_topic(p) for p in _posts(mocked_responses)} == {"immich-owner"}  # bob excluded
    assert store.get_contributor_counts("album-1") == {"owner": 1, "bob": 1}


def test_new_album_notifies_its_members(
    mocked_responses, immich, ntfy, store, translator, config, immich_base, ntfy_base
):
    holder = {"t": NOW}
    app = App(config, immich, ntfy, store, translator, clock=lambda: holder["t"])
    owner = user("owner", "owner@example.com", "Owner")

    # Run 1: a pre-existing (old) album -> sets bootstrap_at = NOW, baselined silently.
    old_dt = NOW - timedelta(days=5)
    mocked_responses.get(_albums(immich_base), json=[album_summary(id="album-1", owner=owner, asset_count=1, updated_at=old_dt, members=[])])
    mocked_responses.get(_album(immich_base, "album-1"), json=album_detail(id="album-1", owner=owner, members=[], counts={"owner": 1}, updated_at=old_dt))
    app.run_once()
    assert _posts(mocked_responses) == []
    mocked_responses.reset()

    # Clock advances; a brand-new album (created after bootstrap) appears, shared with carol.
    holder["t"] = NOW + timedelta(minutes=10)
    carol = user("carol", "carol@example.com", "Carol")
    created = NOW + timedelta(minutes=5)  # after bootstrap (NOW), before clock (NOW+10)
    mocked_responses.get(
        _albums(immich_base),
        json=[
            album_summary(id="album-1", owner=owner, asset_count=1, updated_at=old_dt, members=[]),
            album_summary(id="album-2", name="New Album", owner=owner, asset_count=2, updated_at=created, members=[carol]),
        ],
    )
    mocked_responses.get(
        _album(immich_base, "album-2"),
        json=album_detail(id="album-2", name="New Album", owner=owner, members=[carol],
                          counts={"owner": 2}, updated_at=created, created_at=created),
    )
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()

    posts = _posts(mocked_responses)
    # Only the new member: the owner/creator is never told about their own album, which is
    # the regression guard for the owner now living inside albumUsers.
    assert {_topic(p) for p in posts} == {"immich-carol"}
    assert _body(posts[0])["title"] == "Album shared with you"
    assert _body(posts[0])["message"] == 'You have been added to "New Album".'

    # The new album's existing photos are recorded, not re-announced next run.
    mocked_responses.reset()
    mocked_responses.get(
        _albums(immich_base),
        json=[
            album_summary(id="album-1", owner=owner, asset_count=1, updated_at=old_dt, members=[]),
            album_summary(id="album-2", name="New Album", owner=owner, asset_count=2, updated_at=created, members=[carol]),
        ],
    )
    app.run_once()
    assert _posts(mocked_responses) == []
    assert store.get_contributor_counts("album-2") == {"owner": 2}


def test_new_member_and_new_asset_same_cycle(app, store, mocked_responses, immich_base, ntfy_base):
    owner = user("owner", "owner@example.com", "Owner")
    alice = user("alice", "alice@example.com", "Alice")
    t0 = NOW - timedelta(hours=2)
    _baseline(app, mocked_responses, immich_base, owner, [alice], {"owner": 1}, t0)

    # Same cycle: alice adds a photo AND dave is invited.
    dave = user("dave", "dave@example.com", "Dave")
    t1 = NOW - timedelta(minutes=1)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=[alice, dave])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[alice, dave], counts={"owner": 1, "alice": 1}, updated_at=t1))
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()

    posts = {_topic(p): _body(p) for p in _posts(mocked_responses)}
    # alice = sole contributor (excluded from photo notif); dave = just invited
    # (gets ONLY the access message, not the photo notif); owner gets the photo notif.
    assert set(posts) == {"immich-owner", "immich-dave"}
    assert posts["immich-owner"]["title"] == "New photos"
    assert posts["immich-dave"]["title"] == "Album shared with you"


def test_ntfy_partial_failure_persists_and_no_respam(app, store, mocked_responses, immich_base, ntfy_base):
    owner = user("owner", "owner@example.com", "Owner")
    alice = user("alice", "alice@example.com", "Alice")
    bob = user("bob", "bob@example.com", "Bob")
    t0 = NOW - timedelta(hours=2)
    _baseline(app, mocked_responses, immich_base, owner, [alice, bob], {"owner": 1}, t0)

    # Bob adds a photo (sole contributor) -> recipients owner + alice.
    t1 = NOW - timedelta(minutes=2)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=[alice, bob])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[alice, bob], counts={"owner": 1, "bob": 1}, updated_at=t1))

    def cb(request):
        topic = json.loads(request.body)["topic"]
        return (500 if topic == "immich-alice" else 200, {}, "")

    mocked_responses.add_callback(responses.POST, f"{ntfy_base}/", callback=cb)
    stats = app.run_once()

    topics = {_topic(p) for p in _posts(mocked_responses)}
    assert topics == {"immich-owner", "immich-alice"}      # both attempted
    assert stats.messages_sent == 1
    assert stats.messages_failed == 1
    # persisted despite a failure
    assert store.get_contributor_counts("album-1") == {"owner": 1, "bob": 1}

    # Next identical cycle: cheap skip -> no re-spam to the topic that DID succeed.
    mocked_responses.reset()
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=[alice, bob])])
    app.run_once()
    assert _posts(mocked_responses) == []


def test_unshare_then_reshare(app, store, mocked_responses, immich_base, ntfy_base):
    owner = user("owner", "owner@example.com", "Owner")
    alice = user("alice", "alice@example.com", "Alice")
    t0 = NOW - timedelta(hours=2)
    _baseline(app, mocked_responses, immich_base, owner, [alice], {"owner": 1, "alice": 1}, t0)

    # Un-shared: Immich reports shared=false and omits contributorCounts entirely.
    t1 = NOW - timedelta(minutes=30)
    unshared = album_detail(owner=owner, members=[], asset_count=2, updated_at=t1)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, shared=False, updated_at=t1, members=[])])
    mocked_responses.get(_album(immich_base), json=unshared)
    app.run_once()
    assert _posts(mocked_responses) == []
    # No counts in the payload -> stored counts survive untouched, members are forgotten.
    assert store.get_contributor_counts("album-1") == {"owner": 1, "alice": 1}
    assert store.get_known_member_ids("album-1") == set()

    # Re-shared with alice, and the owner added a photo while it was private.
    mocked_responses.reset()
    t2 = NOW - timedelta(minutes=1)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=3, updated_at=t2, members=[alice])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[alice], counts={"owner": 2, "alice": 1}, updated_at=t2))
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()

    posts = {_topic(p): _body(p) for p in _posts(mocked_responses)}
    # alice is re-invited, so she gets only the access message; the owner is the sole
    # contributor of the new photo and is therefore not notified about it.
    assert set(posts) == {"immich-alice"}
    assert posts["immich-alice"]["title"] == "Album shared with you"
    assert store.get_contributor_counts("album-1") == {"owner": 2, "alice": 1}


def test_missing_contributor_counts_on_tracked_album_is_inert(
    app, store, mocked_responses, immich_base
):
    owner = user("owner", "owner@example.com", "Owner")
    alice = user("alice", "alice@example.com", "Alice")
    t0 = NOW - timedelta(hours=2)
    _baseline(app, mocked_responses, immich_base, owner, [alice], {"owner": 2}, t0)

    # Still shared, but the field is absent: treat as "no signal", never as "zero assets".
    t1 = NOW - timedelta(minutes=1)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=3, updated_at=t1, members=[alice])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[alice], asset_count=3, updated_at=t1))
    stats = app.run_once()

    assert _posts(mocked_responses) == []
    assert stats.errors == 0
    assert store.get_contributor_counts("album-1") == {"owner": 2}


def test_upgraded_v1_db_first_run_is_silent(
    mocked_responses, immich, ntfy, translator, config, db_path, clock, immich_base, ntfy_base
):
    """A DB migrated from schema 1 re-baselines silently, then behaves normally."""
    from test_store import _write_v1_db

    _write_v1_db(db_path)  # pretends the Immich 2.x build left state behind
    store = Store(db_path)
    app = App(config, immich, ntfy, store, translator, clock=clock)
    owner = user("owner", "owner@example.com", "Owner")
    alice = user("alice", "alice@example.com", "Alice")
    # An album created *after* the (now-cleared) bootstrap must still stay silent, because
    # the migration resets bootstrap_at to this run's clock.
    created = NOW - timedelta(days=1)

    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=5, updated_at=created, members=[alice])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[alice], counts={"owner": 3, "alice": 2}, updated_at=created, created_at=created))
    app.run_once()
    assert _posts(mocked_responses) == []
    assert store.get_contributor_counts("album-1") == {"owner": 3, "alice": 2}

    # Second run: normal notifications resume.
    mocked_responses.reset()
    t1 = NOW - timedelta(minutes=1)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=6, updated_at=t1, members=[alice])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[alice], counts={"owner": 3, "alice": 3}, updated_at=t1))
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()
    assert {_topic(p) for p in _posts(mocked_responses)} == {"immich-owner"}
    store.close()


def test_startup_logs_version_and_topic_mapping(app, mocked_responses, immich_base, caplog):
    mocked_responses.get(
        f"{immich_base}/api/server/version", json={"major": 3, "minor": 0, "patch": 0}
    )
    mocked_responses.get(f"{immich_base}/api/users/me", json=user("me", "me@example.com", "Me"))
    mocked_responses.get(
        f"{immich_base}/api/users",
        json=[
            user("u1", "david.k@a.com", "David K"),     # -> topic immich-david-k
            user("u2", "david-k@b.com", "David K2"),    # -> topic immich-david-k (collision)
            user("u3", "jane@c.com", "Jane"),           # -> topic immich-jane
        ],
    )
    with caplog.at_level(logging.INFO):
        app._log_startup()
    text = caplog.text
    assert "Immich server version 3.0.0" in text
    assert "immich-david-k" in text
    assert "immich-jane" in text
    assert "COLLISION" in text


def test_startup_warns_on_non_v3_server(app, mocked_responses, immich_base, caplog):
    mocked_responses.get(
        f"{immich_base}/api/server/version", json={"major": 2, "minor": 7, "patch": 5}
    )
    mocked_responses.get(f"{immich_base}/api/users/me", json=user("me", "me@example.com", "Me"))
    mocked_responses.get(f"{immich_base}/api/users", json=[])
    with caplog.at_level(logging.INFO):
        app._log_startup()
    assert "targets the Immich 3.x API" in caplog.text
