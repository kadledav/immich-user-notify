"""Domain models. Plain frozen dataclasses produced by the Immich client and
consumed by the pure detector/notifier logic. Datetimes are tz-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Union


@dataclass(frozen=True)
class Member:
    """A user who can see an album: the owner, or a shared user."""

    user_id: str
    email: str | None
    name: str | None
    role: str | None = None  # "editor" | "viewer" for shared users; None for the owner


@dataclass(frozen=True)
class AlbumSummary:
    """An entry from GET /api/albums (assets not relied upon here)."""

    id: str
    name: str
    owner_id: str
    asset_count: int
    shared: bool
    updated_at: datetime
    owner: Member
    member_count: int = 0  # number of shared members (albumUsers) per the list endpoint


@dataclass(frozen=True)
class Asset:
    """An entry in an album's assets[]. created_at is upload-to-Immich time."""

    id: str
    owner_id: str
    created_at: datetime
    file_created_at: datetime | None = None
    original_file_name: str | None = None
    type: str | None = None


@dataclass(frozen=True)
class AlbumDetail:
    """GET /api/albums/{id}: the full album with assets and shared members."""

    id: str
    name: str
    owner_id: str
    updated_at: datetime
    owner: Member
    members: list[Member]   # albumUsers; does NOT include the owner
    assets: list[Asset]


@dataclass(frozen=True)
class AssetsAddedEvent:
    kind: Literal["assets_added"]
    album_id: str
    album_name: str
    new_asset_count: int          # count of *notifiable* new assets
    contributor_ids: list[str]    # distinct owner_ids among the notifiable new assets


@dataclass(frozen=True)
class MemberAddedEvent:
    kind: Literal["member_added"]
    album_id: str
    album_name: str
    new_member: Member


Event = Union[AssetsAddedEvent, MemberAddedEvent]
