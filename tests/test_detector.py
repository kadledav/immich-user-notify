from datetime import timedelta

from builders import A, D, M, NOW, state

from immich_user_notify.detector import diff_album
from immich_user_notify.models import AssetsAddedEvent, MemberAddedEvent

WINDOW = 3 * 15 * 60  # 2700s


def diff(detail, *, prior=None, known_assets=(), known_members=(), now=NOW, window=WINDOW):
    return diff_album(
        detail=detail,
        prior=prior,
        known_asset_ids=set(known_assets),
        known_member_ids=set(known_members),
        now=now,
        recency_window_s=window,
    )


def asset_events(result):
    return [e for e in result.events if isinstance(e, AssetsAddedEvent)]


def member_events(result):
    return [e for e in result.events if isinstance(e, MemberAddedEvent)]


def test_first_run_baseline_no_events():
    d = D(members=[M("u1", "u1@x.com")], assets=[A("a1", "owner")])
    r = diff(d, prior=None)
    assert r.is_baseline is True
    assert r.events == []
    assert set(r.assets_to_add) == {"a1"}
    assert set(r.members_to_add) == {"u1"}


def test_baseline_when_flag_false():
    d = D(assets=[A("a1", "owner")])
    r = diff(d, prior=state(baseline_done=False), known_assets={"a0"})
    assert r.is_baseline is True
    assert r.events == []


def test_single_new_asset():
    d = D(assets=[A("a1", "owner"), A("a2", "owner", NOW - timedelta(minutes=1))])
    r = diff(d, prior=state(), known_assets={"a1"})
    assert r.assets_to_add == ["a2"]
    ev = asset_events(r)
    assert len(ev) == 1
    assert ev[0].new_asset_count == 1
    assert ev[0].contributor_ids == ["owner"]


def test_multiple_contributors():
    d = D(
        assets=[
            A("a1", "owner"),
            A("a2", "b", NOW - timedelta(minutes=1)),
            A("a3", "c", NOW - timedelta(minutes=2)),
        ]
    )
    r = diff(d, prior=state(), known_assets={"a1"})
    ev = asset_events(r)[0]
    assert ev.new_asset_count == 2
    assert ev.contributor_ids == ["b", "c"]


def test_new_member_event():
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


def test_recency_guard_skips_old_asset():
    old = A("old", "owner", NOW - timedelta(seconds=WINDOW + 100))
    d = D(assets=[A("a1", "owner"), old])
    r = diff(d, prior=state(), known_assets={"a1"})
    assert "old" in r.assets_to_add        # still recorded as seen
    assert asset_events(r) == []           # but not notified


def test_recency_boundary_inclusive():
    at_boundary = D(assets=[A("b", "owner", NOW - timedelta(seconds=WINDOW))])
    just_over = D(assets=[A("o", "owner", NOW - timedelta(seconds=WINDOW + 1))])
    assert len(asset_events(diff(at_boundary, prior=state()))) == 1
    assert asset_events(diff(just_over, prior=state())) == []


def test_clock_skew_future_asset_is_recent():
    future = D(assets=[A("f", "owner", NOW + timedelta(minutes=5))])
    assert len(asset_events(diff(future, prior=state()))) == 1
