import io
import unittest
from unittest.mock import patch

from benchmarks.ai_proposal_regression_audit import (
    _culprit_composition, audit_trajectory, main, resample_probe,
)
from tragedy_sim import Game
from tragedy_sim.belief import FactorizedBeliefState
from tragedy_sim.belief import PublicEvidence
from tragedy_sim.witness import FsbtxWitnessCompiler
import random
from tragedy_sim.replay import dumps, ReplayArchive


def completed_row():
    game = Game({"id": "proposal-audit", "title": "audit", "module": "FS",
                 "days": 1, "loops": 1, "main_plot": "protect", "subplots": ["rumor"],
                 "cast": {"girl": "key", "maiden": "cultist", "worker": "conspiracy"},
                 "incidents": [], "table_talk": True})
    while game.state.phase != "mastermind":
        game.dispatch(**game.search_actions(game.controller)[0])
    for card, target in (("i2", "school"), ("fg", "maiden"), ("fp", "girl")):
        game.dispatch("m", "play", card=card, target=target)
    for actor, target in zip("abc", ("girl", "maiden", "worker")):
        game.dispatch(actor, "play", card="g1", target=target)
    for _ in range(100):
        if game.winner:
            break
        game.dispatch(**game.search_actions(game.controller)[0])
    assert game.winner == "mastermind"
    return {"replay_text": dumps(game), "seed": 1, "strategy": "fixed"}


class ProposalRegressionAuditTests(unittest.TestCase):
    def test_culprit_composition_conditions_on_repeat_rule(self):
        def row(day, kind, probabilities):
            return {"day": day, "kind": kind, "hard_domain": tuple(probabilities),
                    "precomposition_probabilities": probabilities}
        profile = [row(1, "suicide", {"girl": 1.0}),
                   row(2, "hospital", {"girl": 0.5, "maiden": 0.5})]
        result = _culprit_composition(profile)
        self.assertEqual(result["legal_assignments"], 1)
        self.assertEqual(result["independent_draw_acceptance"], 0.5)
        self.assertEqual(result["conditioned_probabilities"][2], {"maiden": 1.0})
        for kind, expected in (("serial_murder", 2), ("hospital", 1)):
            profile = [row(1, "serial_murder", {"girl": 1.0}),
                       row(2, kind, {"girl": 0.5, "maiden": 0.5})]
            self.assertEqual(_culprit_composition(profile)["legal_assignments"], expected)
        self.assertFalse(_culprit_composition(profile, limit=1)["complete"])

    def test_resampling_preserves_frozen_pool_and_generator_rng(self):
        game = Game(ReplayArchive.parse(completed_row()["replay_text"]).scenario)
        while game.state.phase != "protagonists":
            game = game.search_transition(game.search_actions(game.controller)[0])
        view = game.protagonist_team_view()
        evidence = PublicEvidence.from_view(view)
        facts = FsbtxWitnessCompiler().compile(view)
        state = FactorizedBeliefState(seed=2, joint_culprits=True)
        state.sample(evidence, facts, 2, rng=random.Random(3))
        rng, summary = state.rng.getstate(), state.proposal_summary()
        flags = []
        original = FactorizedBeliefState.sample
        def observe(frozen, *args, **kwargs):
            flags.append(frozen.joint_culprits_enabled)
            return original(frozen, *args, **kwargs)
        with patch.object(FactorizedBeliefState, "sample", observe):
            result = resample_probe(state, evidence, facts, view, (), counts=(2, 4), draws=2, seed=1)
        self.assertEqual(flags, [True] * 4)
        self.assertEqual(len(result), 4)
        self.assertEqual([r["materialized_worlds"] for r in result], [2, 2, 4, 4])
        self.assertEqual(state.rng.getstate(), rng)
        self.assertEqual(state.proposal_summary(), summary)

    def test_timeline_covers_every_command_and_keeps_sampling_public(self):
        row = completed_row()
        inputs = []
        original = FactorizedBeliefState.sample
        def observe(state, evidence, witnesses, count, *, rng):
            inputs.append(evidence)
            return original(state, evidence, witnesses, count, rng=rng)
        with patch.object(FactorizedBeliefState, "sample", observe):
            result = audit_trajectory(row, matrix_proposals=True, worlds=2)
        self.assertEqual(len(result["timeline"]), len(ReplayArchive.parse(row["replay_text"]).commands))
        self.assertEqual(len(result["roots"]), 1)
        self.assertTrue(inputs)
        self.assertTrue(all(e.module == "FS" and not e.known_roles for e in inputs))
        self.assertTrue(result["roots"][0]["truth_hard_compatible"])
        self.assertIsNone(result["roots"][0]["recorded_sampling_matches"])
        self.assertTrue(all(p["card"] is None for p in result["roots"][0]["public_board"]["pending"]))
        self.assertEqual(row, completed_row())
        self.assertTrue(result["roots"][0]["culprit_composition"]["complete"])

    def test_fixed_path_sampling_and_timeline_are_repeatable(self):
        row = completed_row()
        self.assertEqual(audit_trajectory(row, matrix_proposals=False, worlds=2),
                         audit_trajectory(row, matrix_proposals=False, worlds=2))

    def test_cli_rejects_unpaired_or_nonpositive_probe(self):
        for options in (("--probe-loop", "1"), ("--worlds", "0"),
                        ("--probe-loop", "0", "--probe-day", "1"),
                        ("--resample-worlds", "12")):
            with (patch("sys.argv", ["audit", "unused-a.json", "unused-b.json",
                                     "--output", "unused.json", *options]),
                  patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as error):
                main()
            self.assertEqual(error.exception.code, 2)
