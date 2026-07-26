import pytest
from builders import NOW, album_detail, album_summary, album_users, user

from immich_user_notify.immich_client import ImmichError


def test_list_albums_sends_api_key(immich, mocked_responses, immich_base):
    owner = user("owner", "o@x.com", "O")
    mocked_responses.get(
        f"{immich_base}/api/albums",
        json=[album_summary(owner=owner, asset_count=2, updated_at=NOW)],
    )
    albums = immich.list_albums()
    assert len(albums) == 1
    assert albums[0].asset_count == 2
    assert albums[0].member_count == 1  # albumUsers includes the owner since Immich 3.0
    assert mocked_responses.calls[0].request.headers["x-api-key"] == "test-token"


def test_list_albums_sends_no_query_params(immich, mocked_responses, immich_base):
    owner = user("owner", "o@x.com", "O")
    mocked_responses.get(
        f"{immich_base}/api/albums",
        json=[album_summary(owner=owner, asset_count=0, updated_at=NOW)],
    )
    immich.list_albums()
    assert mocked_responses.calls[0].request.url == f"{immich_base}/api/albums"


def test_get_album_parses_detail(immich, mocked_responses, immich_base):
    owner = user("owner", "o@x.com", "O")
    alice = user("a", "a@x.com", "A")
    mocked_responses.get(
        f"{immich_base}/api/albums/album-1",
        json=album_detail(owner=owner, members=[alice], counts={"owner": 2, "a": 1}),
    )
    d = immich.get_album("album-1")
    assert d.name == "Trip"
    # The owner is resolved by role, not by position (the builder puts them last).
    assert d.owner.user_id == "owner"
    assert d.owner.email == "o@x.com"
    assert [m.user_id for m in d.members] == ["a"]  # owner is NOT a member
    assert d.members[0].role == "editor"
    assert d.contributor_counts == {"owner": 2, "a": 1}


def test_get_album_owner_first_also_works(immich, mocked_responses, immich_base):
    owner = user("owner", "o@x.com", "O")
    alice = user("a", "a@x.com", "A")
    dto = album_detail(owner=owner, members=[alice], counts={"owner": 1})
    dto["albumUsers"] = list(reversed(dto["albumUsers"]))  # owner first this time
    mocked_responses.get(f"{immich_base}/api/albums/album-1", json=dto)
    d = immich.get_album("album-1")
    assert d.owner.user_id == "owner"
    assert [m.user_id for m in d.members] == ["a"]


def test_get_album_owner_listed_twice_is_not_a_member(immich, mocked_responses, immich_base):
    owner = user("owner", "o@x.com", "O")
    dto = album_detail(owner=owner, members=[], counts={"owner": 1})
    dto["albumUsers"] = album_users(owner, []) + [{"user": owner, "role": "editor"}]
    mocked_responses.get(f"{immich_base}/api/albums/album-1", json=dto)
    d = immich.get_album("album-1")
    assert d.owner.user_id == "owner"
    assert d.members == []


def test_get_album_without_owner_role_raises(immich, mocked_responses, immich_base):
    alice = user("a", "a@x.com", "A")
    dto = album_detail(owner=user("owner", "o@x.com", "O"), members=[alice])
    dto["albumUsers"] = [{"user": alice, "role": "editor"}]
    mocked_responses.get(f"{immich_base}/api/albums/album-1", json=dto)
    with pytest.raises(ImmichError):
        immich.get_album("album-1")


def test_contributor_counts_absent_vs_empty(immich, mocked_responses, immich_base):
    owner = user("owner", "o@x.com", "O")
    # Absent (non-shared album): no signal at all.
    mocked_responses.get(f"{immich_base}/api/albums/album-1", json=album_detail(owner=owner))
    assert immich.get_album("album-1").contributor_counts is None
    # Present but empty (shared album with no assets): a real, empty state.
    mocked_responses.reset()
    mocked_responses.get(
        f"{immich_base}/api/albums/album-1", json=album_detail(owner=owner, counts={})
    )
    assert immich.get_album("album-1").contributor_counts == {}


def test_list_users(immich, mocked_responses, immich_base):
    mocked_responses.get(
        f"{immich_base}/api/users",
        json=[user("u1", "u1@x.com", "U1"), user("u2", "u2@x.com", "U2")],
    )
    users = immich.list_users()
    assert {u.email for u in users} == {"u1@x.com", "u2@x.com"}


def test_get_me_parses_admin_dto(immich, mocked_responses, immich_base):
    # /users/me returns UserAdminResponseDto since Immich 3.0 (extra fields, same core).
    me = user("me", "me@x.com", "Me")
    me.update({"isAdmin": True, "storageLabel": None, "quotaSizeInBytes": None})
    mocked_responses.get(f"{immich_base}/api/users/me", json=me)
    assert immich.get_me().email == "me@x.com"


def test_get_server_version(immich, mocked_responses, immich_base):
    mocked_responses.get(
        f"{immich_base}/api/server/version", json={"major": 3, "minor": 0, "patch": 1}
    )
    assert immich.get_server_version() == (3, 0, 1)


def test_401_raises(immich, mocked_responses, immich_base):
    mocked_responses.get(f"{immich_base}/api/albums", status=401, json={"message": "unauthorized"})
    with pytest.raises(ImmichError):
        immich.list_albums()


def test_500_raises(immich, mocked_responses, immich_base):
    mocked_responses.get(f"{immich_base}/api/albums", status=500, json={})
    with pytest.raises(ImmichError):
        immich.list_albums()


def test_empty_albums(immich, mocked_responses, immich_base):
    mocked_responses.get(f"{immich_base}/api/albums", json=[])
    assert immich.list_albums() == []
