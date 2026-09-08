"""Architecture fitness tests for ruleset extension points introduced in R1."""

from dataclasses import dataclass, field
import json
import unittest

from tragedy_sim import Game, Observation, TimingId, Visibility
from tragedy_sim.domain import (
    ActionOffer, Activation, ActivationMode, ComponentStore, CORE_PHASES,
    CounterChange, CustomEffect, FlowPlan, LegacyEffect, PhaseKey,
    ResolutionTrace, RuleSource, StateComponent, normalize_effect,
)


@dataclass
class AhrWorldState(StateComponent):
    component_key = "ahr.world"
    hidden: bool = False
    pending_shift: bool = False


@dataclass
class HsaCurseState(StateComponent):
    component_key = "hsa.board_curses"
    boards: dict[str, list[str]] = field(default_factory=dict)


class DomainContractTests(unittest.TestCase):
    def test_namespaced_keys_and_replaceable_flow(self):
        with self.assertRaises(ValueError):
            PhaseKey("day_end")
        standard = FlowPlan((CORE_PHASES["loop_end"], CORE_PHASES["final_guess"],
                             CORE_PHASES["game_over"]))
        ll_battle = PhaseKey("ll.final_battle")
        replaced = standard.replace(CORE_PHASES["final_guess"], ll_battle)
        self.assertEqual(replaced.phases,
                         (CORE_PHASES["loop_end"], ll_battle, CORE_PHASES["game_over"]))
        self.assertEqual(standard.phases[1], CORE_PHASES["final_guess"])

    def test_action_offer_has_stable_text_independent_identity(self):
        command = {"actor": "a", "action": "play", "card": "move_h", "target": "girl"}
        first = ActionOffer.from_command(command, timing=TimingId.PROTAGONIST_ACTION,
                                         label="移动")
        translated = ActionOffer.from_command(command, timing=TimingId.PROTAGONIST_ACTION,
                                              label="Movement")
        changed = ActionOffer.from_command({**command, "target": "doctor"},
                                           timing=TimingId.PROTAGONIST_ACTION)
        self.assertEqual(first.id, translated.id)
        self.assertNotEqual(first.id, changed.id)
        self.assertEqual(first.command, command)
        json.dumps(first.to_dict(), ensure_ascii=False)

    def test_game_exposes_typed_offers_without_changing_legacy_commands(self):
        game = Game()
        command = game.legal_actions("m")[0]
        offer = game.action_offers("m")[0]
        self.assertEqual(offer.command, command)
        successor = game.simulate(**offer.command)
        self.assertNotEqual(successor.game.state_key("m"), game.state_key("m"))

    def test_typed_effects_cross_the_legacy_resolver_boundary(self):
        game = Game()
        before = game.state.characters["student"].goodwill
        game._queue = [CounterChange("student", "goodwill", 1)]
        game._return_phase = game.state.phase
        game._drain()
        self.assertEqual(game.state.characters["student"].goodwill, before + 1)
        self.assertEqual(normalize_effect(LegacyEffect("kill", {"target": "girl"})),
                         {"kind": "kill", "target": "girl"})

    def test_wm_spell_is_an_extra_offer_at_the_same_timing(self):
        offer = ActionOffer.create(
            actor="a", kind="wm.cast_spell", timing=TimingId.PROTAGONIST_ABILITY,
            source=RuleSource("wm.ex_spell"), parameters={"spell": "sensory"},
            label="发动感官强化",
        )
        activation = Activation(RuleSource("wm.ex_spell"), TimingId.PROTAGONIST_ABILITY,
                                ActivationMode.OPTIONAL, "a", offers=(offer,))
        self.assertEqual(activation.offers[0].kind, "wm.cast_spell")
        self.assertEqual(activation.offers[0].parameters["spell"], "sensory")

    def test_ahr_world_is_component_and_switch_is_effect(self):
        store = ComponentStore((AhrWorldState(),))
        clone = store.clone()
        clone.get(AhrWorldState).hidden = True
        self.assertFalse(store.get(AhrWorldState).hidden)
        self.assertTrue(clone.to_dict()["ahr.world"]["hidden"])
        switch = CustomEffect("ahr.switch_world", {"to": "hidden"})
        self.assertEqual(normalize_effect(switch),
                         {"kind": "ahr.switch_world", "to": "hidden"})

    def test_mz_public_claim_does_not_leak_actual_identity(self):
        public = Observation("role_announced", "忍者公开宣称身份。",
                             visibility=Visibility.PUBLIC,
                             data={"character": "student", "announced_role": "key"},
                             timing=TimingId.INCIDENT)
        trace = ResolutionTrace(
            RuleSource("mz.ninja_confession"), TimingId.INCIDENT,
            CustomEffect("mz.announce_role", {"character": "student", "role": "key"}),
            (public,), {"actual_role": "ninja"},
        )
        projection = public.to_dict()
        self.assertNotIn("source", projection)
        self.assertNotIn("actual_role", json.dumps(projection, ensure_ascii=False))
        self.assertEqual(trace.details["actual_role"], "ninja")
        self.assertEqual(trace.to_dict()["source"], "mz.ninja_confession")

    def test_hsa_curses_live_outside_character_state(self):
        curses = HsaCurseState({"shrine": ["curse_1", "curse_2"]})
        store = ComponentStore((curses,))
        self.assertEqual(store.to_dict()["hsa.board_curses"]["boards"]["shrine"],
                         ["curse_1", "curse_2"])
        self.assertNotIn("character", store.to_dict()["hsa.board_curses"])


if __name__ == "__main__":
    unittest.main()
