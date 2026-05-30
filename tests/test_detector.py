from datetime import timedelta

from builders import A, D, M, NOW, state

from immich_user_notify.detector import diff_album
from immich_user_notify.models import AssetsAddedEvent, MemberAddedEvent

BOOTSTRAP = NOW - timedelta(hours=1)  # the app's first-run boundary, in the past


def diff(detail, *, prior=None, known_assets=(), known_members=(), bootstrap_at=BOOTSTRAP):
    return diff_album(
        detail=detail,
        prior=prior,
        known_asset_ids=set(known_assets),
        known_member_ids=set(known_members),
        bootstrap_at=bootstrap_at,
    )


def asset_events(result):
    return [e for e in result.events if isinstance(e, AssetsAddedEvent)]


def member_events(result):
    return [e for e in result.events if isinstance(e, MemberAddedEvent)]


# --- first sight of an album ------------------------------------------------


def test_preexisting_album_silent_baseline():
    # Created before bootstrap -> an album you already had -> recorded silently.
    d = D(
        members=[M("u1", "u1@x.com")],
        assets=[A("a1", "owner")],
        created_at=NOW - timedelta(days=10),
    )
    r = diff(d, prior=None)
    assert r.is_baseline is True
    assert r.events == []
    assert set(r.assets_to_add) == {"a1"}
    assert set(r.members_to_add) == {"u1"}


def test_new_album_notifies_members():
    # Created after bootstrap -> genuinely new -> notify members; assets recorded silently.
    d = D(
        members=[M("u1", "u1@x.com", "U1"), M("u2", "u2@x.com", "U2")],
        assets=[A("a1", "owner")],
        created_at=NOW,
    )
    r = diff(d, prior=None)
    assert r.is_baseline is False
    assert {e.new_member.user_id for e in member_events(r)} == {"u1", "u2"}
    assert asset_events(r) == []            # initial content not separately announced
    assert set(r.assets_to_add) == {"a1"}   # but recorded as seen


def test_new_album_with_no_members_emits_nothing():
    d = D(members=[], assets=[A("a1", "owner")], created_at=NOW)
    r = diff(d, prior=None)
    assert r.events == []


def test_baseline_when_flag_false_uses_created_at():
    d = D(assets=[A("a1", "owner")], created_at=NOW - timedelta(days=5))
    r = diff(d, prior=state(baseline_done=False), known_assets={"a0"})
    assert r.is_baseline is True
    assert r.events == []


# --- tracked album ----------------------------------------------------------


def test_single_new_asset_notifies():
    d = D(assets=[A("a1", "owner"), A("a2", "owner")])
    r = diff(d, prior=state(), known_assets={"a1"})
    assert r.assets_to_add == ["a2"]
    ev = asset_events(r)
    assert len(ev) == 1
    assert ev[0].new_asset_count == 1
    assert ev[0].contributor_ids == ["owner"]


def test_old_upload_asset_still_notifies():
    # The key fix: a photo uploaded long ago, added to a tracked album now, notifies.
    old = A("old", "owner", NOW - timedelta(days=365))
    d = D(assets=[A("a1", "owner"), old])
    r = diff(d, prior=state(), known_assets={"a1"})
    assert asset_events(r)[0].new_asset_count == 1
    assert "old" in r.assets_to_add


def test_multiple_contributors():
    d = D(assets=[A("a1", "owner"), A("a2", "b"), A("a3", "c")])
    r = diff(d, prior=state(), known_assets={"a1"})
    ev = asset_events(r)[0]
    assert ev.new_asset_count == 2
    assert ev.contributor_ids == ["b", "c"]


def test_new_member_on_tracked_album():
    d = D(members=[M("u1", "u1@x.com", "U1")], assets=[A("a1", "owner")])
    r = diff(d, prior=state(), known_assets={"a1"}, known_members=set())
    me = member_events(r)
    assert len(me) == 1
    assert me[0].new_member.user_id == "u1"
    assert r.members_to_add == ["u1"]


def test_removed_asset_recorded_not_notified():
    d = D(assets=[A("a1", "owner")])
    r = diff(d, prior=state(), known_assets={"a1", "a2"})
    assert asset_events(r) == []
    assert r.assets_to_remove == ["a2"]


def test_removed_member_recorded_not_notified():
    d = D(members=[], assets=[A("a1", "owner")])
    r = diff(d, prior=state(), known_assets={"a1"}, known_members={"u9"})
    assert member_events(r) == []
    assert r.members_to_remove == ["u9"]


def test_no_changes_no_events():
    d = D(assets=[A("a1", "owner")], members=[M("u1", "u1@x.com")])
    r = diff(d, prior=state(), known_assets={"a1"}, known_members={"u1"})
    assert r.events == []
