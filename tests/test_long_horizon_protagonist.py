"""TwoDayProtagonistAgent v1: rule-Y obligation defense tests."""

import unittest
from types import SimpleNamespace

from tragedy_sim.day_game.protagonist import (DefenseObligation,
                                              PLOT_THRESHOLDS,
                                              TwoDayProtagonistAgent, _cover_targets,
                                              _counter_for)
from tragedy_sim.day_game.threats import ThreatAssessment


def plot_threat(target="city", plot="avenger", confidence=1.0):
    return ThreatAssessment(
        target=target, failure_kind="plot_loss", role=plot,
        confidence=confidence, severity=1.0, deadline=4,
        active_now=False, source="posterior_plot", hard=False)


def view(**locations):
    counters = {name: {"intrigue": value} for name, value in locations.items()}
    return {"module": "FS", "phase": "protagonists", "loop": 1, "round": 3,
            "days": 4, "locations": counters, "characters": {}}


def offer(card, target, actor="a"):
    return {"id": f"{actor}:{card}:{target}", "actor": actor, "type": "play",
            "parameters": {"card": card, "target": target}}


class FakeBase:
    def __init__(self, pick):
        self.pick = pick
        self.calls = 0

    def choose_action(self, *, participant, view, offers):
        self.calls += 1
        return self.pick


def agent_with(pick, obligations):
    base = FakeBase(pick)
    agent = TwoDayProtagonistAgent(base=base)
    agent._context_key = (1, 3)
    agent._obligations = tuple(obligations)
    agent._threats = tuple(item.threat for item in obligations)
    agent._snapshot = None
    return agent, base


class CoverTargetTests(unittest.TestCase):
    def test_only_forbid_intrigue_covers_accumulation(self):
        self.assertEqual(_cover_targets(offer("fi", "school")), frozenset({"school"}))
        self.assertEqual(_cover_targets(offer("p-1", "girl")), frozenset())
        self.assertEqual(_cover_targets(offer("h", "girl")), frozenset())
        self.assertEqual(_cover_targets({"type": "next"}), frozenset())

    def test_counter_reads_board_or_character(self):
        data = view(city=2)
        data["characters"] = {"girl": {"intrigue": 1}}
        self.assertEqual(_counter_for(plot_threat(target="city"), data), 2)
        self.assertEqual(_counter_for(plot_threat(target="girl", plot="sign"), data), 1)


class ObligationTests(unittest.TestCase):
    def obligation(self, counter, days_left=2, threshold=2):
        return DefenseObligation(threat=plot_threat(), counter=counter,
                                 threshold=threshold, days_left=days_left)

    def test_weight_rises_with_deadline_and_margin(self):
        # A 0-count board is a blind guess while rule Y is hidden.
        self.assertEqual(self.obligation(0).weight, 0.0)
        self.assertEqual(self.obligation(1, days_left=3).weight, 1.0)  # margin zero
        self.assertAlmostEqual(self.obligation(1, days_left=3, threshold=3).weight, 0.5)
        self.assertAlmostEqual(self.obligation(1, days_left=2, threshold=3).weight, 0.7)
        self.assertAlmostEqual(self.obligation(1, days_left=1, threshold=3).weight, 0.9)
        self.assertEqual(self.obligation(2).weight, 0.0)  # already lost
        forced = DefenseObligation(threat=plot_threat(), counter=0,
                                   threshold=2, days_left=3, forced=True)
        self.assertAlmostEqual(forced.weight, 0.9)

    def test_last_day_single_counter_is_urgent(self):
        self.assertEqual(self.obligation(1, days_left=0).weight, 1.0)
        self.assertTrue(self.obligation(1, days_left=0).urgent)

    def test_thresholds_are_two_for_supported_plots(self):
        self.assertTrue(PLOT_THRESHOLDS)
        self.assertTrue(all(value == 2 for value in PLOT_THRESHOLDS.values()))


class ChooseActionTests(unittest.TestCase):
    def test_defends_board_when_one_more_increment_loses_loop(self):
        base_pick = offer("g1", "girl")
        agent, base = agent_with(
            base_pick, [DefenseObligation(plot_threat("city"), 1, 2, 1)])
        chosen = agent.choose_action(
            participant="team",
            view=view(city=1, school=0),
            offers=[offer("fi", "city"), offer("fi", "school"), base_pick])
        self.assertEqual(chosen["parameters"]["card"], "fi")
        self.assertEqual(chosen["parameters"]["target"], "city")

    def test_falls_back_when_no_obligation(self):
        base_pick = offer("g1", "girl")
        agent, _ = agent_with(base_pick, [])
        chosen = agent.choose_action(
            participant="team", view=view(city=0),
            offers=[offer("fi", "city"), base_pick])
        self.assertIs(chosen, base_pick)

    def test_does_not_defend_already_lost_board(self):
        base_pick = offer("g1", "girl")
        agent, _ = agent_with(
            base_pick, [DefenseObligation(plot_threat("city"), 2, 2, 1)])
        chosen = agent.choose_action(
            participant="team", view=view(city=2),
            offers=[offer("fi", "city"), base_pick])
        self.assertIs(chosen, base_pick)

    def test_non_play_offers_use_base(self):
        base_pick = {"id": "next", "actor": "a", "type": "next"}
        agent, _ = agent_with(base_pick, [])
        offers = [base_pick]
        chosen = agent.choose_action(participant="team", view=view(city=1),
                                     offers=offers)
        self.assertIs(chosen, base_pick)


if __name__ == "__main__":
    unittest.main()
