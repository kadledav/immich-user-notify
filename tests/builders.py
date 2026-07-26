"""Test data builders: Immich-shaped JSON dicts (for client/app tests) and domain
model objects (for pure detector/notifier unit tests). Shapes follow Immich 3.0.0.
"""

from __future__ import annotations

from datetime import datetime, timezone

from immich_user_notify.models import AlbumDetail, Member
from immich_user_notify.store import AlbumState

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)

#: Sentinel for "Immich omitted contributorCounts entirely" (a non-shared album), as
#: opposed to an empty list ("shared album with no assets"). The two must not be conflated.
ABSENT = object()


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# --- Immich JSON payload builders -------------------------------------------


def user(id: str, email: str | None = None, name: str | None = None) -> dict:
    return {
        "id": id,
        "email": email,
        "name": name,
        "profileImagePath": "",
        "avatarColor": "primary",
        "profileChangedAt": iso(NOW),
    }


def album_users(owner: dict, members: list[dict] = ()) -> list[dict]:
    """`albumUsers` as Immich 3.0 returns it: the owner is an entry with role "owner".

    The owner is placed *last* on purpose. Immich documents it as first but actually
    orders by role name, so any code that trusts the position must fail here.
    """
    return [{"user": m, "role": "editor"} for m in members] + [
        {"user": owner, "role": "owner"}
    ]


def contributor_counts(counts: dict[str, int]) -> list[dict]:
    """As Immich returns it: ordered by assetCount descending."""
    return [
        {"userId": uid, "assetCount": n}
        for uid, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def album_summary(
    *,
    id: str = "album-1",
    name: str = "Trip",
    owner: dict,
    asset_count: int,
    shared: bool = True,
    updated_at: datetime,
    members: list[dict] = (),
) -> dict:
    # NB: the list endpoint never returns contributorCounts or assets.
    return {
        "id": id,
        "albumName": name,
        "description": "",
        "albumThumbnailAssetId": None,
        "albumUsers": album_users(owner, list(members)),
        "assetCount": asset_count,
        "shared": shared,
        "hasSharedLink": False,
        "isActivityEnabled": True,
        "createdAt": iso(updated_at),
        "updatedAt": iso(updated_at),
    }


def album_detail(
    *,
    id: str = "album-1",
    name: str = "Trip",
    owner: dict,
    members: list[dict] = (),
    counts: dict[str, int] | object = ABSENT,
    asset_count: int | None = None,
    updated_at: datetime = NOW,
    created_at: datetime | None = None,
) -> dict:
    dto = {
        "id": id,
        "albumName": name,
        "description": "",
        "albumThumbnailAssetId": None,
        "albumUsers": album_users(owner, list(members)),
        "assetCount": asset_count if asset_count is not None else 0,
        "shared": True,
        "hasSharedLink": False,
        "isActivityEnabled": True,
        "createdAt": iso(created_at or updated_at),
        "updatedAt": iso(updated_at),
    }
    if counts is not ABSENT:
        dto["contributorCounts"] = contributor_counts(counts)
        if asset_count is None:
            dto["assetCount"] = sum(counts.values())
    return dto


# --- domain model builders --------------------------------------------------


def M(user_id: str, email: str | None = None, name: str | None = None, role: str | None = None) -> Member:
    return Member(user_id=user_id, email=email, name=name, role=role)


def D(
    *,
    id: str = "album-1",
    name: str = "Trip",
    owner: Member | None = None,
    members: list[Member] = (),
    counts: dict[str, int] | None = None,
    updated_at: datetime = NOW,
    created_at: datetime | None = None,
) -> AlbumDetail:
    owner = owner or M("owner", "owner@example.com", "Owner", role="owner")
    return AlbumDetail(
        id=id,
        name=name,
        created_at=created_at or updated_at,
        updated_at=updated_at,
        owner=owner,
        members=list(members),
        contributor_counts=counts,
    )


def state(
    *,
    album_id: str = "album-1",
    name: str = "Trip",
    asset_count: int = 0,
    member_count: int = 0,
    updated_at: datetime = NOW,
    baseline_done: bool = True,
) -> AlbumState:
    return AlbumState(
        album_id=album_id,
        name=name,
        asset_count=asset_count,
        member_count=member_count,
        updated_at=updated_at,
        baseline_done=baseline_done,
    )
