"""Audited FS rule transitions without deep-copying private diagnostic output.

All rule fields, events, commands, knowledge and checkpoints are detached.
Only append-only private traces/decision diagnostics are discarded. Full
transition remains the reference and fallback; this is not a replay producer.
"""

from copy import deepcopy

from .keys import DIAGNOSTICS, UnsupportedKey, audited_fs, rule_state_key


class FsTransitionKernel:
    version = "fs-detached-v1"

    def __init__(self):
        self.compact_clones = 0
        self.fallback_clones = 0

    def clone(self, world):
        try:
            if not audited_fs(world):
                raise UnsupportedKey("unrecognized engine")
            # Also checks that new field types/components have not escaped
            # the audited representation. Keep them on the full engine path.
            rule_state_key(world)
        except (UnsupportedKey, RecursionError):
            self.fallback_clones += 1
            return world.clone()
        memo = {id(world.ruleset): world.ruleset, id(world.script): world.script}
        for name in DIAGNOSTICS:
            memo[id(getattr(world, name))] = []
        self.compact_clones += 1
        return deepcopy(world, memo)

    def transition(self, world, action):
        command = deepcopy(dict(action))
        actor, action = command.pop("actor"), command.pop("action")
        fallbacks_before = self.fallback_clones
        clone = self.clone(world)
        if self.fallback_clones != fallbacks_before:
            return world.transition({"actor": actor, "action": action, **command}).game
        # Failure can discard this detached successor. The caller's world is
        # never partially mutated; validation/authorization still use the engine.
        clone._dispatch(actor, action, command, atomic=False, record_observation=False)
        return clone
