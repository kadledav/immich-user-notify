import json
import logging
from datetime import timedelta

import responses
from builders import NOW, album_detail, album_summary, asset, user

from immich_user_notify.app import App
from immich_user_notify.config import Config


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
    a1 = asset("a1", "owner", t0)

    # --- Cycle 1: pre-existing album (created before bootstrap) -> silent baseline ---
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=1, updated_at=t0, members=members)])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=members, assets=[a1], updated_at=t0))
    app.run_once()
    assert _posts(mocked_responses) == []

    # --- Cycle 2: Bob adds a photo that was UPLOADED long ago -> still notifies ---
    mocked_responses.reset()
    a2 = asset("a2", "userb", NOW - timedelta(days=30))  # old upload, added to album now
    t1 = NOW - timedelta(minutes=5)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=members)])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=members, assets=[a1, a2], updated_at=t1))
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
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=members3, assets=[a1, a2], updated_at=t1))
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


def _baseline(app, mr, immich_base, owner, members, assets, updated_at):
    mr.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=len(assets), updated_at=updated_at, members=members)])
    mr.get(_album(immich_base), json=album_detail(owner=owner, members=members, assets=assets, updated_at=updated_at))
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


def test_old_upload_photo_still_notifies(app, store, mocked_responses, immich_base, ntfy_base):
    owner = user("owner", "owner@example.com", "Owner")
    member = user("m", "m@example.com", "M")
    t0 = NOW - timedelta(hours=3)
    _baseline(app, mocked_responses, immich_base, owner, [member], [asset("a1", "owner", t0)], t0)

    old = asset("old", "owner", NOW - timedelta(days=400))  # uploaded ages ago, added now
    t1 = NOW - timedelta(minutes=1)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=[member])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[member], assets=[asset("a1", "owner", t0), old], updated_at=t1))
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()

    posts = _posts(mocked_responses)
    assert {_topic(p) for p in posts} == {"immich-m"}   # owner is sole contributor -> excluded
    assert _body(posts[0])["title"] == "New photos"
    assert "old" in store.get_known_asset_ids("album-1")


def test_new_album_notifies_its_members(
    mocked_responses, immich, ntfy, store, translator, config, immich_base, ntfy_base
):
    holder = {"t": NOW}
    app = App(config, immich, ntfy, store, translator, clock=lambda: holder["t"])
    owner = user("owner", "owner@example.com", "Owner")

    # Run 1: a pre-existing (old) album -> sets bootstrap_at = NOW, baselined silently.
    old_dt = NOW - timedelta(days=5)
    mocked_responses.get(_albums(immich_base), json=[album_summary(id="album-1", owner=owner, asset_count=1, updated_at=old_dt, members=[])])
    mocked_responses.get(_album(immich_base, "album-1"), json=album_detail(id="album-1", owner=owner, members=[], assets=[asset("a1", "owner", old_dt)], updated_at=old_dt))
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
                          assets=[asset("x", "owner", NOW - timedelta(days=400)), asset("y", "owner", created)],
                          updated_at=created, created_at=created),
    )
    mocked_responses.post(f"{ntfy_base}/", status=200)
    app.run_once()

    posts = _posts(mocked_responses)
    assert {_topic(p) for p in posts} == {"immich-carol"}   # new member notified, no asset spam
    assert _body(posts[0])["title"] == "Album shared with you"
    assert _body(posts[0])["message"] == 'You have been added to "New Album".'


def test_new_member_and_new_asset_same_cycle(app, store, mocked_responses, immich_base, ntfy_base):
    owner = user("owner", "owner@example.com", "Owner")
    alice = user("alice", "alice@example.com", "Alice")
    t0 = NOW - timedelta(hours=2)
    _baseline(app, mocked_responses, immich_base, owner, [alice], [asset("a1", "owner", t0)], t0)

    # Same cycle: alice adds a photo AND dave is invited.
    dave = user("dave", "dave@example.com", "Dave")
    a2 = asset("a2", "alice", NOW - timedelta(minutes=1))
    t1 = NOW - timedelta(minutes=1)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=[alice, dave])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[alice, dave], assets=[asset("a1", "owner", t0), a2], updated_at=t1))
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
    _baseline(app, mocked_responses, immich_base, owner, [alice, bob], [asset("a1", "owner", t0)], t0)

    # Bob adds a photo (sole contributor) -> recipients owner + alice.
    a2 = asset("a2", "bob", NOW - timedelta(minutes=2))
    t1 = NOW - timedelta(minutes=2)
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=[alice, bob])])
    mocked_responses.get(_album(immich_base), json=album_detail(owner=owner, members=[alice, bob], assets=[asset("a1", "owner", t0), a2], updated_at=t1))

    def cb(request):
        topic = json.loads(request.body)["topic"]
        return (500 if topic == "immich-alice" else 200, {}, "")

    mocked_responses.add_callback(responses.POST, f"{ntfy_base}/", callback=cb)
    stats = app.run_once()

    topics = {_topic(p) for p in _posts(mocked_responses)}
    assert topics == {"immich-owner", "immich-alice"}      # both attempted
    assert stats.messages_sent == 1
    assert stats.messages_failed == 1
    assert "a2" in store.get_known_asset_ids("album-1")  # persisted despite a failure

    # Next identical cycle: cheap skip -> no re-spam to the topic that DID succeed.
    mocked_responses.reset()
    mocked_responses.get(_albums(immich_base), json=[album_summary(owner=owner, asset_count=2, updated_at=t1, members=[alice, bob])])
    app.run_once()
    assert _posts(mocked_responses) == []


def test_startup_topic_mapping_logs_collision(app, mocked_responses, immich_base, caplog):
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
    assert "immich-david-k" in text
    assert "immich-jane" in text
    assert "COLLISION" in text
