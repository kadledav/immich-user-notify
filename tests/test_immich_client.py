import pytest
from builders import NOW, album_detail, album_summary, asset, user

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
    assert albums[0].owner.email == "o@x.com"
    assert mocked_responses.calls[0].request.headers["x-api-key"] == "test-token"


def test_get_album_parses_detail(immich, mocked_responses, immich_base):
    owner = user("owner", "o@x.com", "O")
    alice = user("a", "a@x.com", "A")
    mocked_responses.get(
        f"{immich_base}/api/albums/album-1",
        json=album_detail(owner=owner, members=[alice], assets=[asset("x", "owner", NOW)]),
    )
    d = immich.get_album("album-1")
    assert d.name == "Trip"
    assert d.owner.email == "o@x.com"
    assert [m.user_id for m in d.members] == ["a"]
    assert d.members[0].role == "editor"
    assert d.assets[0].id == "x"
    assert d.assets[0].owner_id == "owner"


def test_list_users(immich, mocked_responses, immich_base):
    mocked_responses.get(
        f"{immich_base}/api/users",
        json=[user("u1", "u1@x.com", "U1"), user("u2", "u2@x.com", "U2")],
    )
    users = immich.list_users()
    assert {u.email for u in users} == {"u1@x.com", "u2@x.com"}


def test_get_me(immich, mocked_responses, immich_base):
    mocked_responses.get(f"{immich_base}/api/users/me", json=user("me", "me@x.com", "Me"))
    assert immich.get_me().email == "me@x.com"


def test_401_raises(immich, mocked_responses, immich_base):
    mocked_responses.get(f"{immich_base}/api/albums", status=401, json={"error": "unauthorized"})
    with pytest.raises(ImmichError):
        immich.list_albums()


def test_500_raises(immich, mocked_responses, immich_base):
    mocked_responses.get(f"{immich_base}/api/albums", status=500, json={})
    with pytest.raises(ImmichError):
        immich.list_albums()


def test_empty_albums(immich, mocked_responses, immich_base):
    mocked_responses.get(f"{immich_base}/api/albums", json=[])
    assert immich.list_albums() == []
