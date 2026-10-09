"""Constructive alternatives for hard existential role witnesses.

Only public witness values and candidate plots are inputs. Each assignment
is one sufficient explanation; the full matcher still validates the world.
"""

from __future__ import annotations

from typing import Any, Sequence

from .common_loop_end import loop_end_realizations


HARD_ROLE_ROUTES = frozenset({
    "mastermind_ability_route", "mandatory_serial_route",
    "loop_end_plot_explanation", "role_pressure", "role_route_pressure",
})


def role_route_realizations(witness: Any, plots: Sequence[str]
                            ) -> tuple[dict[str, str], ...]:
    value = witness.value
    if witness.kind == "loop_end_plot_explanation":
        return loop_end_realizations(str(witness.subject), str(plots[0]), value)
    if witness.kind == "mastermind_ability_route":
        if set(value.get("plots", ())) & set(plots):
            return ({},)
        routes = value.get("roles", {})
    elif witness.kind == "mandatory_serial_route":
        routes = {"serial": value.get("serial", ())}
        if "virus" in plots:
            routes["ordinary"] = value.get("virus_ordinary", ())
    elif witness.kind == "role_pressure":
        routes = {str(witness.subject): value.get("candidates", ())}
    elif witness.kind == "role_route_pressure":
        routes = value
    else:
        raise ValueError(f"unsupported role route: {witness.kind}")
    return tuple({"part_timer" if cid == "part_timer_question" else str(cid): str(role)}
                 for role, candidates in routes.items() for cid in candidates)
