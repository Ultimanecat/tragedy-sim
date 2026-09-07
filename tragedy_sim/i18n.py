"""Configuration-backed terminology and timepoint formatting."""

from __future__ import annotations

from functools import lru_cache
import json
from importlib.resources import files
from typing import Any


DEFAULT_LANGUAGE = "zh"
SUPPORTED_LANGUAGES = ("zh", "en", "ja")


def normalize_language(language: str | None) -> str:
    value = (language or DEFAULT_LANGUAGE).lower().replace("_", "-")
    aliases = {"zh-cn": "zh", "zh-hans": "zh", "jp": "ja", "ja-jp": "ja", "en-us": "en", "en-gb": "en"}
    value = aliases.get(value, value.split("-", 1)[0])
    if value not in SUPPORTED_LANGUAGES:
        raise ValueError(f"不支持的语言：{language}；可选 zh / en / ja")
    return value


@lru_cache(maxsize=None)
def locale(language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    language = normalize_language(language)
    resource = files("tragedy_sim").joinpath("locales", f"{language}.json")
    return json.loads(resource.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def terminology() -> dict[str, Any]:
    resource = files("tragedy_sim").joinpath("locales", "terminology.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def label(group: str, key: str, language: str = DEFAULT_LANGUAGE, *, fallback: str | None = None) -> str:
    language = normalize_language(language)
    value = locale(language).get(group, {}).get(key)
    if value is None:
        value = terminology().get(group, {}).get(key, {}).get(language)
    if value is None and language != DEFAULT_LANGUAGE:
        value = locale(DEFAULT_LANGUAGE).get(group, {}).get(key)
    return fallback if value is None and fallback is not None else (value if value is not None else key)


def format_timepoint(timing: str, loop: int, day: int, language: str = DEFAULT_LANGUAGE) -> str:
    template = label("timepoints", timing, language)
    return template.format(loop=loop, day=day)
