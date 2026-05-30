import json
from pathlib import Path

import pytest

from immich_user_notify.config import parse_user_languages


def test_en_strings(translator):
    assert translator.t("en", "title.new_photos") == "New photos"
    assert (
        translator.t("en", "body.assets_added_single", name="Alice", album="Trip")
        == 'Alice added new photos to "Trip".'
    )
    assert (
        translator.t("en", "body.assets_added_multiple", album="Trip")
        == 'More photos were added to "Trip".'
    )
    assert (
        translator.t("en", "body.member_added", album="Trip")
        == 'You have been added to "Trip".'
    )
    assert translator.t("en", "name.someone") == "Someone"


def test_cs_strings(translator):
    assert translator.t("cs", "title.new_photos") == "Nové fotky"
    assert translator.t("cs", "title.album_shared") == "Sdílené album"
    assert (
        translator.t("cs", "body.assets_added_single", name="Alice", album="Trip")
        == "Alice přidal(a) nové fotky do alba „Trip“."
    )


def test_unknown_lang_falls_back_to_default(translator):
    assert translator.t("de", "title.new_photos") == "New photos"


def test_unknown_key_returns_key(translator):
    assert translator.t("en", "no.such.key") == "no.such.key"


def test_locale_key_parity(config):
    locales = Path(config.locales_dir)
    en = json.loads((locales / "en.json").read_text(encoding="utf-8"))
    cs = json.loads((locales / "cs.json").read_text(encoding="utf-8"))
    assert set(en) == set(cs)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a@x.com=cs,b@y.com=en", {"a@x.com": "cs", "b@y.com": "en"}),
        ("", {}),
        ("   ", {}),
        ("A@X.com=CS", {"a@x.com": "cs"}),
        ("bad-entry,c@z.com=cs", {"c@z.com": "cs"}),
        ("d@z.com=", {}),
    ],
)
def test_parse_user_languages(raw, expected):
    assert parse_user_languages(raw) == expected
