"""Test data builders: Immich-shaped JSON dicts (for client/app tests) and domain
model objects (for pure detector/notifier unit tests). Shapes follow Immich 2.7.5.
"""

from __future__ import annotations

from datetime import datetime, timezone

from immich_user_notify.models import AlbumDetail, Asset, Member
from immich_user_notify.store import AlbumState

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


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


def asset(id: str, owner_id: str, created_at: datetime, type: str = "IMAGE") -> dict:
    return {
        "id": id,
        "ownerId": owner_id,
        "createdAt": iso(created_at),
        "fileCreatedAt": iso(created_at),
        "type": type,
        "originalFileName": f"{id}.jpg",
    }


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
    return {
        "id": id,
        "albumName": name,
        "description": "",
        "ownerId": owner["id"],
        "owner": owner,
        "albumUsers": [{"user": m, "role": "editor"} for m in members],
        "assetCount": asset_count,
        "shared": shared,
        "createdAt": iso(updated_at),
        "updatedAt": iso(updated_at),
    }


def album_detail(
    *,
    id: str = "album-1",
    name: str = "Trip",
    owner: dict,
    members: list[dict] = (),
    assets: list[dict] = (),
    updated_at: datetime = NOW,
    created_at: datetime | None = None,
) -> dict:
    return {
        "id": id,
        "albumName": name,
        "description": "",
        "ownerId": owner["id"],
        "owner": owner,
        "albumUsers": [{"user": m, "role": "editor"} for m in members],
        "assets": list(assets),
        "assetCount": len(assets),
        "shared": True,
        "createdAt": iso(created_at or updated_at),
        "updatedAt": iso(updated_at),
    }


# --- domain model builders --------------------------------------------------


def M(user_id: str, email: str | None = None, name: str | None = None, role: str | None = None) -> Member:
    return Member(user_id=user_id, email=email, name=name, role=role)


def A(id: str, owner_id: str, created_at: datetime = NOW) -> Asset:
    return Asset(id=id, owner_id=owner_id, created_at=created_at)


def D(
    *,
    id: str = "album-1",
    name: str = "Trip",
    owner: Member | None = None,
    members: list[Member] = (),
    assets: list[Asset] = (),
    updated_at: datetime = NOW,
    created_at: datetime | None = None,
) -> AlbumDetail:
    owner = owner or M("owner", "owner@example.com", "Owner")
    return AlbumDetail(
        id=id,
        name=name,
        owner_id=owner.user_id,
        created_at=created_at or updated_at,
        updated_at=updated_at,
        owner=owner,
        members=list(members),
        assets=list(assets),
    )


def state(
    *,
    album_id: str = "album-1",
    name: str = "Trip",
    asset_count: int = 0,
    updated_at: datetime = NOW,
    baseline_done: bool = True,
) -> AlbumState:
    return AlbumState(
        album_id=album_id,
        name=name,
        asset_count=asset_count,
        updated_at=updated_at,
        baseline_done=baseline_done,
    )
