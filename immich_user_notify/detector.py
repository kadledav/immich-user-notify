"""Pure change detection: diff a freshly fetched album against stored state.

No I/O. Additions become events; removals are recorded only (no notification).

Immich 3.0 no longer returns an album's asset list, so new photos are detected from
`contributorCounts` instead: a per-user asset count whose value *grew* since the last
run means that user added photos. Counts are absolute state, so they are always stored
as a whole map rather than as deltas.

"Skip the albums I already have" is handled by `bootstrap_at`: an album seen for the
first time is treated as pre-existing (silent baseline) unless it was *created* after
the bootstrap, in which case it's a genuinely new album and its members are notified.
Once an album is tracked, every newly added asset/member notifies regardless of when
the asset was originally uploaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .models import AlbumDetail, AssetsAddedEvent, Event, MemberAddedEvent
from .store import AlbumState


@dataclass(frozen=True)
class DiffResult:
    events: list[Event]
    # The album's full current contributor map, to replace what we have stored.
    # None means Immich gave us no counts (album not shared) -> keep the stored map.
    contributor_counts_to_store: dict[str, int] | None
    members_to_add: list[str]
    members_to_remove: list[str]
    is_baseline: bool


def diff_album(
    *,
    detail: AlbumDetail,
    prior: AlbumState | None,
    known_member_ids: set[str],
    known_contributor_counts: Mapping[str, int],
    bootstrap_at: datetime,
) -> DiffResult:
    is_first_sight = prior is None or not prior.baseline_done

    current_member_ids = {m.user_id for m in detail.members}
    added_members = [m for m in detail.members if m.user_id not in known_member_ids]
    removed_members = [uid for uid in known_member_ids if uid not in current_member_ids]
    members_to_add = [m.user_id for m in added_members]

    counts = detail.contributor_counts

    def result(events: list[Event], *, is_baseline: bool) -> DiffResult:
        return DiffResult(
            events=events,
            # Recorded on every path, including the notify-the-new-album path: otherwise
            # the next run would report the album's whole back-catalogue as new photos.
            contributor_counts_to_store=dict(counts) if counts is not None else None,
            members_to_add=members_to_add,
            members_to_remove=removed_members,
            is_baseline=is_baseline,
        )

    if is_first_sight:
        # A genuinely new album (created after we started) announces itself to its
        # members. A pre-existing album (created before bootstrap, e.g. one of the
        # albums you already had, or an old album newly shared with you) is recorded
        # silently so you don't get a flood.
        if detail.created_at > bootstrap_at:
            events: list[Event] = [
                MemberAddedEvent(
                    kind="member_added",
                    album_id=detail.id,
                    album_name=detail.name,
                    new_member=member,
                )
                for member in detail.members
            ]
            return result(events, is_baseline=False)
        return result([], is_baseline=True)

    # Tracked album: notify every newly added asset (any upload age) and new member.
    events = []
    if counts is not None:
        contributor_ids = sorted(
            uid for uid, n in counts.items() if n > known_contributor_counts.get(uid, 0)
        )
        added = sum(
            max(0, n - known_contributor_counts.get(uid, 0)) for uid, n in counts.items()
        )
        if contributor_ids:
            events.append(
                AssetsAddedEvent(
                    kind="assets_added",
                    album_id=detail.id,
                    album_name=detail.name,
                    new_asset_count=added,
                    contributor_ids=contributor_ids,
                )
            )
    for member in added_members:
        events.append(
            MemberAddedEvent(
                kind="member_added",
                album_id=detail.id,
                album_name=detail.name,
                new_member=member,
            )
        )

    return result(events, is_baseline=False)
