"""Contract tests for the explicit phase resolver registry."""

import unittest

from tragedy_sim import Game, PhaseId
from tragedy_sim.phases import PHASE_RESOLVERS, PhaseRegistry


class PhaseResolverTests(unittest.TestCase):
    def test_every_runtime_phase_has_exactly_one_resolver(self):
        for phase in set(PhaseId) - {PhaseId.RESOLVED}:
            self.assertEqual(PHASE_RESOLVERS.resolve(phase).phase, phase)
        with self.assertRaises(ValueError):
            PhaseRegistry(())

    def test_game_facade_delegates_commands_and_has_no_central_advance_switch(self):
        game = Game()
        self.assertFalse(hasattr(game, "_advance"))
        self.assertEqual(game.controller, "m")
        self.assertEqual(game.legal_actions("m"), [{"actor": "m", "action": "next"}])
        game.dispatch("m", "next")
        self.assertEqual(game.state.phase, "mastermind")
        self.assertEqual(game.controller, "m")

    def test_typed_and_legacy_actions_stay_in_lockstep_after_phase_transition(self):
        game = Game()
        game.dispatch("m", "next")
        commands = game.legal_actions("m")
        self.assertEqual([offer.command for offer in game.action_offers("m")], commands)
        command = dict(commands[0])
        result = game.simulate(command.pop("actor"), command.pop("action"), **command)
        self.assertEqual(result.decision.after.phase, PhaseId.MASTERMIND)
        self.assertEqual(len(result.game.state.pending), 1)


if __name__ == "__main__":
    unittest.main()
