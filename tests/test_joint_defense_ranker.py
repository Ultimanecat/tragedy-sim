"""Card projection is checked against settlement; ranking is only heuristic."""

from copy import deepcopy
import random
import unittest

from tests.test_dark_attack_scenarios import threat_root
from tragedy_sim import Game
from tragedy_sim.belief_dark_constraints import dark_card_domains
from tragedy_sim.dark_attack_scenarios import marginal_dark_worlds, with_dark_bundle
from tragedy_sim.engine import Placement
from tragedy_sim.joint_action_space import JointActionSpace
from tragedy_sim.joint_defense_ranker import BOARDS, CardProjectionModel, JointThreatRanker
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.oracle_protagonist import FullCardOracleProtagonistAgent, HiddenCardOracleProtagonistAgent
from tragedy_sim.search import SearchBudget


def known_space(game):
    view = game.protagonist_team_view()
    faces = {p.target: p.card for p in game.state.pending if p.actor == "m"}
    for p in view["pending"]:
        if p["actor"] == "m":
            p["card"] = faces[p["target"]]
    return JointActionSpace(view, game.search_actions(game.controller))


class JointDefenseRankerTests(unittest.TestCase):
    def test_marginal_probes_cover_every_supported_slot_face(self):
        game = threat_root()
        game.dispatch("a", "play", card="g1", target="doctor")
        view = game.protagonist_team_view()
        view["pending"][0]["card"] = "h"
        before = deepcopy(game.view("m"))
        _, domains, _ = dark_card_domains(view)
        worlds = marginal_dark_worlds(game, view)
        self.assertLessEqual(len(worlds), sum(map(len, domains.values())))
        signatures = []
        for world in worlds:
            black = [p for p in world.state.pending if p.actor == "m"]
            signatures.append(tuple(p.card for p in black))
            self.assertEqual(len({p.card for p in black}), 3)
            self.assertEqual(black[0].card, "h")
            self.assertNotIn("i2", signatures[-1])
            self.assertEqual([p for p in world.state.pending if p.actor != "m"],
                             [p for p in game.state.pending if p.actor != "m"])
        self.assertEqual(len(signatures), len(set(signatures)))
        for slot, faces in domains.items():
            self.assertEqual({row[int(slot)] for row in signatures}, set(faces))
        self.assertEqual(game.view("m"), before)

    def test_projection_matches_engine_on_sampled_fs_btx_card_plans(self):
        library = ScenarioLibrary()
        for sid in ("official-fs-01-first-script", "official-tragic-aiplay-fs-02g",
                    "official-btx-04-young-womens-battlefield", "official-btx-06-secret-that-was-kept",
                    "community-tragic-aiplay-btx-41", "community-tragic-aiplay-btx-45"):
            game = Game(library.get(sid))
            while game.state.phase != "protagonists":
                game = game.search_transition(game.search_actions(game.controller)[0])
            before = deepcopy(game.view("m"))
            space = known_space(game)
            model = CardProjectionModel(game, space)
            plans = list(space.iter_plans())
            for plan in random.Random(0).sample(plans, 16):
                with self.subTest(scenario=sid, plan=plan):
                    projected = model.project(plan, adversarial_cultists=False)
                    after = ParticleEnsembleProtagonistAgent._apply_bundle(game, tuple(p.command() for p in plan))
                    after.resolve()
                    after._resolve_counters()
                    self.assertEqual(projected.locations[:model.n],
                                     tuple(BOARDS.index(after.state.characters[cid].location) for cid in model.ids))
                    for counter in ("paranoia", "goodwill", "intrigue"):
                        expected = tuple(getattr(after.state.characters[cid], counter) for cid in model.ids)
                        if counter == "intrigue":
                            expected += tuple(after.state.locations[b] for b in BOARDS)
                        else:
                            expected += (0,) * 4
                        self.assertEqual(getattr(projected, counter), expected)
                    self.assertEqual(projected.roles, tuple(after.roles[cid] for cid in model.ids))
            self.assertEqual(game.view("m"), before)

    def test_joint_ranking_keeps_resource_owners_and_input_immutable(self):
        game = with_dark_bundle(threat_root(), (Placement("m", "h", "girl"),
                                                Placement("m", "v", "worker"), Placement("m", "i1", "shrine")))
        before = deepcopy(game.view("m"))
        space = known_space(game)
        ranker = JointThreatRanker((game,), space)
        bundles, count = space.ranked_bundles(lambda _: 0, 4, joint_rank=ranker, distinct_effects=True)
        self.assertGreater(count, 10000)
        self.assertEqual(len(bundles), 4)
        for bundle in bundles:
            self.assertIsNotNone(ParticleEnsembleProtagonistAgent._apply_bundle(game, bundle))
        self.assertGreater(ranker.projections, 0)
        self.assertEqual(game.view("m"), before)

    def test_small_shortlist_survives_all_script_policy_routes_in_missed_root(self):
        from benchmarks.ai_self_play import _policy_offer
        game = with_dark_bundle(threat_root(), (Placement("m", "h", "girl"),
                                                Placement("m", "v", "worker"), Placement("m", "i1", "shrine")))
        offers = [_policy_offer(game, a) for a in game.action_offers(game.controller)]
        for cls in (FullCardOracleProtagonistAgent, HiddenCardOracleProtagonistAgent):
            with self.subTest(agent=cls.__name__):
                agent = cls(SearchBudget(node_limit=4), candidate_policy="joint_threat")
                chosen = agent.choose_game_action(participant="team", game=game, offers=offers)
                self.assertIn(chosen, offers)
                trace = agent.last_trace
                self.assertEqual(trace.survivals, trace.scenarios)
                self.assertEqual(trace.evaluated_bundles, 4)
                self.assertGreater(trace.policy_rollouts, 4)
                after = ParticleEnsembleProtagonistAgent._apply_bundle(game, trace.selected_bundle)
                for route in agent._mastermind_strategy_options(game):
                    self.assertTrue(agent._day_score(after, 2, 3, mastermind_strategy=route)[1])

    def test_hidden_threat_path_is_independent_of_true_dark_faces(self):
        from benchmarks.ai_self_play import _policy_offer
        a = threat_root()
        b = with_dark_bundle(a, (Placement("m", "v", "girl"), Placement("m", "i1", "worker"),
                                Placement("m", "h", "shrine")))
        b.state.events = deepcopy(a.state.events)
        self.assertEqual(a.protagonist_team_view(), b.protagonist_team_view())
        agents = [HiddenCardOracleProtagonistAgent(SearchBudget(node_limit=1), candidate_policy="joint_threat")
                  for _ in range(2)]
        for game, agent in zip((a, b), agents):
            agent.choose_game_action(participant="team", game=game,
                                     offers=[_policy_offer(game, x) for x in game.action_offers(game.controller)])
        self.assertEqual(agents[0].last_trace.selected_bundle, agents[1].last_trace.selected_bundle)
        self.assertEqual(agents[0].last_trace.scenarios, agents[1].last_trace.scenarios)

    def test_effect_dedup_retains_limited_card_owner(self):
        from tragedy_sim.joint_action_space import DefenseRequirement
        game = threat_root()
        space = known_space(game)
        requirement = DefenseRequirement(((("fm", "girl"),),), "owner_test")
        bundles, _ = space.ranked_bundles(lambda _: 0, 1000, requirements=(requirement,), distinct_effects=True)
        owners = {next(p["actor"] for p in bundle if p["card"] == "fm" and p["target"] == "girl")
                  for bundle in bundles}
        self.assertEqual(owners, {"a", "b", "c"})

    def test_oracle_summary_counts_action_wins_separately_from_final_answers(self):
        from benchmarks.ai_oracle_defense_validation import summarize
        rows = [{"scenario": "btx", "seed": 0, "variant": policy, "winner": "protagonists",
                 "action_win": policy == "joint_threat"} for policy in ("legacy", "joint_threat")]
        summary = summarize(rows)
        self.assertEqual(summary["per_scenario"]["btx"]["improved"], 1)


if __name__ == "__main__":
    unittest.main()
