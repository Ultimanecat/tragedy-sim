"""Offline causal audit preserves timing and information boundaries."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from benchmarks.ai_causal_audit import audit_row, causal_evidence, compare_root, main
from tragedy_sim import Game
from tragedy_sim.belief import HiddenWorldHypothesis
from tragedy_sim.scenario_library import ScenarioLibrary
from tests.test_particle_ensemble import protagonist_position


class CausalAuditTests(unittest.TestCase):
    def test_explicit_days_and_loops_select_non_suicide_roots(self):
        from tragedy_sim.replay import dumps
        game = Game({"id": "audit-forced-loss", "title": "audit", "module": "FS",
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
            if game.winner is not None:
                break
            game.dispatch(**game.search_actions(game.controller)[0])
        self.assertEqual(game.winner, "mastermind")
        row = {"replay_text": dumps(game), "strategy": "fixed"}
        default = audit_row(row)
        explicit = audit_row(row, probe_days=(1,), probe_loops=(1,))
        all_roots = audit_row(row, all_days=True)
        self.assertTrue(all(root["evidence"]["day"] != 1 for root in default["roots"]))
        self.assertEqual(len(explicit["roots"]), 1)
        self.assertEqual(explicit["roots"][0]["evidence"]["day"], 1)
        self.assertEqual(explicit["roots"][0]["evidence"]["loop"], 1)
        self.assertGreaterEqual(len(all_roots["roots"]), len(explicit["roots"]))
        self.assertIn("hard_role_domains", explicit["roots"][0]["evidence"])
        self.assertTrue(explicit["losses"])
        self.assertTrue(all(event["kind"] == "loop_lost"
                            for loss in explicit["losses"] for event in loss["loss_events"]))

    def test_cli_filters_rows_and_records_completed_progress(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            output = Path(folder) / "output.json"
            source.write_text(json.dumps({"results": [
                {"scenario": "a", "strategy": "strategic"},
                {"scenario": "b", "strategy": "strategic"},
                {"scenario": "a", "strategy": "joint"}]}), encoding="utf-8")
            with (patch("sys.argv", ["audit", str(source), "--output", str(output),
                                     "--scenario", "a", "--strategy", "strategic",
                                     "--probe-day", "2", "--probe-loop", "3"]),
                  patch("benchmarks.ai_causal_audit.audit_row",
                        return_value={"losses": []}) as mocked, patch("builtins.print")):
                main()
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(mocked.call_args.kwargs["probe_days"], [2])
            self.assertEqual(mocked.call_args.kwargs["probe_loops"], [3])
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["progress"], {"completed": 1, "planned": 1, "complete": True})
            self.assertEqual(len(saved["input_sha256"]), 64)

    def test_cli_does_not_label_partial_work_complete(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            output = Path(folder) / "output.json"
            source.write_text(json.dumps({"results": [
                {"scenario": "a", "strategy": "strategic"},
                {"scenario": "b", "strategy": "strategic"}]}), encoding="utf-8")
            with (patch("sys.argv", ["audit", str(source), "--output", str(output)]),
                  patch("benchmarks.ai_causal_audit.audit_row",
                        side_effect=[{"losses": []}, ValueError("failed")]),
                  patch("builtins.print"), self.assertRaises(ValueError)):
                main()
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["progress"], {"completed": 1, "planned": 2, "complete": False})

    def test_suicide_identifies_culprit_and_friend_reveal_does_not_imply_key(self):
        game = Game(ScenarioLibrary().get("official-btx-04-young-womens-battlefield"))
        view = game.protagonist_team_view()
        view["round"] = 6
        view["characters"]["girl"]["paranoia"] = 3
        view["known_roles"] = {"girl": {"role": "friend"}}
        view["events"] = [
            {"kind": "loop_started", "loop": 1, "round": 1},
            {"kind": "incident_status", "incident": "suicide", "happened": True,
             "loop": 1, "round": 6},
            {"kind": "character_died", "target": "girl", "loop": 1, "round": 6},
            {"kind": "incident_ended", "loop": 1, "round": 6},
            {"kind": "day_ended", "loop": 1, "round": 6},
            {"kind": "role_revealed", "character": "girl", "role": "friend",
             "loop": 1, "round": 6},
            {"kind": "loop_lost", "loop": 1, "round": 6},
        ]
        result = causal_evidence(view, HiddenWorldHypothesis.from_scenario(game.scenario))
        self.assertEqual(result["culprit_options"][6], ("girl",))
        facts = result["causal_witnesses"]
        self.assertTrue(any(w["kind"] == "role_is" and w["value"] == "friend" for w in facts))
        self.assertFalse(any(w["source"] == "public_btx_immediate_death_loss" for w in facts))

    def test_immediate_death_retains_key_or_factor_routes_at_city_threshold(self):
        game = Game(ScenarioLibrary().get("official-btx-08-mirror-passcode"))
        for city in (0, 2):
            view = game.protagonist_team_view()
            view["events"] = [
                {"kind": "loop_started", "loop": 1, "round": 1},
                {"kind": "counter_changed", "target": "city", "counter": "intrigue",
                 "after": city, "loop": 1, "round": 1},
                {"kind": "character_died", "target": "girl", "loop": 1, "round": 1},
                {"kind": "loop_lost", "loop": 1, "round": 1},
            ]
            result = causal_evidence(view)
            fact = next(w for w in result["causal_witnesses"]
                        if w["source"] == "public_btx_immediate_death_loss")
            self.assertEqual(fact["value"]["key"], ("girl",))
            self.assertEqual("factor" in fact["value"], city >= 2)

    def test_same_root_probe_does_not_mutate_game_and_fair_input_is_authorized(self):
        game = protagonist_position()
        before = deepcopy(game.view("m"))
        fair_inputs = []
        from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
        original = ParticleEnsembleProtagonistAgent.choose_action

        def observe(self, *, participant, view, offers):
            fair_inputs.append(deepcopy(view))
            return original(self, participant=participant, view=view, offers=offers)

        with patch.object(ParticleEnsembleProtagonistAgent, "choose_action", observe):
            result = compare_root(game, nodes=2, worlds=2, time_limit_ms=10)
        self.assertEqual(game.view("m"), before)
        self.assertEqual(len(result["comparisons"]), 6)
        self.assertTrue(all(row["legal"] for row in result["comparisons"]))
        self.assertTrue(all(item["card"] is None for view in fair_inputs
                            for item in view["pending"] if item["actor"] == "m"))
        self.assertEqual({row["horizon"] for row in result["comparisons"]}, {"day", "loop"})


if __name__ == "__main__":
    unittest.main()
