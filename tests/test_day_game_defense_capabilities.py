"""Ability defense chain tests."""

import unittest

from tragedy_sim.day_game.defense_capabilities import (
    build_day_ability_plan, counter_reduction_capabilities, find_ability_option,
    plan_counter_defense, scenario_capabilities, schedule_ability_steps)
from tragedy_sim import Game
from tragedy_sim.scenario_library import ScenarioLibrary


def btx01():
    return ScenarioLibrary().get("official-btx-01-machina-solar-cogwheel")


def view(**characters):
    return {"characters": characters}


class DefenseCapabilityTests(unittest.TestCase):
    def test_btx01_has_forensic_transfer(self):
        capabilities = counter_reduction_capabilities(btx01())
        transfers = [item for item in capabilities if item.kind == "transfer"]
        self.assertTrue(any(item.actor == "forensic" for item in transfers))

    def test_plan_sets_up_goodwill_movement_and_transfer(self):
        plan = plan_counter_defense(
            btx01(),
            view(forensic={"alive": True, "present": True, "location": "city",
                           "goodwill": 0, "paranoia_limit": 3},
                 rich={"alive": True, "present": True, "location": "school",
                       "paranoia": 2, "paranoia_limit": 1},
                 class_rep={"alive": True, "present": True, "location": "school",
                            "paranoia": 0, "paranoia_limit": 2},
                 outsider={"alive": True, "present": True, "location": "school",
                           "paranoia": 0, "paranoia_limit": 2}),
            target="rich", need=2)
        self.assertIsNotNone(plan.capability)
        kinds = [step.kind for step in plan.steps]
        self.assertIn("setup_goodwill", kinds)
        self.assertIn("move", kinds)
        self.assertIn("use_transfer", kinds)

    def test_ready_forensic_needs_only_transfer(self):
        plan = plan_counter_defense(
            btx01(),
            view(forensic={"alive": True, "present": True, "location": "school",
                           "goodwill": 2},
                 rich={"alive": True, "present": True, "location": "school",
                       "paranoia": 1, "paranoia_limit": 1},
                 class_rep={"alive": True, "present": True, "location": "school",
                            "paranoia": 0, "paranoia_limit": 2},
                 outsider={"alive": True, "present": True, "location": "school",
                           "paranoia": 0, "paranoia_limit": 2}),
            target="rich", need=1)
        self.assertEqual([step.kind for step in plan.steps], ["use_transfer"])

    def test_fs_scenario_has_no_transfer_chain(self):
        scenario = ScenarioLibrary().get("official-fs-01-first-script")
        plan = plan_counter_defense(
            scenario,
            view(rich={"alive": True, "present": True, "location": "school",
                       "paranoia": 1}),
            target="rich", need=1)
        self.assertIsNone(plan.capability)
        self.assertIn("no transfer", plan.blocked_reason or "")

    def test_capability_plan_becomes_legal_three_card_plan(self):
        scenario = btx01()
        view_ = view(
            forensic={"alive": True, "present": True, "location": "city",
                      "goodwill": 0},
            rich={"alive": True, "present": True, "location": "school",
                  "paranoia": 2, "paranoia_limit": 1},
            class_rep={"alive": True, "present": True, "location": "school",
                       "paranoia": 0, "paranoia_limit": 2},
            outsider={"alive": True, "present": True, "location": "school",
                      "paranoia": 0, "paranoia_limit": 2},
        )

        class FakeWorld:
            controller = "a"

            def legal_actions(self, actor):
                return [
                    {"actor": "a", "action": "play", "card": "g2", "target": "forensic"},
                    {"actor": "a", "action": "play", "card": "h", "target": "forensic"},
                    {"actor": "a", "action": "play", "card": "g1", "target": "class_rep"},
                    {"actor": "a", "action": "play", "card": "p1", "target": "outsider"},
                ]

        plan = plan_counter_defense(scenario, view_, target="rich", need=2)
        scheduled = schedule_ability_steps(plan)
        from dataclasses import replace
        day_plan = build_day_ability_plan(
            FakeWorld(), replace(plan, steps=scheduled.days[0]))
        self.assertIsNone(day_plan.blocked_reason)
        self.assertEqual(len(day_plan.card_plan), 3)
        self.assertEqual(day_plan.card_plan[0]["card"], "g2")
        second = build_day_ability_plan(
            FakeWorld(), replace(plan, steps=scheduled.days[1]))
        self.assertIsNone(second.blocked_reason)
        self.assertIsNotNone(second.effect)
        self.assertEqual(second.effect.source, "rich")

    def test_capability_steps_split_across_days(self):
        scenario = btx01()
        view_ = view(
            forensic={"alive": True, "present": True, "location": "city",
                      "goodwill": 0},
            rich={"alive": True, "present": True, "location": "school",
                  "paranoia": 2, "paranoia_limit": 1},
            class_rep={"alive": True, "present": True, "location": "school",
                       "paranoia": 0, "paranoia_limit": 2},
            outsider={"alive": True, "present": True, "location": "school",
                      "paranoia": 0, "paranoia_limit": 2},
        )
        plan = plan_counter_defense(scenario, view_, target="rich", need=2)
        scheduled = schedule_ability_steps(plan)
        self.assertIsNone(scheduled.blocked_reason)
        self.assertEqual(len(scheduled.days), 2)
        for day in scheduled.days:
            targets = [step.target for step in day
                       if step.kind in {"setup_goodwill", "move"}]
            self.assertEqual(len(targets), len(set(targets)))
        self.assertEqual(scheduled.days[-1][-1].kind, "use_transfer")

    def test_find_ability_option_matches_transfer_source_and_sink(self):
        class FakeGame:
            controller = "a"

            def options(self, actor):
                return [
                    {"effects": [{"kind": "counter", "target": "rich"}]},
                    {"effects": [{"kind": "transfer", "source": "rich",
                                  "target": "class_rep"}]},
                ]

        option = find_ability_option(
            FakeGame(), effect_kind="transfer", source="rich", sink="class_rep")
        self.assertEqual(option, {"actor": "a", "action": "choose", "index": 2})

    def test_real_engine_transfer_moves_paranoia_off_rich(self):
        game = Game(btx01())
        for _ in range(120):
            if game.state.phase == "goodwill":
                break
            actions = game.legal_actions(game.controller)
            action = next((item for item in actions
                           if item.get("action") == "next"), actions[0])
            game = game.transition(action).game
        self.assertEqual(game.state.phase, "goodwill")
        for cid in ("forensic", "rich", "class_rep", "outsider"):
            game.state.characters[cid].location = "school"
            game.state.characters[cid].present = True
            game.state.characters[cid].alive = True
        game.state.characters["forensic"].goodwill = 2
        game.state.characters["rich"].paranoia = 2
        game.state.characters["class_rep"].paranoia = 0
        option = find_ability_option(
            game, effect_kind="transfer", source="rich", sink="class_rep")
        self.assertIsNotNone(option)
        pending = game.transition(option).game
        self.assertEqual(pending.state.phase, "refusal")
        accept = find_ability_option(
            pending, effect_kind="transfer", source="rich", sink="class_rep")
        self.assertIsNotNone(accept)
        after = pending.transition(accept).game
        self.assertEqual(after.state.characters["rich"].paranoia, 1)
        self.assertEqual(after.state.characters["class_rep"].paranoia, 1)


if __name__ == "__main__":
    unittest.main()
