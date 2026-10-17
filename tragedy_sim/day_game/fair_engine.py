"""FS finite-world payoffs with one frozen, observable red continuation.

Red policies receive detached authorized state, own commands, and legal red
offers only. No private Game, type label, true role, or hidden command count
is provided. All legal black post-reveal choices remain adversarial. This
solves the fixed-policy model, not the unrestricted information-set game.
"""

from dataclasses import dataclass
import json

from ..domain import InformationState
from .bayesian import BayesianGame, WorldBlock
from .cached import CachedDayContinuationSolver
from .engine_game import EngineDayGame
from .keys import UnsupportedKey, rule_state_key


def _command_key(command):
    return json.dumps(command, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def public_policy_input(world, offers=()):
    # Private black decisions (including their count) are not observations.
    # Their visible outcomes remain in the authorized event history. Own
    # commands retain perfect recall, including private answers in the view.
    own = [c for c in world.history if c.get("actor") in {"a", "b", "c"}]
    payload = dict(state=world.protagonist_team_view(), own_commands=own,
                   offers=sorted((dict(a) for a in offers), key=_command_key))
    return InformationState.create("team", payload)


@dataclass(frozen=True)
class PublicSkipOptionalPolicy:
    """Deterministic observation-only baseline; deliberately not a strong AI."""
    version: str = "public-skip-optional-v1"

    def choose(self, information):
        commands = information.to_dict()["offers"]
        if not commands:
            raise ValueError("red policy received an empty legal menu")
        return next((a for a in commands if a["action"] == "pass"), commands[0])


class FixedPolicyDayContinuation(CachedDayContinuationSolver):
    def __init__(self, policy, *, backend="cached", max_depth=256, capacity=100000):
        if (not isinstance(getattr(policy, "version", None), str) or not policy.version
                or not callable(getattr(policy, "choose", None))):
            raise ValueError("a versioned pure observable policy is required")
        if backend not in {"reference", "cached", "compiled"}:
            raise ValueError("unknown fixed-policy backend")
        super().__init__(max_depth=max_depth, capacity=capacity, compiled=backend == "compiled")
        self._policy, self._policy_version, self.backend = policy, policy.version, backend

    def _check_policy(self):
        if self._policy.version != self._policy_version:
            raise ValueError("continuation policy version changed during a fixed-model solve")

    def _transition(self, current, action):
        if self.backend == "reference":
            return current.transition(action).game
        return super()._transition(current, action)

    def _actions(self, current, actor):
        self._check_policy()
        actions = current.legal_actions(actor)
        if actor == "m":
            return actions
        selected = self._policy.choose(public_policy_input(current, actions))
        if selected not in actions:
            raise ValueError("observable red policy returned an illegal command")
        return [dict(selected)]

    def _cache_key(self, current, position):
        self._check_policy()
        if self.backend == "reference":
            return None
        try:
            # Unlike known-state minimax, a fixed observable policy depends on
            # public history/knowledge even for an identical physical state.
            return ("fs-fixed-public-policy-day-v1", self._policy_version, position,
                    rule_state_key(current), public_policy_input(current).key)
        except (UnsupportedKey, RecursionError):
            self.stats.fallbacks += 1
            return None


class FixedPolicyDayGame(EngineDayGame):
    scope = "FS/fixed-observable-red-continuation/all-legal-black-day-responses"

    def __init__(self, world, *, policy=None, backend="cached", max_depth=256, cache_capacity=100000):
        super().__init__(world, backend=backend, max_depth=max_depth, cache_capacity=cache_capacity)
        self.continuation = FixedPolicyDayContinuation(PublicSkipOptionalPolicy() if policy is None else policy, backend=backend,
                                                      max_depth=max_depth, capacity=cache_capacity)
        if backend != "reference":
            self.kernel = self.continuation.kernel
        self.root_information = public_policy_input(self._root)


def bayesian_engine_game(worlds, *, belief_domain_complete=False, policy=None, backend="cached",
                         max_depth=256, cache_capacity=100000):
    """worlds is (label, ORIGINAL mass, private sampled Game) triples.

    Sampling/materialization is an upstream belief concern. No original true
    world is accepted as privileged input. Every root must have the same
    authorized information, including persistent public and own history.
    """
    policy = PublicSkipOptionalPolicy() if policy is None else policy
    blocks = tuple(WorldBlock(label, mass, FixedPolicyDayGame(world, policy=policy, backend=backend,
                             max_depth=max_depth, cache_capacity=cache_capacity)) for label, mass, world in worlds)
    if not blocks or any(b.game.root_information.key != blocks[0].game.root_information.key for b in blocks):
        raise ValueError("world roots have different authorized protagonist information")
    return BayesianGame(blocks, belief_domain_complete=belief_domain_complete,
                        scope=FixedPolicyDayGame.scope + "/" + policy.version)
