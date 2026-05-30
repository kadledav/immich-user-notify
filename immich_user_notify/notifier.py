"""Pure recipient/message building. No I/O.

Recipients = album owner + shared members, mapped email->topic, each with a
resolved language. The contributor-filtering rule and the member-added rule decide
who actually receives a given event; messages are rendered per recipient in their
own language via the Translator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .config import topic_for_email
from .i18n import Translator
from .models import AssetsAddedEvent, Event, Member, MemberAddedEvent

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Recipient:
    user_id: str
    email: str
    topic: str
    lang: str


@dataclass(frozen=True)
class OutgoingMessage:
    topic: str
    title: str
    body: str
    tags: list[str]
    priority: int
    click: str | None
    icon: str | None


def build_recipients(
    *,
    owner: Member,
    members: Sequence[Member],
    default_language: str,
    user_languages: Mapping[str, str],
) -> list[Recipient]:
    """Owner + members -> recipients (deduped by topic). Drops anyone without an
    email or a valid topic; warns on topic collisions between distinct users.
    """
    recipients: list[Recipient] = []
    topic_owner: dict[str, str] = {}  # topic -> user_id (first seen)

    for member in (owner, *members):
        if not member.email:
            log.warning("dropping recipient %s: no email", member.user_id)
            continue
        topic = topic_for_email(member.email)
        if not topic:
            log.warning("dropping recipient %s <%s>: empty topic", member.user_id, member.email)
            continue
        if topic in topic_owner:
            if topic_owner[topic] != member.user_id:
                log.warning(
                    "topic collision: users %s and %s both map to topic %r; keeping first",
                    topic_owner[topic],
                    member.user_id,
                    topic,
                )
            continue
        topic_owner[topic] = member.user_id
        lang = user_languages.get(member.email.lower(), default_language)
        recipients.append(
            Recipient(user_id=member.user_id, email=member.email, topic=topic, lang=lang)
        )

    return recipients


def select_recipients(
    event: Event,
    all_recipients: Sequence[Recipient],
    *,
    suppress_user_ids: Iterable[str] = (),
) -> list[Recipient]:
    """Apply the per-event recipient rule.

    `suppress_user_ids` are people who must not receive an *asset* notification this
    cycle — used to keep a just-invited member from also getting "N photos added" on
    top of their "you have been added" message.
    """
    if isinstance(event, AssetsAddedEvent):
        excluded = set(suppress_user_ids)
        distinct = set(event.contributor_ids)
        if len(distinct) == 1:  # sole contributor isn't told about their own upload
            excluded |= distinct
        return [r for r in all_recipients if r.user_id not in excluded]
    if isinstance(event, MemberAddedEvent):
        # Only the newly added member is notified.
        return [r for r in all_recipients if r.user_id == event.new_member.user_id]
    return []


def build_messages(
    event: Event,
    all_recipients: Sequence[Recipient],
    *,
    translator: Translator,
    public_url: str,
    icon_url: str | None,
    contributor_names: Mapping[str, str],
    suppress_user_ids: Iterable[str] = (),
) -> list[OutgoingMessage]:
    """Build one message per target recipient, localized to that recipient."""
    targets = select_recipients(event, all_recipients, suppress_user_ids=suppress_user_ids)
    if not targets:
        return []

    click = f"{public_url}/albums/{event.album_id}"
    messages: list[OutgoingMessage] = []

    for r in targets:
        if isinstance(event, AssetsAddedEvent):
            title = translator.t(r.lang, "title.new_photos")
            if len(set(event.contributor_ids)) == 1:
                cid = event.contributor_ids[0]
                name = contributor_names.get(cid) or translator.t(r.lang, "name.someone")
                body = translator.t(
                    r.lang, "body.assets_added_single", name=name, album=event.album_name
                )
            else:
                body = translator.t(
                    r.lang, "body.assets_added_multiple", album=event.album_name
                )
            tags = ["camera_with_flash"]
            priority = 4
        elif isinstance(event, MemberAddedEvent):
            title = translator.t(r.lang, "title.album_shared")
            body = translator.t(r.lang, "body.member_added", album=event.album_name)
            tags = ["handshake"]
            priority = 4
        else:  # pragma: no cover - exhaustive
            continue

        messages.append(
            OutgoingMessage(
                topic=r.topic,
                title=title,
                body=body,
                tags=tags,
                priority=priority,
                click=click,
                icon=icon_url,
            )
        )

    return messages
