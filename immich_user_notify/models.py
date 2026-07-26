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
    role: str | None = None  # "owner" | "editor" | "viewer" (Immich AlbumUserRole)


@dataclass(frozen=True)
class AlbumSummary:
    """An entry from GET /api/albums. Only cheap change signals are used from here."""

    id: str
    name: str
    asset_count: int
    shared: bool
    updated_at: datetime
    # len(albumUsers) per the list endpoint. Since Immich 3.0 that list *includes*
    # the owner, so this is not a count of shared members -- it is only ever compared
    # against its own previous value to spot a membership change.
    member_count: int = 0


@dataclass(frozen=True)
class AlbumDetail:
    """GET /api/albums/{id}: shared members plus per-contributor asset counts.

    Immich 3.0 removed `assets[]` from album responses; `contributor_counts` maps
    userId -> number of assets that user has in the album. Immich only computes it for
    *shared* albums, so it is None for an album with no other members and no shared
    link (i.e. no signal, not "no assets").
    """

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    owner: Member
    members: list[Member]   # albumUsers minus the owner
    contributor_counts: dict[str, int] | None


@dataclass(frozen=True)
class AssetsAddedEvent:
    kind: Literal["assets_added"]
    album_id: str
    album_name: str
    new_asset_count: int          # sum of the positive per-contributor deltas
    contributor_ids: list[str]    # distinct user ids whose asset count grew


@dataclass(frozen=True)
class MemberAddedEvent:
    kind: Literal["member_added"]
    album_id: str
    album_name: str
    new_member: Member


Event = Union[AssetsAddedEvent, MemberAddedEvent]
