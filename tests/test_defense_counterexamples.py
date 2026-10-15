"""Candidate-dependent attacks remain separate from public inference."""

from copy import deepcopy
from unittest.mock import patch
import unittest

from tests.test_dark_attack_scenarios import threat_root
from tragedy_sim.dark_attack_scenarios import legal_dark_bundles, tactical_dark_key, with_dark_bundle
from tragedy_sim.defense_counterexamples import refine_defense
from tragedy_sim.engine import Placement
from tragedy_sim.joint_action_space import JointActionSpace
from tragedy_sim.joint_defense_ranker import JointThreatRanker, TacticalWorldModel
from tragedy_sim.oracle_protagonist import HiddenCardOracleProtagonistAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.search import SearchBudget


def regression_root():
    """Public board/resources from the audited FS01 loop2/day3 replay."""
    game = with_dark_bundle(threat_root(), (Placement("m", "h", "girl"),
                                            Placement("m", "v", "worker"), Placement("m", "i1", "shrine")))
    game.state.characters["student"].intrigue = 1
    game.state.characters["police"].alive = False
    game.state.characters["worker"].paranoia = 3
    game.state.characters["worker"].goodwill = 1
    for actor, card in (("a", "p-1"), ("b", "p-1"), ("c", "fm")):
        game.state.hands[actor].remove(card)
        game.state.discarded[actor].append(card)
    return game


class DefenseCounterexampleTests(unittest.TestCase):
    def test_refined_regression_plan_survives_all_legal_dark_faces(self):
        from benchmarks.ai_self_play import _policy_offer
        game = regression_root()
        before = deepcopy(game.view("m"))
        agent = HiddenCardOracleProtagonistAgent(SearchBudget(node_limit=4), candidate_policy="joint_counterexample")
        agent.choose_game_action(participant="team", game=game,
                                 offers=[_policy_offer(game, p) for p in game.action_offers(game.controller)])
        stats = agent.last_trace.counterexample_search
        self.assertEqual(stats["legal_assignments"], 504)
        self.assertGreater(stats["added"], 0)
        self.assertLessEqual(stats["engine_probes"], 16)
        self.assertFalse(stats["complete_engine_scan"])
        self.assertEqual(game.view("m"), before)
        for faces in legal_dark_bundles(game.protagonist_team_view()):
            world = with_dark_bundle(game, faces)
            after = ParticleEnsembleProtagonistAgent._apply_bundle(world, agent.last_trace.selected_bundle)
            for route in agent._mastermind_strategy_options(world):
                self.assertTrue(agent._day_score(after, 2, 3, mastermind_strategy=route)[1], (faces, route))

    def test_unconfirmed_threats_do_not_enter_common_worlds(self):
        game = threat_root()
        view = game.protagonist_team_view()
        space = JointActionSpace(view, game.search_actions(game.controller))
        candidates, _ = space.ranked_bundles(lambda _: 0, 1)
        with patch("tragedy_sim.defense_counterexamples.TacticalWorldModel") as model:
            model.return_value.score.return_value = (1, 0)
            worlds, plans, stats = refine_defense(game, view, space, (game,), candidates, lambda _: 0, 1,
                                                 lambda *_: False, probe_limit=2)
        self.assertEqual(worlds, (game,))
        self.assertEqual(plans, candidates)
        self.assertEqual(stats["added"], 0)
        self.assertEqual(stats["engine_probes"], 2)
        self.assertEqual(stats["stop"], "probe_limit")

    def test_expired_deadline_keeps_existing_complete_candidates(self):
        game = threat_root()
        view = game.protagonist_team_view()
        space = JointActionSpace(view, game.search_actions(game.controller))
        candidates, _ = space.ranked_bundles(lambda _: 0, 1)
        with patch("tragedy_sim.defense_counterexamples.perf_counter", return_value=2):
            worlds, plans, stats = refine_defense(game, view, space, (game,), candidates, lambda _: 0, 1,
                                                 lambda *_: self.fail("deadline must skip engine probes"), deadline=1)
        self.assertEqual((worlds, plans), ((game,), candidates))
        self.assertEqual(stats["stop"], "deadline")
        self.assertFalse(stats["complete_engine_scan"])

    def test_blind_refinement_is_independent_of_true_pending_faces(self):
        from benchmarks.ai_self_play import _policy_offer
        a = threat_root()
        b = with_dark_bundle(a, (Placement("m", "v", "girl"), Placement("m", "i1", "worker"),
                                Placement("m", "h", "shrine")))
        b.state.events = deepcopy(a.state.events)
        agents = []
        for game in (a, b):
            agent = HiddenCardOracleProtagonistAgent(SearchBudget(node_limit=1), candidate_policy="joint_counterexample")
            agent.choose_game_action(participant="team", game=game,
                                     offers=[_policy_offer(game, p) for p in game.action_offers(game.controller)])
            agents.append(agent)
        self.assertEqual(agents[0].last_trace.selected_bundle, agents[1].last_trace.selected_bundle)
        self.assertEqual(agents[0].last_trace.counterexample_search, agents[1].last_trace.counterexample_search)

    def test_mixed_identity_worlds_are_rejected(self):
        game = threat_root()
        other = game.search_clone()
        other.roles["girl"] = "ordinary"
        with self.assertRaisesRegex(ValueError, "one role"):
            refine_defense(game, game.protagonist_team_view(), None, (game, other), (), lambda _: 0, 1, lambda *_: False)

    def test_board_noops_merge_but_limited_consumption_stays_distinct(self):
        def key(face):
            return tactical_dark_key((Placement("m", face, "school"),), {"school": 0})
        self.assertEqual(key("h"), key("fg"))
        self.assertEqual(key("p1a"), key("p-1"))
        self.assertNotEqual(key("i1"), key("i2"))
        self.assertNotEqual(key("i1"), key("h"))
        self.assertNotEqual(key("d"), key("h"))
        self.assertEqual(tactical_dark_key((Placement("m", "p1a", "girl"),), {}),
                         tactical_dark_key((Placement("m", "p1b", "girl"),), {}))

    def test_grouped_scan_preserves_raw_probe_order_and_candidates(self):
        game = threat_root()
        view = game.protagonist_team_view()
        space = JointActionSpace(view, game.search_actions(game.controller))
        candidates, _ = space.ranked_bundles(lambda _: 0, 2)
        outputs, probes = [], []
        for compressed in (False, True):
            observed = []
            def reject(world, _):
                observed.append(tuple(p.card for p in world.state.pending if p.actor == "m"))
                return False
            with patch("tragedy_sim.defense_counterexamples.TacticalWorldModel") as model:
                model.return_value.score.return_value = (1, 0)
                outputs.append(refine_defense(game, view, space, (game,), candidates, lambda _: 0, 2,
                                               reject, probe_limit=4, compress=compressed))
            probes.append(observed)
        self.assertEqual(probes[0], probes[1])
        self.assertEqual(outputs[0][:2], outputs[1][:2])
        self.assertEqual(outputs[0][2]["legal_assignments"], outputs[1][2]["legal_assignments"])
        self.assertLess(outputs[1][2]["tactical_groups"], outputs[0][2]["tactical_groups"])
        self.assertLess(outputs[1][2]["tactical_checks"], outputs[0][2]["tactical_checks"])

    def test_all_group_members_have_identical_projected_risk(self):
        game = regression_root()
        view = game.protagonist_team_view()
        space = JointActionSpace(view, game.search_actions(game.controller))
        plan = next(space.iter_plans())
        scores = {}
        for faces in legal_dark_bundles(view):
            key = tactical_dark_key(faces, view["locations"])
            score = TacticalWorldModel(with_dark_bundle(game, faces), space).score(plan)
            if key in scores:
                self.assertEqual(scores[key], score)
            scores[key] = score

    def test_incremental_ranking_exactly_matches_fresh_world_order(self):
        game = threat_root()
        view = game.protagonist_team_view()
        space = JointActionSpace(view, game.search_actions(game.controller))
        from itertools import islice
        worlds = tuple(with_dark_bundle(game, p) for p in islice(legal_dark_bundles(view), 4))
        plans = list(islice(space.iter_plans(), 20))
        for capacity in (0, 1, 64):
            ranker = JointThreatRanker(worlds[:2], space, cache_limit=capacity)
            for plan in plans:
                ranker(plan)
            ranker.add_worlds(worlds[2:])
            fresh = JointThreatRanker(worlds, space)
            for plan in plans:
                self.assertEqual(ranker(plan), fresh(plan))
            if capacity == 64:
                self.assertEqual(ranker.projections, fresh.projections)
            self.assertLessEqual(len(ranker.cache), capacity)


if __name__ == "__main__":
    unittest.main()
