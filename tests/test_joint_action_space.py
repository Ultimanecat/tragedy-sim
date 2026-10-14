"""Authorized, resource-aware complete defense-space enumeration."""

from copy import deepcopy
from itertools import product
import random
import unittest
from unittest.mock import patch

from tests.test_dark_attack_scenarios import threat_root
from tragedy_sim.dark_attack_scenarios import with_dark_bundle
from tragedy_sim.engine import Placement
from tragedy_sim.joint_action_space import DefenseRequirement, JointActionSpace, UnsupportedJointSpace
from tragedy_sim.oracle_protagonist import FullCardOracleProtagonistAgent, HiddenCardOracleProtagonistAgent
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.search import SearchBudget


def space_for(game):
    return JointActionSpace(game.protagonist_team_view(), game.search_actions(game.controller))


class JointActionSpaceTests(unittest.TestCase):
    def test_complete_product_matches_independent_target_and_forbid_checks(self):
        game = threat_root()
        space = space_for(game)
        expected = {p for p in product(*space.domains)
                    if len(set(a.target for a in p)) == len(p) and sum(a.card == "fi" for a in p) <= 1}
        actual = set(space.iter_plans())
        self.assertEqual(actual, expected)
        self.assertGreater(len(actual), 10000)
        self.assertEqual(len(actual), len(list(space.iter_plans())))
        before = deepcopy(game.view("m"))
        for plan in random.Random(0).sample(sorted(actual), 24):
            self.assertIsNotNone(ParticleEnsembleProtagonistAgent._apply_bundle(game, tuple(p.command() for p in plan)))
        self.assertEqual(game.view("m"), before)

    def test_noop_fillers_preserve_scarce_cards_and_three_placements(self):
        game = threat_root()
        space = space_for(game)
        fill = [plan for plan in space.iter_plans() if all(p in space.filler_placements for p in plan)]
        self.assertEqual(len(fill), 24)  # four boards, three distinct seats
        self.assertTrue(all(all(p.card == "g1" for p in plan) for plan in fill))
        after = ParticleEnsembleProtagonistAgent._apply_bundle(game, tuple(p.command() for p in fill[0]))
        after.resolve()
        after._resolve_counters()
        self.assertEqual(after.state.discarded["a"], game.state.discarded["a"])
        self.assertEqual(after.state.characters["girl"].paranoia, game.state.characters["girl"].paranoia)

    def test_zero_paranoia_filter_and_combined_forbidden_movement(self):
        game = threat_root()
        game.state.characters["girl"].paranoia = 0
        game.state.characters["girl"].forbidden = ("shrine",)
        space = space_for(game)
        effects = {p.effect for p in space.domains[0]}
        self.assertIn(("p-1", "girl"), effects)
        self.assertIn(("h", "girl"), effects)
        self.assertNotIn(("p-1", "doctor"), effects)
        self.assertNotIn(("fm", "doctor"), effects)
        self.assertNotIn(("fi", "doctor"), effects)
        self.assertTrue(space.pruning["paranoia_decrease_no_effect"])

    def test_visible_faces_tighten_filters_without_reading_true_pending(self):
        game = threat_root()
        changed = with_dark_bundle(game, (Placement("m", "v", "girl"), Placement("m", "p1b", "worker"),
                                          Placement("m", "i1", "shrine")))
        # Search clones trim replay history; restore the same authorized history
        # to isolate hidden faces instead of changing two input dimensions.
        changed.state.events = deepcopy(game.state.events)
        self.assertEqual(game.protagonist_team_view(), changed.protagonist_team_view())
        self.assertEqual(space_for(game).domains, space_for(changed).domains)
        view = game.protagonist_team_view()
        view["pending"][0]["card"] = "h"
        space = JointActionSpace(view, game.search_actions(game.controller))
        self.assertFalse(any(p.card == "p-1" and p.target == "girl" for p in space.domains[0]))

    def test_partial_prefix_is_fixed_and_forbid_overflow_can_complete(self):
        game = threat_root()
        game.dispatch("a", "play", card="fi", target="shrine")
        for overflow in (False, True):
            if overflow:
                game.dispatch("b", "play", card="fi", target="girl")
            space = space_for(game)
            self.assertEqual(space.prefix_forbid_overflow, overflow)
            self.assertEqual(len(space.domains), 1 if overflow else 2)
            self.assertFalse(any(p.card == "fi" for domain in space.domains for p in domain))
            plans = list(space.iter_plans())
            self.assertTrue(plans)
            for plan in plans[:12]:
                self.assertTrue(all(p.target not in {q.target for q in space.prefix} for p in plan))
                self.assertIsNotNone(ParticleEnsembleProtagonistAgent._apply_bundle(game, tuple(p.command() for p in plan)))

    def test_necessary_conjunction_keeps_seat_assignments_and_resources(self):
        game = threat_root()
        game.state.hands["a"].remove("fm")
        space = space_for(game)
        requirement = DefenseRequirement(((("fm", "worker"), ("h", "girl"), ("h", "maiden")),), "test_proven")
        plans = list(space.iter_plans((requirement,)))
        self.assertEqual(len(plans), 4)
        self.assertEqual({p.actor for plan in plans for p in plan if p.card == "fm"}, {"b", "c"})
        for plan in plans:
            self.assertIsNotNone(ParticleEnsembleProtagonistAgent._apply_bundle(game, tuple(p.command() for p in plan)))

    def test_alternatives_propagate_unique_owner_and_handle_impossible_clauses(self):
        game = threat_root()
        game.state.hands["b"].remove("fm")
        game.state.hands["c"].remove("fm")
        space = space_for(game)
        requirement = DefenseRequirement(((("fm", "worker"),),), "unique_owner")
        escape = DefenseRequirement(((("h", "girl"),), (("v", "girl"),)), "alternative_escape")
        plans = list(space.iter_plans((requirement, escape)))
        self.assertTrue(plans)
        self.assertTrue(all(p[0].card == "fm" and p[0].target == "worker" for p in plans))
        self.assertEqual({q.card for p in plans for q in p if q.target == "girl"}, {"h", "v"})
        impossible = DefenseRequirement(((("p-1", "doctor"),),), "impossible_effect")
        self.assertEqual(list(space.iter_plans((impossible,))), [])
        conflict = DefenseRequirement(((("h", "worker"),),), "same_target_conflict")
        self.assertEqual(list(space.iter_plans((requirement, conflict))), [])
        self.assertTrue(list(space.iter_plans()))

    def test_committed_effect_satisfies_requirement(self):
        game = threat_root()
        game.dispatch("a", "play", card="g1", target="doctor")
        space = space_for(game)
        requirement = DefenseRequirement(((("g1", "doctor"),),), "already_committed")
        self.assertEqual(list(space.iter_plans()), list(space.iter_plans((requirement,))))

    def test_rank_shortlist_is_global_top_k_and_counts_full_domain(self):
        space = space_for(threat_root())
        def rank(command):
            return 12 if command["card"] == "fi" else 5 if command["card"] == "h" else 0
        plans = list(space.iter_plans())
        expected = sorted(plans, key=lambda plan: (-sum(rank(p.command()) for p in plan), plan))[:7]
        selected, count = space.ranked_bundles(rank, 7)
        self.assertEqual(count, len(plans))
        self.assertEqual(selected, tuple(tuple(p.command() for p in plan) for plan in expected))

    def test_joint_rank_can_prioritize_low_individual_value_conjunction(self):
        space = space_for(threat_root())
        desired = {("fm", "worker"), ("h", "girl"), ("h", "maiden")}
        selected, count = space.ranked_bundles(
            lambda p: 100 if p["card"] == "g2" else 0, 1,
            joint_rank=lambda plan: (int(desired.issubset({p.effect for p in plan})),
                                     -sum(p.card in {"fm", "p-1", "g2"} for p in plan)))
        self.assertEqual({(p["card"], p["target"]) for p in selected[0]}, desired)
        self.assertGreater(count, 10000)

    def test_unsupported_rules_and_permission_shapes_are_explicit(self):
        game = threat_root()
        view = game.protagonist_team_view()
        offers = game.search_actions(game.controller)
        for change in (lambda v: v.update(module="WM"),
                       lambda v: v["characters"]["doctor"].update(echo_board_actions=True),
                       lambda v: v["team_hands"].pop("b")):
            modified = deepcopy(view)
            change(modified)
            with self.assertRaises(UnsupportedJointSpace):
                JointActionSpace(modified, offers)
        with self.assertRaises(UnsupportedJointSpace):
            JointActionSpace(view, offers[:-1])

    def test_opt_in_oracle_matches_full_engine_reference_on_partial_root(self):
        from benchmarks.ai_self_play import _policy_offer
        game = threat_root()
        game.dispatch("a", "play", card="g1", target="school")
        game.dispatch("b", "play", card="g1", target="city")
        view = game.protagonist_team_view()
        known_view = deepcopy(view)
        faces = {p.target: p.card for p in game.state.pending if p.actor == "m"}
        for p in known_view["pending"]:
            if p["actor"] == "m":
                p["card"] = faces[p["target"]]
        space = JointActionSpace(known_view, game.search_actions(game.controller))
        agent = FullCardOracleProtagonistAgent(SearchBudget(node_limit=256), candidate_policy="joint_enumeration")
        choices = []
        for plan in space.iter_plans():
            after = ParticleEnsembleProtagonistAgent._apply_bundle(game, tuple(p.command() for p in plan))
            value, alive, *_ = agent._rollout_score(after, view["loop"], view["round"])
            value -= 0.025 * sum(p.card in {"fm", "g2", "p-1"} for p in plan)
            choices.append((alive, value))
        before = deepcopy(game.view("m"))
        offers = [_policy_offer(game, a) for a in game.action_offers(game.controller)]
        chosen = agent.choose_game_action(participant="team", game=game, offers=offers, public_view=view)
        trace = agent.last_trace
        self.assertEqual(trace.enumerated_bundles, len(choices))
        self.assertEqual(trace.evaluated_bundles, len(choices))
        after = ParticleEnsembleProtagonistAgent._apply_bundle(game, trace.selected_bundle)
        value, alive, *_ = agent._rollout_score(after, view["loop"], view["round"])
        value -= 0.025 * sum(p["card"] in {"fm", "g2", "p-1"} for p in trace.selected_bundle)
        self.assertEqual((alive, value), max(choices))
        self.assertIn(chosen, offers)
        self.assertEqual(game.view("m"), before)

    def test_opt_in_oracle_reports_unsupported_fallback(self):
        from benchmarks.ai_self_play import _policy_offer
        game = threat_root()
        game.state.characters["doctor"].echo_board_actions = True
        agent = FullCardOracleProtagonistAgent(SearchBudget(node_limit=2), candidate_policy="joint_enumeration")
        agent.choose_game_action(participant="team", game=game,
                                 offers=[_policy_offer(game, a) for a in game.action_offers(game.controller)])
        self.assertIn("echo", agent.last_trace.joint_space_fallback)
        self.assertEqual(agent.last_trace.enumerated_bundles, 0)

    def test_blind_oracle_passes_only_dark_faces_to_shared_space(self):
        from benchmarks.ai_self_play import _policy_offer
        game = threat_root()
        view = game.protagonist_team_view()
        captured = []
        def capture(observation, offers):
            captured.append(deepcopy(observation))
            return JointActionSpace(observation, offers)
        offers = [_policy_offer(game, a) for a in game.action_offers(game.controller)]
        agent = HiddenCardOracleProtagonistAgent(SearchBudget(node_limit=2), candidate_policy="joint_enumeration")
        with patch("tragedy_sim.joint_action_space.JointActionSpace", side_effect=capture):
            agent.choose_game_action(participant="team", game=game, public_view=view, offers=offers)
        self.assertEqual(captured, [view])
        self.assertTrue(all(p["card"] is None for p in captured[0]["pending"] if p["actor"] == "m"))

    def test_oracle_policy_settings_are_explicit_and_reject_wrong_agents(self):
        from benchmarks.ai_self_play import play
        for invalid in (True, [], "greedy"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                FullCardOracleProtagonistAgent(candidate_policy=invalid)
        with self.assertRaisesRegex(ValueError, "oracle protagonist"):
            play("official-fs-01-first-script", 0, 2, 4, "joint",
                 protagonist_strategy="particle_ensemble", oracle_candidate_policy="joint_enumeration")

    def test_numeric_noop_does_not_prove_virus_role_mutation_noop(self):
        from tragedy_sim import Game
        from tragedy_sim.scenario_library import ScenarioLibrary
        game = Game(ScenarioLibrary().get("official-btx-09-those-with-antibodies"))
        while game.state.phase != "protagonists":
            game = game.search_transition(game.search_actions(game.controller)[0])
        # Counter mutation scans globally, even on a different zero-valued
        # target. This fixture exercises the missing invariant explicitly.
        ordinary = next(cid for cid, role in game.roles.items() if role == "ordinary")
        game.state.characters[ordinary].paranoia = 3
        zero = next(c for c in game.state.characters if c != ordinary)
        game.state.characters[zero].paranoia = 0
        game._change(zero, "paranoia", -1)
        self.assertEqual(game.roles[ordinary], "serial")
        self.assertEqual(game.state.characters[zero].paranoia, 0)
        with self.assertRaisesRegex(UnsupportedJointSpace, "mutation invariants"):
            space_for(game)

    def test_deadline_finishes_one_common_batch_instead_of_repeated_partial_rows(self):
        from benchmarks.ai_self_play import _policy_offer
        game = threat_root()
        agent = HiddenCardOracleProtagonistAgent(SearchBudget(node_limit=2, time_limit_ms=1))
        worlds = tuple(game.search_clone() for _ in range(3))
        clock = iter(range(100))
        with patch.object(agent, "_worlds", return_value=worlds), \
                patch.object(agent, "_rollout_score", return_value=(0.1, True, 1, False)) as rollout, \
                patch("tragedy_sim.oracle_protagonist.perf_counter", side_effect=lambda: next(clock)):
            agent.choose_game_action(participant="team", game=game,
                                     offers=[_policy_offer(game, a) for a in game.action_offers(game.controller)])
        self.assertEqual(rollout.call_count, 3)
        self.assertEqual(agent.last_trace.evaluated_bundles, 1)
        self.assertEqual(agent.last_trace.survivals, 3)

    def test_invalid_world_does_not_turn_partial_scores_into_full_survival(self):
        from benchmarks.ai_self_play import _policy_offer
        game = threat_root()
        bad = game.search_clone()
        bad.state.hands["b"].remove("g1")
        bundle = ({"actor": "a", "action": "play", "card": "fi", "target": "shrine"},
                  {"actor": "b", "action": "play", "card": "g1", "target": "doctor"},
                  {"actor": "c", "action": "play", "card": "g1", "target": "girl"})
        agent = HiddenCardOracleProtagonistAgent(SearchBudget(node_limit=1))
        offers = [_policy_offer(game, a) for a in game.action_offers(game.controller)]
        with patch.object(agent, "_worlds", return_value=(game.search_clone(), bad)), \
                patch.object(agent, "_bundle", return_value=bundle), \
                patch.object(agent, "_rollout_score", return_value=(0.1, True, 1, False)):
            chosen = agent.choose_game_action(participant="team", game=game, offers=offers)
        self.assertIn(chosen, offers)
        self.assertIsNone(agent.last_trace)


if __name__ == "__main__":
    unittest.main()
