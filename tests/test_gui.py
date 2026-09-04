"""Hotseat privacy/controller tests plus a native Tk rendering smoke test."""

from copy import deepcopy
import unittest

from tragedy_sim import Game, RuleError
from tragedy_sim.hotseat import HotseatSession, character_details, public_knowledge, public_log, public_rules, secret_dossier
from tragedy_sim.scenario import example_scenario


class HotseatSessionTests(unittest.TestCase):
    def test_shared_view_never_follows_private_seat(self):
        session = HotseatSession(Game(example_scenario("BTX")))
        public = session.public_view()
        self.assertNotIn("secret", public)
        self.assertEqual(public["hand"], [])
        session.unlock("m")
        private = session.private_view()
        self.assertIn("secret", private)
        self.assertEqual(len(private["hand"]), 10)
        self.assertEqual(session.public_view(), public)
        session.hide()
        self.assertIsNone(session.private_view())
        self.assertEqual(session.options(), [])

    def test_handoff_hides_when_controller_changes_but_not_same_seat(self):
        session = HotseatSession(Game())
        session.unlock("m")
        session.act(session.token, "next")
        self.assertEqual(session.seat, "m")
        for card, target in (("p1a", "student"), ("p1b", "doctor")):
            session.act(session.token, "play", card=card, target=target)
            self.assertEqual(session.seat, "m")
        session.act(session.token, "play", card="h", target="maiden")
        self.assertIsNone(session.seat)
        self.assertEqual(session.expected_seat, "a")
        session.unlock("a")
        session.act(session.token, "play", card="g1", target="student")
        self.assertIsNone(session.seat)
        self.assertEqual(session.expected_seat, "b")

    def test_stale_controls_cannot_dispatch_twice(self):
        session = HotseatSession(Game())
        session.unlock("m")
        token = session.token
        session.act(token, "next")
        snapshot = deepcopy(session.game.__dict__)
        with self.assertRaises(RuleError):
            session.act(token, "next")
        self.assertEqual(session.game.__dict__, snapshot)

    def test_legal_targets_follow_living_and_side_occupancy(self):
        session = HotseatSession(Game())
        session.game.state.characters["patient"].alive = False
        session.unlock("m")
        session.act(session.token, "next")
        targets = session.legal_targets()
        self.assertNotIn("patient", targets)
        self.assertIn("hospital", targets)
        session.act(session.token, "play", card="p1a", target="doctor")
        self.assertNotIn("doctor", session.legal_targets())
        session.act(session.token, "play", card="p1b", target="hospital")
        self.assertNotIn("hospital", session.legal_targets())

    def test_early_final_guess_is_a_separate_leader_handoff(self):
        session = HotseatSession(Game(example_scenario("BTX")))
        session.game.state.phase = "loop_end"
        session.request_final_guess()
        self.assertEqual(session.expected_seat, "a")
        self.assertIsNone(session.seat)
        session.unlock("a")
        token = session.token
        with self.assertRaises(RuleError):
            session.act(token, "next")
        session.act(token, "final")
        self.assertEqual(session.game.state.phase, "final_guess")
        self.assertEqual(session.seat, "a")
        self.assertIsNone(session.intent)

    def test_savepoint_and_replace_privacy(self):
        session = HotseatSession(Game())
        session.unlock("m")
        session.act(session.token, "next")
        self.assertTrue(session.dirty)
        other = Game(example_scenario("BTX"))
        session.replace(other)
        self.assertIs(session.game, other)
        self.assertFalse(session.dirty)
        self.assertIsNone(session.seat)

    def test_formatters_only_put_secrets_in_explicit_dossier(self):
        game = Game()
        public, private = game.view(), game.view("m")
        combined = public_log(public) + public_knowledge(public) + public_rules("FS")
        self.assertNotIn("规则 Y：谋杀计划", combined)
        self.assertNotIn("女学生：关键人物", combined)
        dossier = secret_dossier(private)
        self.assertIn("规则 Y：谋杀计划", dossier)
        self.assertIn("女学生：关键人物", dossier)
        self.assertIn("不安临界", character_details(public, "girl"))


class TkSmokeTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        self.tk = tk
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        self.root.withdraw()

    def tearDown(self):
        if hasattr(self, "root"):
            self.root.destroy()

    def test_renders_locked_private_cards_and_public_state(self):
        from tragedy_sim.gui import TragedyApp
        app = TragedyApp(self.root, Game(example_scenario("BTX")))
        self.root.update_idletasks()
        self.assertIn("unlock", app.controls)
        self.assertNotIn("card:p1a", app.controls)
        self.assertNotIn("secret", app.session.public_view())
        app.unlock("m")
        app.perform(app.session.token, "next")
        self.root.update_idletasks()
        self.assertIn("card:p1a", app.controls)
        self.assertIsNotNone(app.private_notebook)
        self.assertEqual(app.private_notebook.tabs().__len__(), 2)
        app.hide()
        self.root.update_idletasks()
        self.assertNotIn("card:p1a", app.controls)

    def test_selection_then_dispatch_uses_engine_and_handoff(self):
        from tragedy_sim.gui import TragedyApp
        app = TragedyApp(self.root, Game())
        app.unlock("m")
        token = app.session.token
        app.perform(token, "next")
        for card, target in (("p1a", "student"), ("p1b", "doctor"), ("h", "maiden")):
            app.select_card(card)
            app.selected_target = target
            app._play_enabled()
            app.perform(app.session.token, "play", card=card, target=target)
        self.assertIsNone(app.session.seat)
        self.assertEqual(app.session.expected_seat, "a")
        self.assertEqual(app.session.game.state.phase, "protagonists")
        self.assertEqual(len(app.session.public_view()["pending"]), 3)
        self.assertTrue(all(item["card"] is None for item in app.session.public_view()["pending"]))

    def test_complete_gui_callback_flow_for_both_modules(self):
        from tragedy_sim.gui import TragedyApp
        for module in ("FS", "BTX"):
            with self.subTest(module=module):
                app = TragedyApp(self.root, Game(example_scenario(module)))
                for _ in range(180):
                    if app.session.game.winner:
                        break
                    if app.session.seat is None:
                        self.assertIn("unlock", app.controls)
                        app.unlock(app.session.expected_seat)
                    game, phase, token = app.session.game, app.session.game.state.phase, app.session.token
                    if phase == "mastermind":
                        n = len(game.state.pending)
                        card, target = (("p1a", "school"), ("p1b", "city"), ("h", "shrine"))[n]
                        self.assertIn("card:" + card, app.controls)
                        app.perform(token, "play", card=card, target=target)
                    elif phase == "protagonists":
                        n = sum(p.actor != "m" for p in game.state.pending)
                        self.assertIn("card:g1", app.controls)
                        app.perform(token, "play", card="g1", target=("student", "doctor", "maiden")[n])
                    elif phase == "reveal":
                        self.assertIn("resolve", app.controls)
                        app.perform(token, "resolve")
                    else:
                        self.assertIn("next", app.controls)
                        app.perform(token, "next")
                    self.root.update_idletasks()
                self.assertEqual(app.session.game.winner, "protagonists")
                self.assertIn("另存完整对局", " ".join(child.cget("text") for child in app.private.winfo_children() if "text" in child.keys()))
                for child in self.root.winfo_children():
                    child.destroy()


if __name__ == "__main__":
    unittest.main()
