"""TwoDayProtagonistAgent v1: rule-Y obligation defense tests."""

import unittest
from types import SimpleNamespace

from tragedy_sim.composition import BeliefSnapshot
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
    counters = dict(locations)
    return {"module": "FS", "phase": "protagonists", "loop": 1, "round": 3,
            "days": 4, "locations": counters, "characters": {}}


def avenger_snapshot(brain_holder="police", plot="avenger", worlds=8):
    entities = [SimpleNamespace(main_plot=plot,
                                roles={brain_holder: "brain",
                                       "girl": "key"})
                for _ in range(worlds)]
    return BeliefSnapshot(entities, None)  # type: ignore[arg-type]


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


class RelocationTests(unittest.TestCase):
    def agent(self, snapshot, obligation, base_pick):
        agent = TwoDayProtagonistAgent(base=FakeBase(base_pick))
        agent._context_key = (1, 3)
        agent._obligations = (obligation,)
        agent._threats = (obligation.threat,)
        agent._snapshot = snapshot
        agent._covered_today = set()
        return agent

    def test_moving_suspected_brain_off_watched_board_counts_as_defense(self):
        obligation = DefenseObligation(
            plot_threat("school", plot="avenger"), counter=1, threshold=2,
            days_left=3)
        data = view(school=0, city=0)
        data["characters"] = {"police": {"location": "school",
                                         "initial_location": "school"},
                              "girl": {"location": "city",
                                       "initial_location": "city"}}
        move_offer = offer("h", "police")
        base_pick = offer("g1", "girl")
        agent = self.agent(avenger_snapshot(), obligation, base_pick)
        chosen = agent.choose_action(participant="team", view=data,
                                     offers=[base_pick, move_offer])
        self.assertEqual(chosen["parameters"]["card"], "h")
        self.assertEqual(chosen["parameters"]["target"], "police")

    def test_suspect_not_on_watched_board_is_not_moved(self):
        obligation = DefenseObligation(
            plot_threat("school", plot="avenger"), counter=1, threshold=2,
            days_left=3)
        data = view(school=0, city=0)
        data["characters"] = {"police": {"location": "city",
                                         "initial_location": "school"},
                              "girl": {"location": "city",
                                       "initial_location": "city"}}
        move_offer = offer("h", "police")
        base_pick = offer("g1", "girl")
        agent = self.agent(avenger_snapshot(), obligation, base_pick)
        chosen = agent.choose_action(participant="team", view=data,
                                     offers=[base_pick, move_offer])
        self.assertIs(chosen, base_pick)


class DayPlanEvaluationTests(unittest.TestCase):
    class StubWorld:
        def __init__(self, counter=1, lost=False):
            self.counter = counter
            self.lost = lost
            self.loss_reasons = []
            self.winner = None
            self.controller = "a"
            self.state = SimpleNamespace(loop=1, round=2)
            self.commands = []

        def clone(self):
            clone = DayPlanEvaluationTests.StubWorld(self.counter, self.lost)
            clone.commands = list(self.commands)
            return clone

        def transition(self, command):
            self.commands.append(command)
            if command.get("card") == "fi":
                self.counter = max(0, self.counter - 1)
            return SimpleNamespace(game=self)

        def action_offers(self, controller):
            return []

        def protagonist_team_view(self):
            return {"locations": {"school": self.counter},
                    "characters": {"girl": {"alive": True}}}

    def stub_base(self, first_offer, follow):
        base = FakeBase(first_offer)
        base._joint_plan = list(follow)
        return base

    def test_score_plan_prefers_lower_watched_counter(self):
        base = self.stub_base(offer("g1", "girl"), [])
        agent = TwoDayProtagonistAgent(base=base)
        agent._snapshot = None
        risk = DefenseObligation(plot_threat("school", plot="protect"),
                                 counter=1, threshold=2, days_left=2)
        commands = [{"actor": "a", "action": "play", "card": "g1",
                     "target": "girl"},
                    {"actor": "b", "action": "play", "card": "g1",
                     "target": "girl"},
                    {"actor": "c", "action": "play", "card": "g1",
                     "target": "girl"}]
        worlds = [DayPlanEvaluationTests.StubWorld() for _ in range(3)]
        score = agent._score_plan(commands, {}, [risk], worlds)
        self.assertIsNotNone(score)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_variant_chosen_when_it_scores_better(self):
        base_first = offer("g1", "girl")
        better = offer("fi", "school", actor="a")
        base = self.stub_base(base_first, [
            {"actor": "b", "action": "play", "card": "g1", "target": "girl"},
            {"actor": "c", "action": "play", "card": "g1", "target": "girl"}])
        agent = TwoDayProtagonistAgent(base=base)
        agent._context_key = (1, 2)
        risk = DefenseObligation(plot_threat("school", plot="protect"),
                                 counter=1, threshold=2, days_left=2)
        agent._obligations = (risk,)
        agent._threats = (risk.threat,)
        agent._snapshot = SimpleNamespace(worlds=[
            DayPlanEvaluationTests.StubWorld(counter=2) for _ in range(3)])
        agent._refresh = lambda *a, **k: None
        agent._day_plan = []
        agent._plan_day_key = (1, 2)
        agent._plan_evaluated = False
        data = view(school=1)
        data["characters"] = {"girl": {"location": "city"}}
        chosen = agent.choose_action(
            participant="team", view=data, offers=[base_first, better])
        self.assertEqual(chosen["parameters"]["card"], "fi")
        self.assertEqual(agent.diagnostics.get("reason"), "day_plan_variant")


class ChannelSplitTests(unittest.TestCase):
    def agent(self):
        entities = [SimpleNamespace(main_plot="avenger",
                                    roles={"police": "brain",
                                           "worker": "ordinary"})
                    for _ in range(4)]
        entities += [SimpleNamespace(main_plot="avenger",
                                     roles={"police": "ordinary",
                                            "worker": "brain"})
                     for _ in range(4)]
        base = FakeBase(offer("g1", "girl"))
        agent = TwoDayProtagonistAgent(base=base)
        agent._context_key = (1, 3)
        agent._threats = (plot_threat("school", plot="avenger"),)
        agent._obligations = (DefenseObligation(
            plot_threat("school", plot="avenger"), 1, 2, 3),)
        agent._snapshot = BeliefSnapshot(entities, None)
        agent._residual = {}
        agent._covers_today = 0
        return agent, base

    def view(self):
        data = view(school=1)
        data["characters"] = {"police": {"location": "school"},
                              "worker": {"location": "school"},
                              "girl": {"location": "city"}}
        return data

    def test_forbid_then_relocate_covers_both_sources(self):
        agent, base = self.agent()
        first = agent.choose_action(participant="team", view=self.view(),
                                    offers=[offer("fi", "school", actor="a")])
        self.assertEqual(first["parameters"]["card"], "fi")
        second = agent.choose_action(
            participant="team", view=self.view(),
            offers=[offer("h", "police", actor="b"), base.pick])
        self.assertEqual(second["parameters"]["card"], "h")
        third = agent.choose_action(
            participant="team", view=self.view(),
            offers=[offer("h", "worker", actor="c"), base.pick])
        self.assertEqual(third["parameters"]["target"], "worker")

    def test_no_relocation_when_no_suspect_on_board(self):
        agent, base = self.agent()
        data = view(school=1)
        data["characters"] = {"police": {"location": "city"},
                              "worker": {"location": "hospital"}}
        chosen = agent.choose_action(
            participant="team", view=data,
            offers=[offer("h", "police", actor="b"), base.pick])
        self.assertIs(chosen, base.pick)


class MultiSeatResidualTests(unittest.TestCase):
    def test_second_seat_covers_remaining_disjunct(self):
        # Two sampled-world halves: brain=police on school, brain=worker on
        # school. Moving police covers the first half; the second seat should
        # still move worker instead of treating the target as fully covered.
        entities = [SimpleNamespace(main_plot="avenger",
                                    roles={"police": "brain",
                                           "worker": "ordinary"})
                    for _ in range(4)]
        entities += [SimpleNamespace(main_plot="avenger",
                                     roles={"police": "ordinary",
                                            "worker": "brain"})
                     for _ in range(4)]
        snapshot = BeliefSnapshot(entities, None)
        base = FakeBase(offer("g1", "girl"))
        agent = TwoDayProtagonistAgent(base=base)
        agent._context_key = (1, 3)
        agent._threats = (plot_threat("school", plot="avenger"),)
        agent._obligations = (DefenseObligation(
            plot_threat("school", plot="avenger"), 1, 2, 3),)
        agent._snapshot = snapshot
        agent._residual = {}
        agent._covers_today = 0
        data = view(school=1, city=0)
        data["characters"] = {"police": {"location": "school"},
                              "worker": {"location": "school"},
                              "girl": {"location": "city"}}
        first = agent.choose_action(
            participant="team", view=data,
            offers=[offer("h", "police", actor="a"), base.pick])
        self.assertEqual(first["parameters"]["target"], "police")
        second = agent.choose_action(
            participant="team", view=data,
            offers=[offer("h", "worker", actor="b"), base.pick])
        self.assertEqual(second["parameters"]["target"], "worker")

    def test_no_second_cover_after_full_fi_coverage(self):
        base = FakeBase(offer("g1", "girl"))
        agent = TwoDayProtagonistAgent(base=base)
        agent._context_key = (1, 3)
        threat = plot_threat("school", plot="protect")
        agent._threats = (threat,)
        agent._obligations = (DefenseObligation(threat, 1, 2, 3),)
        agent._snapshot = None
        agent._residual = {}
        agent._covers_today = 0
        data = view(school=1)
        data["characters"] = {"police": {"location": "school"}}
        first = agent.choose_action(participant="team", view=data,
                                    offers=[offer("fi", "school", actor="a")])
        self.assertEqual(first["parameters"]["card"], "fi")
        second = agent.choose_action(
            participant="team", view=data,
            offers=[offer("h", "police", actor="b"), base.pick])
        self.assertIs(second, base.pick)


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

    def test_forced_posterior_obligation_covers_before_counter_moves(self):
        base_pick = offer("g1", "girl")
        forced = DefenseObligation(plot_threat("school", plot="protect"),
                                   counter=0, threshold=2, days_left=4,
                                   forced=True)
        agent, _ = agent_with(base_pick, [forced])
        chosen = agent.choose_action(
            participant="team", view=view(school=0),
            offers=[offer("fi", "school"), base_pick])
        self.assertEqual(chosen["parameters"]["card"], "fi")
        self.assertEqual(chosen["parameters"]["target"], "school")

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
