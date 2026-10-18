"""Complete compatible FS histories from authorized events and own commands.

Past revealed cards constrain their original placements. Other hidden choices
are enumerated with the native engine. Histories have no invented probability:
their current states are adversarial alternatives within ONE setup type.
"""

from copy import deepcopy
from dataclasses import dataclass

from ..belief import PublicSnapshot
from ..game import Game
from .continuation import WorkLimit
from .keys import UnsupportedKey, rule_state_key


@dataclass(frozen=True)
class HistorySupport:
    roots: tuple
    complete: bool
    nodes: int
    transitions: int
    reasons: tuple
    merged: int


def replay_public_history(hypothesis, evidence, view, own_commands=(), *, work=None, max_depth=1024):
    """No true-world input, prior, hidden command count, or script lookup.

    Coverage concerns the supplied event transcript and own-command memory.
    Additional unrecorded observations can only narrow this conservative set.
    A partial traversal NEVER supplies a complete model, even if it found roots.
    Current hidden faces are represented canonically; the day game's complete
    face domain subsequently restores and enumerates their physical resources.
    """
    if (evidence.module != "FS" or view.get("module") != "FS" or view.get("viewer") != "team"
            or view.get("phase") != "protagonists" or "secret" in view
            or len(view.get("pending", ())) != 3
            or any(p.get("actor") != "m" or p.get("card") is not None for p in view["pending"])):
        raise ValueError("history replay requires authorized FS team information")
    if any(not isinstance(c, dict) or c.get("actor") not in {"a", "b", "c"}
           or not isinstance(c.get("action"), str) for c in own_commands):
        raise ValueError("history replay accepts protagonist own commands only")
    if type(max_depth) is not int or max_depth < 1:
        raise ValueError("history depth must be positive")
    work = WorkLimit(node_limit=10000) if work is None else work
    before_nodes, before_edges = work.nodes, work.transitions
    target = (view["loop"], view["round"])
    received = tuple(PublicSnapshot.from_view(dict(event=e)).key for e in view.get("events", ()))
    own_commands = tuple(deepcopy(own_commands))
    revealed = {}
    for event in view.get("events", ()):
        if event.get("kind") == "cards_revealed":
            key = event["loop"], event["round"]
            if key in revealed:
                raise ValueError("ambiguous repeated reveal in history")
            revealed[key] = tuple(dict(actor=p["actor"], action="play", card=p["card"], target=p["target"])
                                  for p in event["cards"])
    scenario = hypothesis.materialize(evidence)
    scenario.update(id=str(view.get("scenario_id", scenario["id"])), title=str(view.get("title", scenario["title"])))
    initial = Game(scenario)
    stack, seen, roots, reasons, merged = [(initial, 0, 0)], set(), [], set(), 0
    while stack:
        if work.exhausted():
            reasons.update(work.reasons)
            break
        current, own_index, depth = stack.pop()
        work.nodes += 1
        position = current.state.loop, current.state.round
        events = tuple(PublicSnapshot.from_view(dict(event=e)).key for e in current.state.events)
        if position > target or len(events) > len(received) or events != received[:len(events)]:
            continue
        try:
            key = rule_state_key(current), own_index, events
        except UnsupportedKey:
            reasons.add("history_unsupported_key")
            break
        if key in seen:
            merged += 1
            continue
        seen.add(key)
        if position == target and current.state.phase == "protagonists":
            if (own_index == len(own_commands)
                    and PublicSnapshot.from_view(current.protagonist_team_view()) == PublicSnapshot.from_view(view)):
                # Keep the text actually received, not replay-local labels.
                current.state.events = deepcopy(list(view.get("events", ())))
                roots.append(current)
            continue
        if current.winner is not None or current.state.phase in {"final_guess", "game_over"}:
            continue
        if depth >= max_depth:
            reasons.add("history_depth_limit")
            continue
        actor = current.controller
        actions = current.legal_actions(actor)
        if actor != "m":
            actions = ([own_commands[own_index]] if own_index < len(own_commands)
                       and own_commands[own_index] in actions else [])
        elif current.state.phase == "mastermind":
            if position == target:
                # All legal current face triples are restored in the payoff
                # model. Only their already observed targets matter here.
                index = len(current.state.pending)
                placements = view.get("pending", ())
                wanted = placements[index]["target"] if index < len(placements) else None
                actions = [next((a for a in actions if a.get("target") == wanted), None)]
                actions = [a for a in actions if a is not None]
            else:
                index = len(current.state.pending)
                cards = revealed.get(position, ())
                actions = [cards[index]] if index < len(cards) and cards[index] in actions else []
        for action in reversed(actions):
            if work.time_limit_ms is not None and work.exhausted():
                reasons.update(work.reasons)
                break
            successor = current.transition(action).game
            work.transitions += 1
            stack.append((successor, own_index + (actor != "m"), depth+1))
    return HistorySupport(tuple(roots), not reasons, work.nodes-before_nodes, work.transitions-before_edges,
                          tuple(sorted(reasons)), merged)
