"""Attack coverage is legal, isolated and separate from posterior knowledge."""

from copy import deepcopy
from math import perm
import unittest

from tragedy_sim import Game
from tragedy_sim.dark_attack_scenarios import attack_dark_worlds, evacuation_bundles, legal_dark_bundles, with_dark_bundle
from tragedy_sim.engine import Placement
from tragedy_sim.oracle_protagonist import OracleProtagonistAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import SearchBudget


def threat_root():
    game = Game(ScenarioLibrary().get("official-fs-01-first-script"))
    while game.state.phase != "mastermind":
        game = game.search_transition(game.search_actions(game.controller)[0])
    for face, target in (("h", "girl"), ("p1a", "worker"), ("i1", "shrine")):
        game.dispatch("m", "play", card=face, target=target)
    game.state.loop, game.state.round = 2, 3
    game.state.characters["girl"].location = "hospital"
    game.state.characters["girl"].intrigue = 1
    game.state.characters["worker"].intrigue = 2
    game.state.discarded["m"].append("i2")
    game.state.hands["m"].remove("i2")
    return game


class DarkAttackScenariosTests(unittest.TestCase):
    def test_full_enumeration_matches_public_all_different_and_visible_faces(self):
        game = threat_root()
        view = game.protagonist_team_view()
        bundles = tuple(legal_dark_bundles(view))
        self.assertEqual(len(bundles), perm(9, 3))
        self.assertEqual(len(set(tuple(p.card for p in bundle) for bundle in bundles)), len(bundles))
        for bundle in bundles:
            self.assertEqual(len({p.card for p in bundle}), 3)
            self.assertNotIn("i2", {p.card for p in bundle})
            with_dark_bundle(game, bundle)
        visible = deepcopy(view)
        visible["pending"][0]["card"] = "h"
        self.assertEqual(len(tuple(legal_dark_bundles(visible))), perm(8, 2))
        self.assertTrue(all(bundle[0].card == "h" for bundle in legal_dark_bundles(visible)))

    def test_killer_vertical_attack_is_covered_and_real_engine_detects_loss(self):
        game = threat_root()
        view = game.protagonist_team_view()
        before = deepcopy(game.view("m"))
        variants = attack_dark_worlds(game, view)
        danger = next(world for world in variants if any(p.target == "worker" and p.card == "v"
                                                         for p in world.state.pending))
        bundle = ({"actor": "a", "action": "play", "card": "fi", "target": "shrine"},
                  {"actor": "b", "action": "play", "card": "fm", "target": "girl"},
                  {"actor": "c", "action": "play", "card": "p-1", "target": "doctor"})
        oracle = OracleProtagonistAgent(reveal_cards=True, script_aware_rollout=False)
        strategy = "key_assassination:target=girl,key=girl,killer=worker"
        _, survived = oracle._day_score(ParticleEnsembleProtagonistAgent._apply_bundle(danger, bundle),
                                        2, 3, mastermind_strategy=strategy)
        self.assertFalse(survived)
        self.assertEqual(game.view("m"), before)
        self.assertTrue(all(world.roles == game.roles for world in variants))
        self.assertTrue(all(world.scenario == game.scenario for world in variants))

    def test_disables_visible_cards_limit_and_red_prefix_are_preserved(self):
        game = threat_root()
        game.dispatch("a", "play", card="g1", target="doctor")
        view = deepcopy(game.protagonist_team_view())
        view["pending"][0]["card"] = "h"
        view.setdefault("public_setup", {}).setdefault("special_rules", {})["disabled_mastermind_cards"] = ["v"]
        variants = attack_dark_worlds(game, view, limit=2)
        self.assertLessEqual(len(variants), 2)
        for world in variants:
            master = [p for p in world.state.pending if p.actor == "m"]
            self.assertEqual(master[0].card, "h")
            self.assertNotIn("v", {p.card for p in master})
            self.assertEqual([p for p in world.state.pending if p.actor != "m"],
                             [p for p in game.state.pending if p.actor != "m"])
            self.assertEqual(world.state.hands["a"], game.state.hands["a"])
        for bad in (0, -1, True, "2"):
            with self.subTest(limit=bad), self.assertRaises(ValueError):
                attack_dark_worlds(game, view, limit=bad)
        with self.assertRaises(ValueError):
            with_dark_bundle(game, (Placement("m", "h", "girl"), Placement("m", "h", "worker"),
                                    Placement("m", "i1", "shrine")))

    def test_default_policy_is_unchanged_and_invalid_settings_fail(self):
        from benchmarks.ai_self_play import _policy_offer
        from tests.test_particle_ensemble import protagonist_position
        game = protagonist_position()
        view = game.protagonist_team_view()
        offers = [_policy_offer(game, a) for a in game.action_offers(game.controller)]
        agents = [ParticleEnsembleProtagonistAgent(SearchBudget(node_limit=2, seed=0), particle_count=2, **kwargs)
                  for kwargs in ({}, {"dark_card_policy": "sampled"})]
        choices = [agent.choose_action(participant="team", view=deepcopy(view), offers=offers) for agent in agents]
        self.assertEqual(choices[0], choices[1])
        traces = [agent.last_trace.to_dict() for agent in agents]
        for trace in traces:
            trace.pop("evidence_elapsed_ms")
            trace.pop("search_elapsed_ms")
        self.assertEqual(traces[0], traces[1])
        for kwargs in ({"dark_card_policy": "wrong"}, {"dark_attack_limit": 0}, {"dark_attack_limit": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ParticleEnsembleProtagonistAgent(**kwargs)

    def test_guard_evaluation_keeps_candidates_posterior_samples_and_rng(self):
        from benchmarks.ai_self_play import _policy_offer
        from tests.test_particle_ensemble import protagonist_position
        game = protagonist_position()
        offers = [_policy_offer(game, a) for a in game.action_offers(game.controller)]
        agents = [ParticleEnsembleProtagonistAgent(SearchBudget(node_limit=4, seed=3), particle_count=4,
                                                   rng_seed=3, dark_card_policy=policy, dark_guard_proposals=False)
                  for policy in ("sampled", "adversarial_guard")]
        for agent in agents:
            agent.choose_action(participant="team", view=deepcopy(game.protagonist_team_view()), offers=offers)
        a, b = agents
        self.assertEqual([row["bundle"] for row in a.last_trace.root_actions],
                         [row["bundle"] for row in b.last_trace.root_actions])
        self.assertEqual(a.last_trace.belief_roles, b.last_trace.belief_roles)
        self.assertEqual(a.last_trace.belief_dark_cards, b.last_trace.belief_dark_cards)
        self.assertEqual(a.factorized_belief.matrix_rng.getstate(), b.factorized_belief.matrix_rng.getstate())
        self.assertGreater(b.last_trace.dark_attack_probes, 0)
        self.assertGreater(b.last_trace.evaluated_pairs, a.last_trace.evaluated_pairs)

    def test_joint_evacuation_respects_actor_hands_and_partial_submissions(self):
        game = threat_root()
        game.state.hands["a"].remove("fm")
        game.state.discarded["a"].append("fm")
        view = game.protagonist_team_view()
        bases = (({"actor": "a", "action": "play", "card": "fi", "target": "shrine"},
                  {"actor": "b", "action": "play", "card": "fm", "target": "girl"},
                  {"actor": "c", "action": "play", "card": "p-1", "target": "doctor"}),)
        plans = evacuation_bundles(game, view, bases)
        desired = next(plan for plan in plans if any(p["card"] == "h" and p["target"] == "girl" for p in plan))
        self.assertEqual(next(p["actor"] for p in desired if p["card"] == "fm"), "b")
        self.assertTrue(any(p["card"] == "h" and p["target"] == "maiden" for p in desired))
        self.assertIsNotNone(ParticleEnsembleProtagonistAgent._apply_bundle(game, desired))
        self.assertEqual(evacuation_bundles(game, view, (bases[0][1:],)), ())
        for actor in ("b", "c"):
            view["team_hands"][actor].remove("fm")
        self.assertEqual(evacuation_bundles(game, view, bases), ())

    def test_exhaustive_audit_limit_never_publishes_truncated_success(self):
        from benchmarks.ai_calibration_matrix import source_digest
        from benchmarks.ai_dark_attack_audit import _exhaustive_world
        from dataclasses import asdict
        game = threat_root()
        job = {"sources": source_digest(), "view": game.protagonist_team_view(), "hypothesis": game.scenario,
               "original_dark": [asdict(p) for p in game.state.pending], "world_index": 0, "seed": 0,
               "face_limit": 1, "plans": {}}
        with self.assertRaisesRegex(ValueError, "no exhaustive"):
            _exhaustive_world(job)


if __name__ == "__main__":
    unittest.main()
