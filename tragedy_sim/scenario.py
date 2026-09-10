"""Strict JSON scenarios: invalid/unsupported rules fail before the game starts."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from .catalog import CHARACTERS, INCIDENT_NAMES, MODULES, PLOTS, ROLE_NAMES
from .engine import RuleError


HSA_GROUP_INCIDENTS = {"frenzied_night", "curse_awakening", "filth_overflow", "dead_apocalypse"}


def validate_scenario(data: dict) -> dict:
    from .rulesets.registry import get_ruleset
    if not isinstance(data, dict) or not isinstance(data.get("module"), str) or data["module"] not in MODULES:
        raise RuleError("不支持的模组；当前支持 " + " / ".join(MODULES))
    return get_ruleset(data["module"]).validator(data)


def load_scenario(path: str | Path) -> dict:
    return validate_scenario(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def example_scenario(module: str = "FS") -> dict:
    if module not in MODULES:
        raise RuleError("不支持的模组；当前支持 " + " / ".join(MODULES))
    if module == "MZ":
        main_plot = "mz_secret_record"
        subplots = ["mz_factor", "mz_doom_song"]
        cast = {"student": "ordinary", "girl": "key", "doctor": "brain",
                "worker": "conspiracy", "maiden": "factor", "patient": "prophet"}
    elif module == "MC":
        main_plot = "mc_event_web"
        subplots = ["mc_detective", "mc_absolute"]
        cast = {"student": "detective", "girl": "fool", "doctor": "conspiracy",
                "worker": "friend", "maiden": "obsessive", "patient": "ordinary"}
    elif module == "HSA":
        main_plot = "hsa_noble"
        subplots = ["love_hsa", "hsa_monster_plot"]
        cast = {"student": "ordinary", "girl": "key", "doctor": "vampire",
                "worker": "conspiracy", "maiden": "loved", "patient": "lover"}
    elif module == "WM":
        main_plot = "wm_gospel"
        subplots = ["wm_rumor", "wm_great_race"]
        cast = {"student": "serial", "girl": "key", "doctor": "deep_one",
                "worker": "conspiracy", "maiden": "cultist", "patient": "time_traveler"}
    elif module == "AHR":
        main_plot = "ahr_closed_future"
        subplots = ["ahr_puppet_lines", "ahr_beyond_worldline"]
        cast = {"student": "obsessive", "girl": "key", "doctor": "ahr_puppet",
                "worker": "fragment", "maiden": "piper", "patient": "alice",
                "nurse": "piper"}
    elif module == "LL":
        main_plot = "ll_final_plan"
        subplots = ["ll_beyond_worldline", "ll_x_citizen"]
        cast = {"student": "ordinary", "girl": "key", "doctor": "brain",
                "worker": "killer", "maiden": "factor", "patient": "ordinary"}
    else:
        main_plot = "murder_plan"
        subplots = ["rumor"] if module == "FS" else ["rumor", "threads"]
        cast = {"student": "ordinary", "girl": "key", "doctor": "brain", "worker": "killer",
                "maiden": "conspiracy", "patient": "ordinary"}
    return validate_scenario({
        "id": "silent-town-" + module.lower(), "title": "寂静小镇（原创教学剧本）", "module": module,
        "days": 3, "loops": 3, "main_plot": main_plot,
        "subplots": subplots, "cast": cast,
        "incidents": ([{"day": 2, "kind": "murder", "culprit": "doctor"},
                       {"day": 3, "kind": "cocoon", "culprit": "patient"}]
                      if module == "LL" else
                      [{"day": 1, "kind": "dimension_swap", "culprit": "student"},
                       {"day": 3, "kind": "hope_light", "culprit": "patient"}]
                      if module == "AHR" else
                      [{"day": 2, "kind": "discovery", "culprit": "doctor"},
                       {"day": 3, "kind": "mass_suicide", "culprit": "patient"}]
                      if module == "WM" else
                      [{"day": 2, "kind": "frenzied_murder", "culprit": "doctor"},
                       {"day": 3, "kind": "curse_declaration", "culprit": "patient"}]
                      if module == "HSA" else
                      [{"day": 2, "kind": "omen", "culprit": "girl"},
                       {"day": 3, "kind": "suicide", "culprit": "maiden"}]
                      if module == "MC" else
                      [{"day": 2, "kind": "serial_murder", "culprit": "doctor"},
                       {"day": 3, "kind": "suicide", "culprit": "patient"}]
                      if module == "MZ" else
                      [{"day": 2, "kind": "murder", "culprit": "doctor"},
                       {"day": 3, "kind": "suicide", "culprit": "patient"}]),
        "table_talk": module != "LL",
    })
