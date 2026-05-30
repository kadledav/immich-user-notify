"""Pure change detection: diff a freshly fetched album against stored state.

No I/O. The clock (`now`) is passed in so the recency guard is deterministic in tests.
Additions are turned into events; removals are recorded only (no notification).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import AlbumDetail, AssetsAddedEvent, Event, MemberAddedEvent
from .store import AlbumState


@dataclass(frozen=True)
class DiffResult:
    events: list[Event]
    assets_to_add: list[str]        # ALL new asset ids (incl. recency-suppressed)
    assets_to_remove: list[str]
    members_to_add: list[str]
    members_to_remove: list[str]
    is_baseline: bool


def diff_album(
    *,
    detail: AlbumDetail,
    prior: AlbumState | None,
    known_asset_ids: set[str],
    known_member_ids: set[str],
    now: datetime,
    recency_window_s: int,
) -> DiffResult:
    is_baseline = prior is None or not prior.baseline_done

    current_asset_ids = {a.id for a in detail.assets}
    current_member_ids = {m.user_id for m in detail.members}

    added_assets = [a for a in detail.assets if a.id not in known_asset_ids]
    removed_assets = [aid for aid in known_asset_ids if aid not in current_asset_ids]
    added_members = [m for m in detail.members if m.user_id not in known_member_ids]
    removed_members = [uid for uid in known_member_ids if uid not in current_member_ids]

    assets_to_add = [a.id for a in added_assets]
    members_to_add = [m.user_id for m in added_members]

    if is_baseline:
        # Record everything, emit nothing: never dump full history on first sight.
        return DiffResult(
            events=[],
            assets_to_add=assets_to_add,
            assets_to_remove=removed_assets,
            members_to_add=members_to_add,
            members_to_remove=removed_members,
            is_baseline=True,
        )

    events: list[Event] = []

    def is_recent(asset) -> bool:
        delta = (now - asset.created_at).total_seconds()
        # negative delta = clock skew / future timestamp -> treat as recent (notify)
        return delta < 0 or delta <= recency_window_s

    notifiable = [a for a in added_assets if is_recent(a)]
    if notifiable:
        contributor_ids = sorted({a.owner_id for a in notifiable})
        events.append(
            AssetsAddedEvent(
                kind="assets_added",
                album_id=detail.id,
                album_name=detail.name,
                new_asset_count=len(notifiable),
                contributor_ids=contributor_ids,
            )
        )

    # Membership has no per-album timestamp -> no recency guard.
    for member in added_members:
        events.append(
            MemberAddedEvent(
                kind="member_added",
                album_id=detail.id,
                album_name=detail.name,
                new_member=member,
            )
        )

    return DiffResult(
        events=events,
        assets_to_add=assets_to_add,
        assets_to_remove=removed_assets,
        members_to_add=members_to_add,
        members_to_remove=removed_members,
        is_baseline=False,
    )
