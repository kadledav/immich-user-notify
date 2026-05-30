from builders import M

from immich_user_notify.models import AssetsAddedEvent, MemberAddedEvent
from immich_user_notify.notifier import (
    build_messages,
    build_recipients,
    select_recipients,
)


def _recips():
    owner = M("owner", "owner@x.com", "Owner")
    members = [M("alice", "alice@x.com", "Alice"), M("bob", "bob@x.com", "Bob")]
    return build_recipients(
        owner=owner, members=members, default_language="en", user_languages={}
    )


def test_build_recipients_owner_and_members():
    assert {r.topic for r in _recips()} == {"immich-owner", "immich-alice", "immich-bob"}


def test_build_recipients_dedup_owner_also_member():
    owner = M("owner", "owner@x.com", "Owner")
    rs = build_recipients(
        owner=owner, members=[owner], default_language="en", user_languages={}
    )
    assert len(rs) == 1


def test_build_recipients_drops_no_email():
    owner = M("owner", "owner@x.com", "Owner")
    rs = build_recipients(
        owner=owner, members=[M("x", None, "X")], default_language="en", user_languages={}
    )
    assert {r.topic for r in rs} == {"immich-owner"}


def test_recipient_language_resolution():
    owner = M("owner", "owner@x.com", "Owner")
    rs = build_recipients(
        owner=owner,
        members=[M("a", "a@x.com", "A")],
        default_language="en",
        user_languages={"a@x.com": "cs"},
    )
    by_topic = {r.topic: r.lang for r in rs}
    assert by_topic["immich-owner"] == "en"
    assert by_topic["immich-a"] == "cs"


def test_select_single_contributor_excluded():
    ev = AssetsAddedEvent("assets_added", "album-1", "Trip", 1, ["alice"])
    assert {r.topic for r in select_recipients(ev, _recips())} == {"immich-owner", "immich-bob"}


def test_select_multi_contributor_all():
    ev = AssetsAddedEvent("assets_added", "album-1", "Trip", 2, ["alice", "bob"])
    assert {r.topic for r in select_recipients(ev, _recips())} == {
        "immich-owner",
        "immich-alice",
        "immich-bob",
    }


def test_select_member_added_only_new_member():
    ev = MemberAddedEvent("member_added", "album-1", "Trip", M("alice", "alice@x.com", "Alice"))
    assert {r.topic for r in select_recipients(ev, _recips())} == {"immich-alice"}


def test_messages_single_contributor_en(translator):
    ev = AssetsAddedEvent("assets_added", "album-1", "Trip", 1, ["alice"])
    msgs = build_messages(
        ev,
        _recips(),
        translator=translator,
        public_url="https://p.example.com",
        icon_url=None,
        contributor_names={"alice": "Alice"},
    )
    assert {m.topic for m in msgs} == {"immich-owner", "immich-bob"}
    m = msgs[0]
    assert m.title == "New photos"
    assert m.body == 'Alice added new photos to "Trip".'
    assert m.tags == ["camera_with_flash"]
    assert m.priority == 4
    assert m.click == "https://p.example.com/albums/album-1"


def test_messages_multiple_contributors(translator):
    ev = AssetsAddedEvent("assets_added", "album-1", "Trip", 3, ["alice", "bob"])
    msgs = build_messages(
        ev, _recips(), translator=translator, public_url="https://p", icon_url=None,
        contributor_names={},
    )
    assert {m.topic for m in msgs} == {"immich-owner", "immich-alice", "immich-bob"}
    assert all(m.body == 'More photos were added to "Trip".' for m in msgs)


def test_messages_member_added(translator):
    ev = MemberAddedEvent("member_added", "album-1", "Trip", M("alice", "alice@x.com", "Alice"))
    msgs = build_messages(
        ev, _recips(), translator=translator, public_url="https://p", icon_url=None,
        contributor_names={},
    )
    assert len(msgs) == 1
    assert msgs[0].topic == "immich-alice"
    assert msgs[0].title == "Album shared with you"
    assert msgs[0].body == 'You have been added to "Trip".'
    assert msgs[0].tags == ["handshake"]


def test_messages_per_recipient_language(translator):
    owner = M("owner", "owner@x.com", "Owner")
    rs = build_recipients(
        owner=owner,
        members=[M("alice", "alice@x.com", "Alice")],
        default_language="en",
        user_languages={"owner@x.com": "cs"},
    )
    ev = AssetsAddedEvent("assets_added", "album-1", "Trip", 1, ["alice"])
    msgs = build_messages(
        ev, rs, translator=translator, public_url="https://p", icon_url=None,
        contributor_names={"alice": "Alice"},
    )
    # alice is the sole contributor -> excluded; only owner (cs) remains
    assert len(msgs) == 1
    assert msgs[0].topic == "immich-owner"
    assert msgs[0].title == "Nové fotky"
    assert msgs[0].body == "Alice přidal(a) nové fotky do alba „Trip“."


def test_contributor_name_fallback_someone(translator):
    ev = AssetsAddedEvent("assets_added", "album-1", "Trip", 1, ["ghost"])
    msgs = build_messages(
        ev, _recips(), translator=translator, public_url="https://p", icon_url=None,
        contributor_names={},
    )
    # ghost is not a recipient -> exclusion is a no-op; everyone notified
    assert {m.topic for m in msgs} == {"immich-owner", "immich-alice", "immich-bob"}
    assert all(m.body == 'Someone added new photos to "Trip".' for m in msgs)
