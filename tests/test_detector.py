from datetime import timedelta

from builders import D, M, NOW, state

from immich_user_notify.detector import diff_album
from immich_user_notify.models import AssetsAddedEvent, MemberAddedEvent

BOOTSTRAP = NOW - timedelta(hours=1)  # the app's first-run boundary, in the past


def diff(detail, *, prior=None, known_counts=None, known_members=(), bootstrap_at=BOOTSTRAP):
    return diff_album(
        detail=detail,
        prior=prior,
        known_member_ids=set(known_members),
        known_contributor_counts=dict(known_counts or {}),
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
        counts={"owner": 1},
        created_at=NOW - timedelta(days=10),
    )
    r = diff(d, prior=None)
    assert r.is_baseline is True
    assert r.events == []
    assert r.contributor_counts_to_store == {"owner": 1}
    assert set(r.members_to_add) == {"u1"}


def test_new_album_notifies_members():
    # Created after bootstrap -> genuinely new -> notify members; counts recorded silently.
    d = D(
        members=[M("u1", "u1@x.com", "U1"), M("u2", "u2@x.com", "U2")],
        counts={"owner": 1},
        created_at=NOW,
    )
    r = diff(d, prior=None)
    assert r.is_baseline is False
    assert {e.new_member.user_id for e in member_events(r)} == {"u1", "u2"}
    assert asset_events(r) == []                        # initial content not announced
    assert r.contributor_counts_to_store == {"owner": 1}  # but recorded as seen


def test_new_album_with_no_members_emits_nothing():
    d = D(members=[], counts={"owner": 1}, created_at=NOW)
    r = diff(d, prior=None)
    assert r.events == []


def test_baseline_when_flag_false_uses_created_at():
    d = D(counts={"owner": 1}, created_at=NOW - timedelta(days=5))
    r = diff(d, prior=state(baseline_done=False), known_counts={"owner": 0})
    assert r.is_baseline is True
    assert r.events == []


# --- tracked album ----------------------------------------------------------


def test_single_new_asset_notifies():
    d = D(counts={"owner": 2})
    r = diff(d, prior=state(), known_counts={"owner": 1})
    assert r.contributor_counts_to_store == {"owner": 2}
    ev = asset_events(r)
    assert len(ev) == 1
    assert ev[0].new_asset_count == 1
    assert ev[0].contributor_ids == ["owner"]


def test_first_asset_for_a_new_contributor_notifies():
    d = D(counts={"owner": 1, "bob": 3})
    r = diff(d, prior=state(), known_counts={"owner": 1})
    ev = asset_events(r)[0]
    assert ev.new_asset_count == 3
    assert ev.contributor_ids == ["bob"]


def test_multiple_contributors():
    d = D(counts={"owner": 1, "b": 1, "c": 1})
    r = diff(d, prior=state(), known_counts={"owner": 1})
    ev = asset_events(r)[0]
    assert ev.new_asset_count == 2
    assert ev.contributor_ids == ["b", "c"]


def test_cross_user_compensation_still_notifies():
    # A adds 2 while B's 2 are removed: the album's total is unchanged, but A did add.
    d = D(counts={"a": 3, "b": 0})
    r = diff(d, prior=state(), known_counts={"a": 1, "b": 2})
    ev = asset_events(r)[0]
    assert ev.new_asset_count == 2
    assert ev.contributor_ids == ["a"]
    assert r.contributor_counts_to_store == {"a": 3, "b": 0}


def test_removed_assets_recorded_not_notified():
    d = D(counts={"owner": 1})
    r = diff(d, prior=state(), known_counts={"owner": 3})
    assert asset_events(r) == []
    assert r.contributor_counts_to_store == {"owner": 1}


def test_vanished_contributor_is_dropped_from_stored_counts():
    d = D(counts={"owner": 1})
    r = diff(d, prior=state(), known_counts={"owner": 1, "gone": 4})
    assert asset_events(r) == []
    assert r.contributor_counts_to_store == {"owner": 1}  # "gone" must not linger


def test_empty_counts_replace_stored_counts():
    d = D(counts={})
    r = diff(d, prior=state(), known_counts={"owner": 2})
    assert asset_events(r) == []
    assert r.contributor_counts_to_store == {}


def test_absent_counts_leave_state_untouched():
    # Immich omits contributorCounts for a non-shared album: no signal, not "empty".
    d = D(counts=None)
    r = diff(d, prior=state(), known_counts={"owner": 2})
    assert asset_events(r) == []
    assert r.contributor_counts_to_store is None


def test_new_member_on_tracked_album():
    d = D(members=[M("u1", "u1@x.com", "U1")], counts={"owner": 1})
    r = diff(d, prior=state(), known_counts={"owner": 1}, known_members=set())
    me = member_events(r)
    assert len(me) == 1
    assert me[0].new_member.user_id == "u1"
    assert r.members_to_add == ["u1"]


def test_removed_member_recorded_not_notified():
    d = D(members=[], counts={"owner": 1})
    r = diff(d, prior=state(), known_counts={"owner": 1}, known_members={"u9"})
    assert member_events(r) == []
    assert r.members_to_remove == ["u9"]


def test_unshared_album_still_records_member_removal():
    # Un-sharing drops the members and Immich stops reporting counts at the same time.
    d = D(members=[], counts=None)
    r = diff(d, prior=state(), known_counts={"owner": 1}, known_members={"u1"})
    assert r.events == []
    assert r.members_to_remove == ["u1"]
    assert r.contributor_counts_to_store is None


def test_no_changes_no_events():
    d = D(counts={"owner": 1}, members=[M("u1", "u1@x.com")])
    r = diff(d, prior=state(), known_counts={"owner": 1}, known_members={"u1"})
    assert r.events == []
