"""Scenario-conditioned evaluation tests for every recorded FS/BTX script."""

from copy import deepcopy
import math
import random
import unittest

from tragedy_sim import Game
from tragedy_sim.catalog import CHARACTERS
from tragedy_sim.evaluation import ScenarioConditionedEvaluator
from tragedy_sim.scenario import example_scenario, validate_scenario
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.search import MastermindEvaluator, SearchBudget
from tragedy_sim.optimized_mcts import OptimizedMctsMastermindAgent


def contribution(report, prefix):
    return next((item for item in report.contributions
                 if item.key.startswith(prefix)), None)


def synthetic_avenger_hideous():
    scenario = example_scenario("FS")
    scenario.update(id="test-fs-avenger-hideous", title="test",
                    main_plot="avenger", subplots=["hideous"])
    characters = list(scenario["cast"])
    scenario["cast"] = dict.fromkeys(characters, "ordinary")
    scenario["cast"].update({
        characters[0]: "brain", characters[1]: "conspiracy",
        characters[2]: "friend",
    })
    return validate_scenario(scenario)


class ScenarioEvaluationContextTests(unittest.TestCase):
    def test_all_recorded_fs_btx_scripts_compile_and_are_cached(self):
        library = ScenarioLibrary()
        scripts = [library.get(item["id"]) for item in library.list()
                   if item["module"] in {"FS", "BTX"} and item["source"] == "library"]
        self.assertEqual(sum(item["module"] == "FS" for item in scripts), 2)
        self.assertEqual(sum(item["module"] == "BTX" for item in scripts), 11)
        evaluator = ScenarioConditionedEvaluator()
        for script in scripts:
            with self.subTest(script=script["id"]):
                game = Game(script)
                first = evaluator.context_for(script)
                second = evaluator.context_for(deepcopy(script))
                self.assertIs(first, second)
                report = evaluator.evaluate(game)
                self.assertEqual(report.context_key, first.key)
                self.assertTrue(math.isfinite(report.value))
                self.assertTrue(-0.92 <= report.value <= 0.92)
        self.assertEqual(len(evaluator._contexts), len(scripts))

    def test_unmigrated_ruleset_uses_explicit_fallback(self):
        game = Game(example_scenario("MZ"))
        evaluator = ScenarioConditionedEvaluator()
        report = evaluator.evaluate(game)
        self.assertEqual(report.value, MastermindEvaluator()(game))
        self.assertEqual(report.contributions[0].key, "fallback")


class MainPlotEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.library = ScenarioLibrary()
        self.evaluator = ScenarioConditionedEvaluator()

    def _script_with_main(self, main):
        if main == "avenger":
            return synthetic_avenger_hideous()
        return next(self.library.get(item["id"]) for item in self.library.list()
                    if item["module"] in {"FS", "BTX"}
                    and item["source"] == "library"
                    and self.library.get(item["id"])["main_plot"] == main)

    def test_every_fs_btx_main_plot_has_correct_threshold_direction(self):
        for main in ("protect", "avenger", "sealed", "sign", "bomb"):
            with self.subTest(main=main):
                game = Game(self._script_with_main(main))
                if main == "protect":
                    target = (game.state.locations, "school")
                elif main == "sealed":
                    target = (game.state.locations, "shrine")
                elif main in {"avenger", "bomb"}:
                    role = "brain" if main == "avenger" else "witch"
                    cid = next(cid for cid, assigned in game.roles.items()
                               if assigned == role)
                    target = (game.state.locations,
                              dict(self.evaluator.context_for(game.scenario).initial_locations)[cid])
                else:
                    cid = next(cid for cid, assigned in game.roles.items()
                               if assigned == "key")
                    target = (game.state.characters[cid], "intrigue")
                values = []
                for amount in (0, 1, 2):
                    if isinstance(target[0], dict):
                        target[0][target[1]] = amount
                    else:
                        setattr(target[0], target[1], amount)
                    item = contribution(self.evaluator.evaluate(game), f"plot:{main}")
                    values.append(0.0 if item is None else item.value)
                self.assertLess(values[0], values[1])
                self.assertLess(values[1], values[2])
                self.assertGreater(values[2] - values[1], values[1] - values[0])

    def test_change_uses_observed_butterfly_occurrence_not_raw_counters(self):
        game = Game(self._script_with_main("change"))
        before = self.evaluator(game)
        game.incident_records.append({
            "day": 1, "kind": "butterfly", "happened": True, "effective": False})
        after = self.evaluator(game)
        item = contribution(self.evaluator.last_report, "plot:change")
        self.assertIsNotNone(item)
        self.assertEqual(item.progress, 1.0)
        self.assertGreater(after, before + 0.4)

    def test_murder_plan_has_no_invented_plot_loss_route(self):
        game = Game(self._script_with_main("murder_plan"))
        report = self.evaluator.evaluate(game)
        self.assertIsNone(contribution(report, "plot:murder_plan"))


class RoleAndIncidentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.library = ScenarioLibrary()
        self.evaluator = ScenarioConditionedEvaluator()

    def test_killer_threshold_and_key_position_are_non_linear(self):
        game = Game(example_scenario("BTX"))
        killer = game.state.characters["worker"]
        key = game.state.characters["girl"]
        killer.location = key.location
        direct = []
        assassination = []
        for amount in (0, 1, 2, 3, 4):
            killer.intrigue = amount
            direct.append(contribution(
                self.evaluator.evaluate(game), "role:killer_direct").value
                          if amount else 0.0)
        for amount in (0, 1, 2):
            key.intrigue = amount
            item = contribution(self.evaluator.evaluate(game), "role:killer_key")
            assassination.append(0.0 if item is None else item.value)
        self.assertGreater(direct[4] - direct[3], direct[3] - direct[2])
        self.assertGreater(assassination[2] - assassination[1],
                           assassination[1] - assassination[0])
        key.location = "shrine"
        separated = contribution(self.evaluator.evaluate(game), "role:killer_key").value
        self.assertLess(separated, assassination[2] / 2)

    def test_friend_lover_time_traveler_factor_and_serial_routes(self):
        checks = {
            "friend": "official-btx-05-lesser-of-two-evils",
            "lover": "official-btx-11-neverending-happy-sad-story",
            "time_traveler": "official-btx-03-future-assassin",
            "factor": "official-btx-08-mirror-passcode",
            "serial": "official-fs-01-first-script",
        }
        for role, scenario_id in checks.items():
            with self.subTest(role=role):
                game = Game(self.library.get(scenario_id))
                cid = next(cid for cid, assigned in game.roles.items()
                           if assigned == role)
                character = game.state.characters[cid]
                if role == "friend":
                    character.alive = False
                    item = contribution(self.evaluator.evaluate(game), "role:friend_dead")
                elif role == "lover":
                    character.paranoia, character.intrigue = 3, 1
                    item = contribution(self.evaluator.evaluate(game), "role:lover")
                elif role == "time_traveler":
                    early = contribution(self.evaluator.evaluate(game), "role:time_traveler").value
                    game.state.round = game.scenario["days"]
                    item = contribution(self.evaluator.evaluate(game), "role:time_traveler")
                    self.assertGreater(item.value, early * 2)
                elif role == "factor":
                    game.state.locations["city"] = 2
                    item = contribution(self.evaluator.evaluate(game), "role:factor_key")
                else:
                    targets = [c for c in game.state.characters.values()
                               if c.id != cid]
                    for target in targets:
                        target.location = "school"
                    character.location = "city"
                    victim = next(c for c in targets
                                  if game.roles[c.id] in {"key", "friend"})
                    victim.location = "city"
                    item = contribution(self.evaluator.evaluate(game), "role:serial")
                self.assertIsNotNone(item)
                self.assertGreater(item.value, 0.15)

    def test_incident_progress_expires_after_its_day(self):
        game = Game(example_scenario("BTX"))
        culprit = game.state.characters["doctor"]
        culprit.paranoia = CHARACTERS["doctor"].limit
        current = contribution(self.evaluator.evaluate(game), "incident:2:murder")
        self.assertIsNotNone(current)
        game.state.round = 3
        expired = contribution(self.evaluator.evaluate(game), "incident:2:murder")
        self.assertIsNone(expired)

    def test_virus_and_threads_value_their_setup_specific_future_effects(self):
        virus = Game(self.library.get("official-btx-08-mirror-passcode"))
        ordinary = next(c for cid, c in virus.state.characters.items()
                        if virus.roles[cid] == "ordinary")
        ordinary.paranoia = 2
        virus_item = contribution(self.evaluator.evaluate(virus), "plot:virus")
        self.assertIsNotNone(virus_item)
        self.assertGreater(virus_item.value, 0)

        threads = Game(self.library.get("official-btx-06-secret-that-was-kept"))
        target = next(iter(threads.state.characters.values()))
        before = contribution(self.evaluator.evaluate(threads), "plot:threads")
        self.assertIsNone(before)
        target.goodwill = 1
        after = contribution(self.evaluator.evaluate(threads), "plot:threads")
        self.assertIsNotNone(after)
        self.assertGreater(after.value, 0)

    def test_terminal_values_are_exact(self):
        game = Game(example_scenario("FS"))
        game.winner = "mastermind"
        self.assertEqual(self.evaluator(game), 1.0)
        game.winner = "protagonists"
        self.assertEqual(self.evaluator(game), -1.0)

    def test_phase_stability_and_loop_pressure_are_explicit(self):
        game = Game(example_scenario("BTX"))
        initial = self.evaluator.evaluate(game)
        self.assertTrue(initial.stable)
        game.state.phase = "mastermind"
        self.assertFalse(self.evaluator.evaluate(game).stable)

        game.state.phase = "day_start"
        game.state.loop = 2
        later = self.evaluator.evaluate(game)
        self.assertGreater(later.value, initial.value)
        self.assertIsNotNone(contribution(later, "match:loops_spent"))
        game.known_roles["girl"] = {"role": "key", "loop": 1, "day": 1}
        informed = self.evaluator.evaluate(game)
        self.assertEqual(informed.value, later.value)
        self.assertIsNone(contribution(informed, "defense:knowledge"))


class RecordedScriptEvaluationWalkTests(unittest.TestCase):
    def test_every_recorded_script_is_bounded_across_reachable_phases(self):
        library = ScenarioLibrary()
        scripts = [library.get(item["id"]) for item in library.list()
                   if item["module"] in {"FS", "BTX"} and item["source"] == "library"]
        for script_index, script in enumerate(scripts):
            with self.subTest(script=script["id"]):
                game = Game(script)
                evaluator = ScenarioConditionedEvaluator()
                rng = random.Random(100 + script_index)
                phases = set()
                for _ in range(600):
                    report = evaluator.evaluate(game)
                    phases.add(game.state.phase)
                    self.assertTrue(math.isfinite(report.value))
                    self.assertTrue(-1 <= report.value <= 1)
                    if game.winner is not None:
                        break
                    actions = game.action_offers(game.controller)
                    self.assertTrue(actions)
                    game = game.transition(rng.choice(actions)).game
                self.assertIsNotNone(game.winner, "evaluation walk did not reach a terminal state")
                self.assertGreaterEqual(len(phases), 3)

    def test_optimized_mcts_uses_new_evaluator_on_every_recorded_script(self):
        library = ScenarioLibrary()
        for item in library.list():
            if item["module"] not in {"FS", "BTX"} or item["source"] != "library":
                continue
            with self.subTest(script=item["id"]):
                game = Game(library.get(item["id"]))
                agent = OptimizedMctsMastermindAgent(
                    SearchBudget(node_limit=3, rollout_depth=2, seed=8))
                chosen = agent.search(game)
                self.assertIn(chosen, game.action_offers("m"))
                self.assertIsInstance(agent.evaluator, ScenarioConditionedEvaluator)


if __name__ == "__main__":
    unittest.main()
