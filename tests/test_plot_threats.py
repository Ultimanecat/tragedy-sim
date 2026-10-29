"""Posterior rule-Y threats from hidden plots (long-horizon target plan)."""

import unittest
from types import SimpleNamespace

from tragedy_sim.composition import BeliefSnapshot
from tragedy_sim.day_game.threats import classify_plot_threats

VIEW = {
    "round": 3,
    "days": 5,
    "locations": {"school": 1, "shrine": 0, "city": 2, "hospital": 0},
    "characters": {
        "brain": {"initial_location": "city"},
        "witch": {"initial_location": "hospital"},
    },
}


def snapshot(plots):
    worlds = [SimpleNamespace(
        main_plot=plot,
        roles={"brain": "brain", "witch": "witch", "girl": "key"},
    ) for plot in plots]
    return BeliefSnapshot(worlds, None)  # type: ignore[arg-type]


def materialized_snapshot(plots):
    """Determinized worlds are Game objects: plot/roles live on .scenario."""
    worlds = [SimpleNamespace(
        scenario={"main_plot": plot,
                  "cast": {"brain": "brain", "witch": "witch", "girl": "key"}},
        roles={"brain": "brain", "witch": "witch", "girl": "key"},
    ) for plot in plots]
    return BeliefSnapshot(worlds, None)  # type: ignore[arg-type]


class PlotThreatTests(unittest.TestCase):
    def test_board_rule_target_and_confidence(self):
        threats = classify_plot_threats(
            view=VIEW, snapshot=snapshot(["protect", "protect", "sealed"]))
        by_target = {item.target: item for item in threats}
        self.assertAlmostEqual(by_target["school"].confidence, 2 / 3)
        self.assertAlmostEqual(by_target["shrine"].confidence, 1 / 3)
        self.assertEqual(by_target["school"].deadline, 5)
        self.assertEqual(by_target["school"].source, "posterior_plot")
        self.assertFalse(by_target["school"].hard)

    def test_role_board_target_uses_initial_location(self):
        threats = classify_plot_threats(
            view=VIEW, snapshot=snapshot(["avenger", "bomb"]))
        by_plot = {item.role: item for item in threats}
        self.assertEqual(by_plot["avenger"].target, "city")
        self.assertEqual(by_plot["bomb"].target, "hospital")

    def test_active_when_board_counter_reaches_threshold(self):
        threats = classify_plot_threats(
            view=VIEW, snapshot=snapshot(["avenger"]))
        avenger = next(item for item in threats if item.role == "avenger")
        self.assertTrue(avenger.active_now)  # city already has 2 intrigue

    def test_character_rule_resolves_to_holder(self):
        threats = classify_plot_threats(
            view=VIEW, snapshot=snapshot(["ll_treacherous_world"]))
        self.assertEqual(len(threats), 1)
        self.assertEqual(threats[0].target, "girl")
        self.assertEqual(threats[0].failure_kind, "plot_loss")

    def test_materialized_game_worlds_are_supported(self):
        threats = classify_plot_threats(
            view=VIEW, snapshot=materialized_snapshot(["sealed"]))
        self.assertEqual([item.target for item in threats], ["shrine"])

    def test_unknown_plot_and_missing_snapshot_yield_nothing(self):
        self.assertEqual(classify_plot_threats(
            view=VIEW, snapshot=snapshot(["murder_plan"])), ())
        self.assertEqual(classify_plot_threats(
            view=VIEW, snapshot=None), ())


if __name__ == "__main__":
    unittest.main()
