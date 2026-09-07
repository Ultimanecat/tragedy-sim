"""Typed transition records and end-to-end plain-text replay tests."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tragedy_sim import Game, MATCH_FLOW, PhaseId, ReplayArchive, ReplaySession, RuleError, TimingId
from tragedy_sim.replay import MAGIC, dumps
from tragedy_sim.scenario import example_scenario


def finish_neutral_match(module="FS"):
    game = Game(example_scenario(module))
    for _ in range(300):
        if game.winner:
            return game
        phase, actor = game.state.phase, game.controller
        if phase == "mastermind":
            number = sum(p.actor == "m" for p in game.state.pending)
            card, target = (("p1a", "school"), ("p1b", "city"),
                            ("h", "shrine"), ("v", "hospital"))[number]
            game.dispatch(actor, "play", card=card, target=target)
        elif phase == "protagonists":
            number = sum(p.actor != "m" for p in game.state.pending)
            game.dispatch(actor, "play", card="g1", target=("student", "doctor", "maiden")[number])
        elif phase == "reveal":
            game.dispatch(actor, "resolve")
        elif phase in ("decision", "refusal"):
            game.dispatch(actor, "choose", index=1)
        elif phase == "final_guess":
            cid = game.view()["guess_remaining"][0]
            game.dispatch(actor, "guess", character=cid,
                          role=game.view("m")["secret"]["initial_roles"][cid])
        else:
            game.dispatch(actor, "next")
    raise AssertionError(f"match did not finish: {module} / {game.state.phase}")


class TransitionRecordTests(unittest.TestCase):
    def test_successful_dispatch_records_typed_transition_and_steps(self):
        game = Game()
        game.dispatch("m", "next")
        record = game.decisions[-1]
        self.assertEqual(record.before.phase, PhaseId.DAY_START)
        self.assertEqual(record.after.phase, PhaseId.MASTERMIND)
        self.assertEqual(record.command, {"actor": "m", "action": "next"})
        self.assertEqual(record.timing, TimingId.DAY_START)
        self.assertIn("结束", record.description)
        self.assertEqual(record.steps[-1].kind, "day_started")
        self.assertEqual(record.steps[-1].timing, TimingId.DAY_START)
        self.assertEqual(record.steps[-1].timepoint, "第 1 天开始时")

    def test_failed_dispatch_is_atomic_and_does_not_create_record(self):
        game = Game()
        before = deepcopy(game.__dict__)
        with self.assertRaises(RuleError):
            game.dispatch("a", "next")
        self.assertEqual(game.__dict__, before)

    def test_state_key_ignores_history_log_but_respects_viewer_information(self):
        game = Game()
        public = game.state_key()
        game._event("diagnostic", "同一状态的额外说明。")
        self.assertEqual(game.state_key(), public)
        self.assertNotEqual(game.state_key(), game.state_key("m"))

    def test_explicit_flow_legal_actions_and_detached_simulation(self):
        game = Game()
        self.assertEqual(MATCH_FLOW.definition("day_start").id, PhaseId.DAY_START)
        self.assertEqual(game.legal_actions("m"), [{"actor": "m", "action": "next"}])
        result = game.simulate("m", "next")
        self.assertEqual(game.state.phase, "day_start")
        self.assertEqual(result.game.state.phase, "mastermind")
        self.assertEqual(result.decision.after.phase, PhaseId.MASTERMIND)
        plays = result.game.legal_actions("m")
        self.assertTrue(plays)
        self.assertTrue(all(action["action"] == "play" for action in plays))
        self.assertEqual(result.game.legal_actions("a"), [])

    def test_phase_machine_rejects_wrong_command_before_mutation(self):
        game = Game()
        before = deepcopy(game.__dict__)
        with self.assertRaisesRegex(RuleError, "当前阶段"):
            game.dispatch("m", "resolve")
        self.assertEqual(game.__dict__, before)


class ReplayTests(unittest.TestCase):
    def test_all_modules_export_parse_and_reach_identical_end_state(self):
        for module in ("FS", "BTX", "MZ"):
            with self.subTest(module=module):
                game = finish_neutral_match(module)
                text = dumps(game)
                self.assertTrue(text.startswith(MAGIC + "\t1\n"))
                self.assertIn("完整信息回放", text)
                self.assertIn("剧作家将", text)
                self.assertIn("[第 1 天剧作家出牌阶段]", text)
                self.assertTrue(all(event["timing"] in {timing.value for timing in TimingId}
                                    for event in game.state.events))
                archive = ReplayArchive.parse(text)
                restored = archive.verify()
                self.assertEqual(restored.view("m"), game.view("m"))
                self.assertEqual(len(restored.decisions), len(game.decisions))

    def test_file_export_is_exclusive_and_session_can_seek(self):
        game = finish_neutral_match()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "match.tlr"
            game.save_replay(path)
            with self.assertRaises(FileExistsError):
                game.save_replay(path)
            session = ReplaySession(ReplayArchive.load(path))
        self.assertEqual(session.index, 0)
        self.assertIsNone(session.current_decision)
        initial = session.public_view()
        session.step(1)
        self.assertEqual(session.index, 1)
        self.assertEqual(session.current_decision.number, 1)
        self.assertNotEqual(session.public_view(), initial)
        session.seek(session.length)
        self.assertEqual(session.game.winner, game.winner)
        with self.assertRaises(RuleError):
            session.seek(session.length + 1)

    def test_incomplete_match_and_tampered_replay_are_rejected(self):
        with self.assertRaises(RuleError):
            dumps(Game())
        game = finish_neutral_match()
        text = dumps(game)
        damaged = text.replace('"action":"next"', '"action":"illegal"', 1)
        with self.assertRaises(RuleError):
            ReplayArchive.parse(damaged)


if __name__ == "__main__":
    unittest.main()
