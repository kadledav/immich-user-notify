"""Tiny JSON-file localization. One flat {key: template} file per language under
locales/. Lookup order: requested lang -> default lang -> the raw key. Templates
are Python str.format strings.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class Translator:
    def __init__(self, locales_dir: str, default_lang: str = "en") -> None:
        self._default_lang = (default_lang or "en").lower()
        self._locales: dict[str, dict[str, str]] = {}

        path = Path(locales_dir)
        if path.is_dir():
            for file in sorted(path.glob("*.json")):
                try:
                    data = json.loads(file.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    log.error("failed to load locale %s: %s", file, exc)
                    continue
                self._locales[file.stem.lower()] = {str(k): str(v) for k, v in data.items()}
            log.info("loaded locales: %s", ", ".join(sorted(self._locales)) or "(none)")
        else:
            log.error("locales dir not found: %s", locales_dir)

        if self._default_lang not in self._locales:
            log.warning(
                "default language %r has no locale file in %s",
                self._default_lang,
                locales_dir,
            )

    @property
    def available_languages(self) -> list[str]:
        return sorted(self._locales)

    def _lookup(self, lang: str, key: str) -> str:
        lang = (lang or "").lower()
        if key in self._locales.get(lang, {}):
            return self._locales[lang][key]
        if key in self._locales.get(self._default_lang, {}):
            return self._locales[self._default_lang][key]
        return key

    def t(self, lang: str, key: str, **kwargs: object) -> str:
        template = self._lookup(lang, key)
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            log.warning("bad localization template for key %r (lang %r): %s", key, lang, exc)
            fallback = self._lookup(self._default_lang, key)
            try:
                return fallback.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return fallback
