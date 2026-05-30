import pytest

from immich_user_notify.config import topic_for_email


@pytest.mark.parametrize(
    "email,expected",
    [
        ("david.k@gmail.com", "immich-david-k"),
        ("jane_doe@x.com", "immich-jane_doe"),
        ("John.Smith@x.com", "immich-john-smith"),
        ("bob+immich@x.com", "immich-bob-immich"),
        ("a.b.c@x.com", "immich-a-b-c"),
        ("x" * 80 + "@x.com", "immich-" + "x" * 57),  # prefix + truncate to 64
        ("@x.com", ""),
        ("not-an-email", "immich-not-an-email"),
    ],
    ids=["dot", "underscore", "case", "plus", "multidot", "trunc64", "empty", "noat"],
)
def test_topic_for_email(email, expected):
    assert topic_for_email(email) == expected


def test_topic_truncation_boundary():
    assert len(topic_for_email("a" * 65 + "@x.com")) == 64


def test_topic_unicode_replaced():
    # d á v í . k  -> á,í,. become "-", then prefixed
    assert topic_for_email("dáví.k@x.com") == "immich-d-v--k"
