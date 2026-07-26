"""Orchestration: one polling cycle (run_once) and the forever loop (run_forever).

Crash-safety: per album we SEND best-effort, then PERSIST the full state delta
unconditionally in one transaction (see plan). One bad album never aborts the run.
"""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

from .config import Config, topic_for_email
from .detector import diff_album
from .i18n import Translator
from .immich_client import ImmichClient, ImmichError
from .models import AssetsAddedEvent, Member, MemberAddedEvent
from .notifier import build_messages, build_recipients
from .ntfy_client import NtfyClient, NtfyError
from .store import Store
from .timeutil import utcnow

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    albums_seen: int = 0
    albums_fetched: int = 0
    events: int = 0
    messages_sent: int = 0
    messages_failed: int = 0
    errors: int = 0

    def __str__(self) -> str:
        return (
            f"albums_seen={self.albums_seen} fetched={self.albums_fetched} "
            f"events={self.events} sent={self.messages_sent} "
            f"failed={self.messages_failed} errors={self.errors}"
        )


def _display_name(member: Member) -> str:
    if member.name and member.name.strip():
        return member.name.strip()
    if member.email:
        return member.email.split("@", 1)[0]
    return ""  # notifier falls back to localized "Someone"


class App:
    def __init__(
        self,
        config: Config,
        immich: ImmichClient,
        ntfy: NtfyClient,
        store: Store,
        translator: Translator,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._config = config
        self._immich = immich
        self._ntfy = ntfy
        self._store = store
        self._translator = translator
        self._clock = clock

    # --- one cycle --------------------------------------------------------

    def run_once(self) -> RunStats:
        stats = RunStats()
        now = self._clock()

        try:
            albums = self._immich.list_albums()
        except ImmichError as exc:
            log.error("listing albums failed; skipping run: %s", exc)
            stats.errors += 1
            return stats

        # Count only successful runs, so a transient list failure doesn't consume a
        # force-full-scan slot.
        run_count = self._store.increment_run_count()
        force_full = (
            self._config.force_full_scan_every > 0
            and run_count % self._config.force_full_scan_every == 0
        )
        # One-time boundary: albums that existed at bootstrap are "already mine" and
        # baselined silently; albums created after it are new and notify their members.
        bootstrap_at = self._store.get_or_set_bootstrap_at(now)
        stats.albums_seen = len(albums)

        for summary in albums:
            prior = self._store.get_album_state(summary.id)
            # Only shared albums are notify-worthy; keep already-tracked albums so a
            # later un-share still updates state correctly.
            if not summary.shared and prior is None:
                continue
            changed = (
                prior is None
                or prior.asset_count != summary.asset_count
                or prior.member_count != summary.member_count
                or prior.updated_at != summary.updated_at
            )
            if not changed and not force_full:
                continue

            try:
                detail = self._immich.get_album(summary.id)
            except ImmichError as exc:
                log.error("fetching album %s (%s) failed: %s", summary.id, summary.name, exc)
                stats.errors += 1
                continue
            stats.albums_fetched += 1

            try:
                self._process_album(summary, detail, prior, bootstrap_at, stats)
            except Exception:  # never let one album kill the run
                log.exception("error processing album %s (%s)", detail.id, detail.name)
                stats.errors += 1

        return stats

    def _process_album(self, summary, detail, prior, bootstrap_at, stats: RunStats) -> None:
        known_counts = self._store.get_contributor_counts(detail.id)
        known_members = self._store.get_known_member_ids(detail.id)

        diff = diff_album(
            detail=detail,
            prior=prior,
            known_member_ids=known_members,
            known_contributor_counts=known_counts,
            bootstrap_at=bootstrap_at,
        )

        if diff.events:
            # Build + send is best-effort: any failure here must NOT skip the persist
            # below, or we'd re-detect and re-notify the same change forever.
            try:
                self._send(detail, diff.events, stats)
            except Exception:
                log.exception(
                    "error building/sending notifications for album %s (%s)",
                    detail.id,
                    detail.name,
                )
                stats.errors += 1

        # Persist the whole delta atomically and unconditionally. upsert_album_meta
        # first so the album row exists before the contributor/member FKs reference it.
        # Gate fields (asset_count/member_count/updated_at) are stored from the LIST
        # summary so the next run's change check compares like-for-like: if a photo lands
        # between the list call and the detail call, the gate fires again next run and the
        # contributor delta is then zero, so nobody is notified twice.
        with self._store.transaction():
            self._store.upsert_album_meta(
                detail.id,
                name=detail.name,
                asset_count=summary.asset_count,
                member_count=summary.member_count,
                updated_at=summary.updated_at,
                baseline_done=True,
            )
            if diff.contributor_counts_to_store is not None:
                self._store.replace_contributor_counts(
                    detail.id, diff.contributor_counts_to_store
                )
            if diff.members_to_add:
                self._store.add_known_members(detail.id, diff.members_to_add)
            if diff.members_to_remove:
                self._store.remove_known_members(detail.id, diff.members_to_remove)

    def _send(self, detail, events, stats: RunStats) -> None:
        recipients = build_recipients(
            owner=detail.owner,
            members=detail.members,
            default_language=self._config.default_language,
            user_languages=self._config.user_languages,
        )
        contributor_names = self._contributor_names(detail, events)
        # A member invited this cycle gets only the "you have been added" message,
        # not also the album's new-photo notification.
        new_member_ids = {
            e.new_member.user_id for e in events if isinstance(e, MemberAddedEvent)
        }

        messages = []
        for event in events:
            messages += build_messages(
                event,
                recipients,
                translator=self._translator,
                public_url=self._config.immich_public_url,
                icon_url=self._config.icon_url,
                contributor_names=contributor_names,
                suppress_user_ids=new_member_ids,
            )
        stats.events += len(events)

        for msg in messages:
            try:
                self._ntfy.publish(
                    msg.topic,
                    message=msg.body,
                    title=msg.title,
                    priority=msg.priority,
                    tags=msg.tags,
                    click=msg.click,
                    icon=msg.icon,
                )
                stats.messages_sent += 1
            except NtfyError as exc:
                log.error("publishing to topic %s failed: %s", msg.topic, exc)
                stats.messages_failed += 1

    def _contributor_names(self, detail, events) -> dict[str, str]:
        names = {m.user_id: _display_name(m) for m in (detail.owner, *detail.members)}
        # Resolve any single-contributor whose name we don't have yet (best effort).
        # Immich counts assets by owner, including people who have since been removed
        # from the album, so this lookup matters more than the member list suggests.
        for event in events:
            if isinstance(event, AssetsAddedEvent) and len(set(event.contributor_ids)) == 1:
                cid = event.contributor_ids[0]
                if not names.get(cid):
                    try:
                        names[cid] = _display_name(self._immich.get_user(cid))
                    except ImmichError:
                        pass  # notifier falls back to localized "Someone"
        return names

    # --- forever loop -----------------------------------------------------

    def run_forever(self) -> None:
        self._log_startup()

        stopping = {"flag": False}

        def handle(signum, _frame):
            log.info("received signal %s; will stop after the current run", signum)
            stopping["flag"] = True

        signal.signal(signal.SIGTERM, handle)
        signal.signal(signal.SIGINT, handle)

        interval = self._config.interval_seconds
        while not stopping["flag"]:
            try:
                stats = self.run_once()
                log.info("run complete: %s", stats)
            except Exception:
                log.exception("unexpected error during run")
            # Sleep in 1s steps so a signal stops us promptly.
            slept = 0
            while slept < interval and not stopping["flag"]:
                time.sleep(1)
                slept += 1

        log.info("shutting down")

    # --- startup ----------------------------------------------------------

    def _log_startup(self) -> None:
        try:
            major, minor, patch = self._immich.get_server_version()
            log.info("Immich server version %d.%d.%d", major, minor, patch)
            if major != 3:
                log.warning(
                    "this build targets the Immich 3.x API; server reports %d.%d.%d --"
                    " album parsing will most likely fail",
                    major,
                    minor,
                    patch,
                )
        except ImmichError as exc:
            log.warning("could not fetch the Immich server version: %s", exc)

        try:
            me = self._immich.get_me()
            log.info("authenticated to Immich as %s <%s> (id=%s)", me.name, me.email, me.user_id)
        except ImmichError as exc:
            log.warning("could not fetch /users/me: %s", exc)

        try:
            users = self._immich.list_users()
        except ImmichError as exc:
            log.warning("could not list users for the topic mapping: %s", exc)
            return
        self._log_topic_mapping(users)

    def _log_topic_mapping(self, users: Iterable[Member]) -> None:
        users = list(users)
        log.info("user -> ntfy topic mapping (%d users):", len(users))
        topic_to_emails: dict[str, list[str]] = {}
        for u in sorted(users, key=lambda x: (x.email or "").lower()):
            if not u.email:
                log.info("  %s <no email> -> (skipped)", u.name or u.user_id)
                continue
            topic = topic_for_email(u.email)
            lang = self._config.user_languages.get(u.email.lower(), self._config.default_language)
            if not topic:
                log.warning(
                    "  %s <%s> -> (no valid topic; will not be notified)",
                    u.name or "?",
                    u.email,
                )
                continue
            log.info("  %s <%s> -> topic '%s' (lang=%s)", u.name or "?", u.email, topic, lang)
            topic_to_emails.setdefault(topic, []).append(u.email)
        for topic, emails in topic_to_emails.items():
            if len(emails) > 1:
                log.warning("  COLLISION: topic '%s' shared by: %s", topic, ", ".join(emails))
